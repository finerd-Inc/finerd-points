#!/usr/bin/env python3
"""finerd points ledger command line.

Every command prints JSON (or the preview text) and exits 2 with a plain-English
refusal when something is unsafe. Run with `-h` for the list.

Typical write cycle:
  ledger.py lease acquire --ledger L --session S
  ledger.py preview --ledger L --batch batch.json        # show the text to the person
  ledger.py apply --ledger L --batch batch.json --confirm <hash> --session S
  # for each planned external write: perform it through the person's connector, then
  ledger.py op --ledger L --session S --op-id op-… --state confirmed --destination-id … --read-back '{…}'
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpledger as fl  # noqa: E402


def _json_arg(v):
    if v is None:
        return None
    if v.startswith("@"):
        return json.loads(Path(v[1:]).read_text(encoding="utf-8"))
    return json.loads(v)


def out(obj):
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def cmd_init(a):
    p = Path(a.ledger)
    p.parent.mkdir(parents=True, exist_ok=True)
    led = fl.new_ledger(a.name, a.currency, a.timezone, a.storage, a.household)
    led["_meta"]["setup"]["location"] = a.location or p.name
    if a.session:
        fl.acquire_lease(led, a.session)
    v = fl.create(p, led)  # refuses if anything exists at that path
    out({"created": str(p), "ledger_id": led["ledger_id"], "version": v,
         "setup_record": setup_record(led)})


def _marker(ledger_path, h):
    p = Path(ledger_path)
    return p.with_name(f".{p.name}.preview-{h}")


def setup_record(led):
    s = led["_meta"]["setup"]
    return {
        "ledger_id": led["ledger_id"], "storage": s["storage"], "location": s["location"],
        "calendar_id": s["calendar_id"], "timezone": s["timezone"], "household_mode": s["household_mode"],
        "report_currency": s["report_currency"], "writer": (led["_meta"].get("writer") or {}).get("session"),
        "note": "Keep this record. A new conversation needs the ledger file (or the sheet link) to continue; "
                "it never creates a second ledger.",
    }


def cmd_show(a):
    led = fl.load(a.ledger)
    if a.section == "setup":
        out(setup_record(led))
    elif a.section:
        if a.section not in fl.COLLECTIONS:
            raise fl.LedgerError(f"Section must be setup or one of {', '.join(fl.COLLECTIONS)}.")
        out(led[a.section])
    else:
        out(fl.summary(led))


def cmd_lease(a):
    led = fl.load(a.ledger)
    base = led["version"]
    if a.action == "status":
        out(fl.lease_status(led))
        return
    if a.action in ("acquire", "renew"):
        w = fl.acquire_lease(led, a.session, transfer=a.transfer)
    else:
        fl.release_lease(led, a.session)
        w = None
    v = fl.save(a.ledger, led, base)
    out({"writer": w, "version": v})


def cmd_preview(a):
    led = fl.load(a.ledger)
    batch = _json_arg("@" + a.batch)
    h, text = fl.preview_batch(led, batch)
    _marker(a.ledger, h).write_text(fl.iso(fl.now_utc()) + "\n", encoding="utf-8")
    if a.json:
        out({"hash": h, "preview": text})
    else:
        print(text)


def cmd_apply(a):
    led = fl.load(a.ledger)
    base = led["version"]
    batch = _json_arg("@" + a.batch)
    marker = _marker(a.ledger, a.confirm)
    if not marker.exists():
        raise fl.LedgerError("Run `preview` for this batch and show its text to the person before applying it.")
    age = fl.now_utc().timestamp() - marker.stat().st_mtime
    if age > 3600:
        raise fl.LedgerError("That preview is more than an hour old. Run `preview` again and show it to the person.")
    fl.ensure_lease(led, a.session)  # renew our lease, or take an expired one; never a live one of another chat
    results = fl.apply_batch(led, batch, a.confirm, a.session)
    v = fl.save(a.ledger, led, base)
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    out({"version": v, "results": results,
         "external_to_perform": [x for x in led["oplog"] if x["state"] == "planned"]})


def cmd_op(a):
    led = fl.load(a.ledger)
    base = led["version"]
    fl.ensure_lease(led, a.session)
    op = fl.set_op_state(led, a.op_id, a.state, a.session, a.destination_id, _json_arg(a.read_back), a.error)
    v = fl.save(a.ledger, led, base)
    out({"version": v, "op": op})


def cmd_pending(a):
    out(fl.pending_ops(fl.load(a.ledger)))


def cmd_current(a):
    out(fl.current(fl.load(a.ledger), a.subject, a.field))


def cmd_export(a):
    out({"written": fl.export_csv(fl.load(a.ledger), a.out)})


def cmd_redact(a):
    led = fl.load(a.ledger)
    if not a.confirm:
        h, plan, text = fl.redaction_plan(led, a.person)
        print(text)
        return
    base = led["version"]
    fl.ensure_lease(led, a.session)
    ops = fl.redact_person(led, a.person, a.confirm, a.session)
    v = fl.save(a.ledger, led, base)
    out({"version": v, "calendar_updates_to_preview": ops})


def cmd_validate(a):
    led = fl.load(a.ledger)
    out({"ok": True, "version": led["version"], "schema_version": led["schema_version"]})


def main(argv=None):
    ap = argparse.ArgumentParser(description="finerd points ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a new ledger (refuses if the file exists)")
    s.add_argument("--ledger", required=True)
    s.add_argument("--name", required=True, help="the owner's first name or nickname")
    s.add_argument("--currency", default="USD")
    s.add_argument("--timezone", default="UTC")
    s.add_argument("--storage", choices=["file", "folder"], default="file",
                   help="a Google Sheet is an export (ledger.py export) until the platform probe passes")
    s.add_argument("--household", choices=["single", "shared", "separate"], default="single")
    s.add_argument("--location", help="where the person keeps it (file name, folder or sheet link)")
    s.add_argument("--session")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("show")
    s.add_argument("--ledger", required=True)
    s.add_argument("--section")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("lease")
    s.add_argument("action", choices=["acquire", "renew", "release", "status"])
    s.add_argument("--ledger", required=True)
    s.add_argument("--session")
    s.add_argument("--transfer", action="store_true", help="only after the person hands write access over")
    s.set_defaults(fn=cmd_lease)

    s = sub.add_parser("preview")
    s.add_argument("--ledger", required=True)
    s.add_argument("--batch", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("apply")
    s.add_argument("--ledger", required=True)
    s.add_argument("--batch", required=True)
    s.add_argument("--confirm", required=True, help="the batch hash from the preview the person saw")
    s.add_argument("--session", required=True)
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("op", help="record the outcome of an external write")
    s.add_argument("--ledger", required=True)
    s.add_argument("--session", required=True)
    s.add_argument("--op-id", required=True)
    s.add_argument("--state", required=True, choices=list(fl.OP_STATES))
    s.add_argument("--destination-id")
    s.add_argument("--read-back", help="JSON (or @file) with the values read back from the destination")
    s.add_argument("--error")
    s.set_defaults(fn=cmd_op)

    s = sub.add_parser("pending")
    s.add_argument("--ledger", required=True)
    s.set_defaults(fn=cmd_pending)

    s = sub.add_parser("current")
    s.add_argument("--ledger", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--field", required=True)
    s.set_defaults(fn=cmd_current)

    s = sub.add_parser("export")
    s.add_argument("--ledger", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("redact", help="a household member's privacy withdrawal")
    s.add_argument("--ledger", required=True)
    s.add_argument("--person", required=True)
    s.add_argument("--confirm")
    s.add_argument("--session")
    s.set_defaults(fn=cmd_redact)

    s = sub.add_parser("validate")
    s.add_argument("--ledger", required=True)
    s.set_defaults(fn=cmd_validate)

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
