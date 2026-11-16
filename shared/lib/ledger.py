#!/usr/bin/env python3
"""finerd points ledger command line (spec v2).

The ledger lives in a folder on the person's computer (default «~/finerd points») and is written only
through bin/commit there. Every command prints JSON (or the preview text) and exits 2 with a
plain-English refusal when something is unsafe. Run with `-h` for the list.

Claude Code and Cowork (the folder is on this computer):
  ledger.py setup     --folder F --name N --timezone TZ --currency USD   # once; installs bin/commit
  ledger.py open      --folder F --cleanup                               # every conversation
  ledger.py plan-read --folder F --read read.json --out batch.json       # what a read of a site adds
  ledger.py preview   --folder F --batch batch.json                      # show this text to the person
  ledger.py apply     --folder F --batch batch.json --confirm <hash>     # after their yes

Claude chat with the person's computer connected (the folder is reached through the connector):
  bring ledger.json into the conversation, then
  ledger.py preview --ledger ledger.json --batch batch.json --save seen.json
  ledger.py chat-prepare --ledger ledger.json --base-hash H --batch batch.json --confirm <hash> \\
                         --seen seen.json --out outbox
  deliver the outbox files into <folder>/work/ under their own names (never overwriting), run on the
  computer the command chat-prepare prints, and read its RESULT line.

A ledger file without its folder is read-only (limited mode): show, current, pending, export.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpledger as fl  # noqa: E402
import fpcollect as fc  # noqa: E402
import fpstore as st  # noqa: E402


def _json_arg(v):
    if v is None:
        return None
    if v.startswith("@"):
        return json.loads(Path(v[1:]).read_text(encoding="utf-8"))
    return json.loads(v)


def out(obj):
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def _read(a):
    """(ledger, base hash, base version, folder or None)."""
    if getattr(a, "folder", None):
        led, bh, bv = st.read(a.folder)
        if led is None:
            raise fl.LedgerError(f"There is no ledger in {a.folder} yet. Run setup first.")
        return led, bh, bv, a.folder
    if getattr(a, "ledger", None):
        data = Path(a.ledger).read_bytes()
        led = fl.loads(data.decode("utf-8"))
        return led, hashlib.sha256(data).hexdigest(), led["version"], None
    raise fl.LedgerError("Give the ledger folder (--folder) or, read-only, a ledger file (--ledger).")


def _need_folder(a, what):
    if not getattr(a, "folder", None):
        raise fl.LedgerError(f"{what} changes the ledger, and the ledger changes only in its folder through "
                             f"bin/commit. Without the folder (limited mode) finerd points only reads.")


def setup_record(led, folder=None):
    s = led["_meta"]["setup"]
    return {
        "ledger_id": led["ledger_id"], "version": led["version"], "storage": s["storage"],
        "folder": str(folder) if folder else s.get("location"), "timezone": s["timezone"],
        "household_mode": s["household_mode"], "report_currency": s["report_currency"],
        "history_from": s.get("history_from"),
        "note": "A new conversation opens this folder; it never creates a second ledger.",
    }


# ---------------------------------------------------------------- commands

def cmd_setup(a):
    root, warnings = st.install(a.folder)
    led, _, _ = st.read(root)
    if led is not None:
        out({"exists": True, "setup_record": setup_record(led, root), "warnings": warnings})
        return
    if a.import_file:
        led = fl.load(a.import_file)
        led["_meta"]["setup"]["storage"] = "folder"
        led["_meta"]["writer"] = None
    else:
        led = fl.new_ledger(a.name, a.currency, a.timezone, "folder", a.household)
    led["_meta"]["setup"]["location"] = str(root)
    res = st.create(root, led, writer=a.writer)
    if res.get("result") != "committed":
        raise fl.LedgerError(f"The first ledger was not written: {res.get('reason')}")
    out({"created": str(root), "version": int(res["version"]), "setup_record": setup_record(led, root),
         "warnings": warnings})


def cmd_open(a):
    root = Path(a.folder).expanduser().resolve()
    reinstalled = st.install_script(root) if a.reinstall else False
    chk = st.check(root)
    removed = st.cleanup(root) if a.cleanup else []
    led, bh, bv = st.read(root)
    res = {"version": bv, "hash": bh,
           "check": {k: chk.get(k) for k in ("result", "chain", "recovered", "problems", "notes")},
           "cleaned_up": len(removed), "script_reinstalled": reinstalled}
    if led is not None:
        res["summary"] = fl.summary(led)
        res["forbidden"] = fl.forbidden_report(led)
        res["abandoned"] = [x.split()[0] for x in chk.get("recovered", []) if x.endswith("abandoned")]
    out(res)
    if chk.get("exit") not in (0, None):
        sys.exit(2)


def cmd_show(a):
    led, bh, bv, folder = _read(a)
    if a.section == "setup":
        out(setup_record(led, folder))
    elif a.section:
        if a.section not in fl.COLLECTIONS:
            raise fl.LedgerError(f"Section must be setup or one of {', '.join(fl.COLLECTIONS)}.")
        out(led[a.section])
    else:
        out({**fl.summary(led), "hash": bh})


def cmd_plan_read(a):
    led = _read(a)[0]
    reads = _json_arg("@" + a.read)
    reads = reads if isinstance(reads, list) else [reads]
    batch, summaries = fc.plan_reads(led, reads)
    Path(a.out).write_text(json.dumps(batch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out({"batch": a.out, "operations": len(batch), "summaries": summaries})


def cmd_preview(a):
    batch = _json_arg("@" + a.batch)
    if getattr(a, "folder", None):
        h, text = st.preview(a.folder, batch)
    else:
        led = _read(a)[0]
        h, text = fl.preview_batch(led, batch)
        if a.save:
            Path(a.save).write_text(json.dumps({"hash": h, "base_version": led["version"], "text": text,
                                                "at": fl.iso(fl.now_utc())}, ensure_ascii=False), encoding="utf-8")
    if a.json:
        out({"hash": h, "preview": text})
    else:
        print(text)


def cmd_apply(a):
    _need_folder(a, "apply")
    batch = _json_arg("@" + a.batch)
    res = st.apply_and_publish(a.folder, batch, a.confirm, writer=a.writer, summary=a.summary or "")
    if res.get("result") == "committed":
        led, _, _ = st.read(a.folder)
        res["external_to_perform"] = [x for x in led["oplog"] if x["state"] == "planned"]
    out(res)
    if res.get("result") not in ("committed", "needs_preview"):
        sys.exit(2)


def _publish_change(a, change, summary):
    """Read, change in memory, publish; once more when another writer published first."""
    res = {}
    for _ in range(2):
        led, bh, bv = st.read(a.folder)
        result = change(led)
        res = st.publish(a.folder, led, bh, bv, writer=a.writer, summary=summary)
        if res.get("result") == "committed":
            return res, result
        if res.get("code") != "10":
            break
    raise fl.LedgerError(f"The change was not written: {res.get('reason')}")


def cmd_op(a):
    _need_folder(a, "op")
    res, op = _publish_change(a, lambda led: fl.set_op_state(
        led, a.op_id, a.state, None, a.destination_id, _json_arg(a.read_back), a.error), f"external {a.op_id}")
    out({"version": int(res["version"]), "op": op})


def cmd_redact(a):
    led = _read(a)[0]
    if not a.confirm:
        _, _, text = fl.redaction_plan(led, a.person)
        print(text)
        return
    _need_folder(a, "redact")
    res, ops = _publish_change(a, lambda l: fl.redact_person(l, a.person, a.confirm), f"remove {a.person}")
    out({"version": int(res["version"]), "calendar_updates_to_preview": ops})


def cmd_pending(a):
    out(fl.pending_ops(_read(a)[0]))


def cmd_current(a):
    out(fl.current(_read(a)[0], a.subject, a.field))


def cmd_export(a):
    out({"written": fl.export_csv(_read(a)[0], a.out)})


def cmd_validate(a):
    led = _read(a)[0]
    out({"ok": True, "version": led["version"], "schema_version": led["schema_version"]})


def cmd_script_hash(a):
    out({"script": str(st.SCRIPT), "sha256": st.script_hash()})


def cmd_chat_prepare(a):
    """Build what a chat delivers into <folder>/work/ and the bin/commit command to run there."""
    data = Path(a.ledger).read_bytes()
    if hashlib.sha256(data).hexdigest() != a.base_hash:
        raise fl.LedgerError("The ledger copy in this conversation is not the one whose hash the computer reported. "
                             "Bring ledger.json in again.")
    led = fl.loads(data.decode("utf-8"))
    batch = _json_arg("@" + a.batch)
    seen = json.loads(Path(a.seen).read_text(encoding="utf-8"))
    expected = fl.sha({"base": seen["base_version"], "ledger": led["ledger_id"], "batch": batch})
    if seen.get("hash") != a.confirm or expected != a.confirm:
        raise fl.LedgerError("This batch is not the one the person saw (hash mismatch). Show the preview again.")
    if fl.now_utc().timestamp() - fl.parse_iso(seen["at"]).timestamp() > st.PREVIEW_MAX_AGE:
        raise fl.LedgerError("That preview is more than an hour old. Show it to the person again.")
    h, text = fl.preview_batch(led, batch)
    if st._preview_lines(text) != st._preview_lines(seen["text"]):
        out({"result": "needs_preview", "preview": text, "hash": h,
             "reason": "The ledger changed in another conversation and this batch now reads differently."})
        return
    fl.apply_batch(led, batch, h)
    op_id = st.new_op_id()
    bv = led["version"]
    cand = st.prepare_candidate(led, bv, op_id, "chat", a.summary or "")
    outbox = Path(a.out)
    outbox.mkdir(parents=True, exist_ok=True)
    name = f"cand-{op_id}.json"
    payload = st.serialize(cand)
    ch = hashlib.sha256(payload).hexdigest()
    (outbox / name).write_bytes(payload)
    (outbox / (name + ".meta")).write_text(f"protocol={st.PROTOCOL}\nop_id={op_id}\nversion={bv + 1}\nhash={ch}\n")
    (outbox / (name + ".batch.json")).write_text(json.dumps(batch, ensure_ascii=False) + "\n", encoding="utf-8")
    out({"result": "prepared", "deliver_into_work": [name, name + ".meta", name + ".batch.json"],
         "commit_args": ["commit", op_id, a.base_hash, str(bv), name, ch],
         "run_on_computer": f'sh "<folder>/bin/commit" commit {op_id} {a.base_hash} {bv} {name} {ch}',
         "expect": f"RESULT=committed VERSION={bv + 1} HASH={ch}"})


def main(argv=None):
    ap = argparse.ArgumentParser(description="finerd points ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def where(s, folder_only=False):
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--folder", help="the ledger folder, for example '~/finerd points'")
        if not folder_only:
            g.add_argument("--ledger", help="a ledger file, read-only (limited mode, or a chat's copy)")
        s.add_argument("--writer", default="claude-code", choices=["claude-code", "cowork", "chat"])

    s = sub.add_parser("setup", help="create the ledger folder, install bin/commit and write the first ledger")
    s.add_argument("--folder", default=st.DEFAULT_FOLDER)
    s.add_argument("--name", default="Me", help="the owner's first name or nickname")
    s.add_argument("--currency", default="USD")
    s.add_argument("--timezone", default="UTC")
    s.add_argument("--household", choices=["single", "shared", "separate"], default="single")
    s.add_argument("--import-file", help="a v1 ledger file to move into the folder")
    s.add_argument("--writer", default="claude-code", choices=["claude-code", "cowork", "chat"])
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("open", help="every conversation: recover, check the journal chain, summarize")
    s.add_argument("--folder", required=True)
    s.add_argument("--cleanup", action="store_true", help="remove old work files and released locks (not in chat)")
    s.add_argument("--reinstall", action="store_true", help="put this version's bin/commit in place first")
    s.set_defaults(fn=cmd_open)

    s = sub.add_parser("show")
    where(s)
    s.add_argument("--section")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("plan-read", help="turn what was read from a site into a batch for the preview")
    where(s)
    s.add_argument("--read", required=True, help="JSON file: one read or a list of reads")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_plan_read)

    s = sub.add_parser("preview")
    where(s)
    s.add_argument("--batch", required=True)
    s.add_argument("--save", help="with --ledger: where to keep what the person saw (for chat-prepare)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("apply")
    where(s, folder_only=True)
    s.add_argument("--batch", required=True)
    s.add_argument("--confirm", required=True, help="the batch hash from the preview the person saw")
    s.add_argument("--summary", help="a few words for the commit log")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("op", help="record the outcome of an external write")
    where(s, folder_only=True)
    s.add_argument("--op-id", required=True)
    s.add_argument("--state", required=True, choices=list(fl.OP_STATES))
    s.add_argument("--destination-id")
    s.add_argument("--read-back", help="JSON (or @file) with the values read back from the destination")
    s.add_argument("--error")
    s.set_defaults(fn=cmd_op)

    for name, fn in (("pending", cmd_pending), ("validate", cmd_validate)):
        s = sub.add_parser(name)
        where(s)
        s.set_defaults(fn=fn)

    s = sub.add_parser("current")
    where(s)
    s.add_argument("--subject", required=True)
    s.add_argument("--field", required=True)
    s.set_defaults(fn=cmd_current)

    s = sub.add_parser("export")
    where(s)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("redact", help="a household member's privacy withdrawal")
    where(s)
    s.add_argument("--person", required=True)
    s.add_argument("--confirm")
    s.set_defaults(fn=cmd_redact)

    s = sub.add_parser("script-hash", help="the sha256 bin/commit must have")
    s.set_defaults(fn=cmd_script_hash)

    s = sub.add_parser("chat-prepare", help="chat: build the candidate and the bin/commit command")
    s.add_argument("--ledger", required=True, help="ledger.json brought into the conversation")
    s.add_argument("--base-hash", required=True, help="sha256 of ledger.json as the computer reported it")
    s.add_argument("--batch", required=True)
    s.add_argument("--confirm", required=True)
    s.add_argument("--seen", required=True, help="the file `preview --save` wrote")
    s.add_argument("--out", required=True)
    s.add_argument("--summary")
    s.set_defaults(fn=cmd_chat_prepare)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}, ensure_ascii=False))
        sys.exit(2)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as e:
        print(json.dumps({"refused": f"The input could not be used ({type(e).__name__}: {e}). Check the batch or "
                                     f"file and try again."}, ensure_ascii=False))
        sys.exit(2)


if __name__ == "__main__":
    main()
