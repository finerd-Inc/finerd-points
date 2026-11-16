"""finerd points ledger folder (spec v2, appendix E). Python 3.9+, standard library only.

The ledger is one `ledger.json` in a dedicated folder, with these beside it:
  bin/commit   the commit script (fp_commit.sh), the only thing that replaces ledger.json
  work/        candidates and working files (redacted like the ledger)
  journal/     one entry per commit: planned → committed | abandoned
  backups/     the version each commit replaced
  locks/       released locks (renamed, never deleted: a chat may rename but not delete)
  reports/     the HTML report when the host cannot show one in the conversation

Every writer — Claude Code, Cowork, or a chat working through the person's connected computer —
stages a candidate in work/ and runs bin/commit. The connector's own overwrite of ledger.json is
never used.
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

import fpledger as fl
import fpcollect  # noqa: F401  (registers the schema-2 operations)

PROTOCOL = 1
SCRIPT = Path(__file__).resolve().with_name("fp_commit.sh")
SUBDIRS = ("bin", "work", "journal", "backups", "locks", "reports")
OWN_NAMES = set(SUBDIRS) | {"ledger.json", ".lock", ".lock-guard", ".DS_Store"}
DEFAULT_FOLDER = "~/finerd points"
# Paths that are certainly synced by a cloud client; a ledger there can get conflict copies.
CLOUD_PARTS = ("Library/CloudStorage", "Library/Mobile Documents", "Dropbox", "OneDrive", "Google Drive",
               "iCloud Drive", "Box Sync")
MAYBE_SYNCED = ("Documents", "Desktop")  # iCloud «Desktop & Documents» may sync these
OP_RE = re.compile(r"^[0-9a-f][0-9a-f-]{7,63}$")
BACKUPS_KEEP = 20


class StoreError(fl.LedgerError):
    pass


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def script_hash():
    return file_sha(SCRIPT)


def new_op_id():
    return f"{secrets.token_hex(8)}-{secrets.token_hex(4)}"


# ---------------------------------------------------------------- the folder

def check_folder(folder):
    """Resolve the folder and refuse places that are not a dedicated, unsynced ledger folder.
    Returns (path, warnings)."""
    p = Path(folder).expanduser()
    root = p.resolve()
    home = Path.home().resolve()
    if root in (Path("/"), home, home.parent) or root.parent == Path("/"):
        raise StoreError(f"{root} is not a dedicated folder. Choose a folder only for the ledger, "
                         f"such as {DEFAULT_FOLDER}.")
    s = str(root)
    for part in CLOUD_PARTS:
        if f"/{part}" in s:
            raise StoreError(f"{root} is inside a cloud-synced folder ({part}). Sync can create conflicting copies "
                             f"of the ledger; choose a folder outside it, such as {DEFAULT_FOLDER}.")
    warnings = []
    try:
        rel = root.relative_to(home)
        if rel.parts and rel.parts[0] in MAYBE_SYNCED:
            warnings.append(f"{rel.parts[0]} may be synced by iCloud on this Mac; {DEFAULT_FOLDER} is safer.")
    except ValueError:
        pass
    if root.exists():
        if not root.is_dir():
            raise StoreError(f"{root} is a file, not a folder.")
        foreign = sorted(x.name for x in root.iterdir() if x.name not in OWN_NAMES)
        if foreign:
            raise StoreError(f"{root} already holds other files ({', '.join(foreign[:5])}). Choose an empty folder "
                             f"only for the ledger.")
    return root, warnings


def install(folder):
    """Create the folder layout and install bin/commit. Choosing the folder approves this.
    Returns (path, warnings)."""
    root, warnings = check_folder(folder)
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    if created:
        os.chmod(root, 0o700)
    for d in SUBDIRS:
        (root / d).mkdir(exist_ok=True)
    install_script(root)
    return root, warnings


def install_script(root):
    """Put this skill's copy of the commit script at bin/commit (replaced, never edited in place).
    Returns True if it was (re)installed."""
    dst = Path(root) / "bin" / "commit"
    if dst.exists() and file_sha(dst) == script_hash():
        return False
    dst.parent.mkdir(exist_ok=True)
    tmp = dst.with_name(f".commit-{secrets.token_hex(4)}")
    tmp.write_bytes(SCRIPT.read_bytes())
    os.chmod(tmp, 0o700)
    os.replace(tmp, dst)
    return True


def _root(folder):
    root = Path(folder).expanduser().resolve()
    if not (root / "bin").is_dir():
        raise StoreError(f"{root} is not a finerd points ledger folder (no bin/). Set it up first.")
    return root


# ---------------------------------------------------------------- read

def read(folder):
    """Return (ledger or None, base_hash, base_version). The hash is of the exact bytes parsed."""
    root = _root(folder)
    p = root / "ledger.json"
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        return None, "none", 0
    led = fl.loads(data.decode("utf-8"))
    return led, hashlib.sha256(data).hexdigest(), led["version"]


# ---------------------------------------------------------------- commit

def _write_new(path, data):
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def serialize(led):
    return (json.dumps(led, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def stage(folder, candidate, base_version, op_id, batch=None):
    """Write the candidate, its meta file and the batch into work/. Returns (name, hash)."""
    root = _root(folder)
    if not OP_RE.match(op_id):
        raise StoreError("Bad operation id.")
    data = serialize(candidate)
    h = hashlib.sha256(data).hexdigest()
    name = f"cand-{op_id}.json"
    w = root / "work" / name
    _write_new(w, data)
    _write_new(w.with_name(name + ".meta"),
               f"protocol={PROTOCOL}\nop_id={op_id}\nversion={base_version + 1}\nhash={h}\n".encode())
    if batch is not None:
        _write_new(w.with_name(name + ".batch.json"), (json.dumps(batch, ensure_ascii=False) + "\n").encode())
    return name, h


def parse_output(text):
    out = {"notes": [], "recovered": [], "problems": []}
    for line in text.splitlines():
        if line.startswith("RESULT="):
            head, _, reason = line.partition(" REASON=")
            for tok in head.split():
                k, _, v = tok.partition("=")
                out[k.lower()] = v
            if reason:
                out["reason"] = reason
        elif line.startswith("NOTE="):
            out["notes"].append(line[5:])
        elif line.startswith("RECOVERED="):
            out["recovered"].append(line[10:])
        elif line.startswith("PROBLEM="):
            out["problems"].append(line[8:])
        elif line.startswith("CHAIN="):
            out["chain"] = line[6:]
    return out


def run_script(folder, args, env=None, timeout=300):
    root = _root(folder)
    script = root / "bin" / "commit"
    if not script.exists() or file_sha(script) != script_hash():
        raise StoreError("bin/commit in the ledger folder is missing or differs from this version of finerd points. "
                         "Run setup again to reinstall it before writing.")
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(["/bin/sh", str(script), *args], capture_output=True, text=True, env=e, timeout=timeout)
    res = parse_output(p.stdout)
    res["exit"] = p.returncode
    if p.stderr.strip():
        res["stderr"] = p.stderr.strip()[-500:]
    return res


def check(folder):
    """Resolve planned journal entries and check the journal chain (run on every open)."""
    return run_script(folder, ["check"])


def prepare_candidate(led, base_version, op_id, writer, summary=""):
    cand = json.loads(json.dumps(led))
    cand["version"] = base_version + 1
    cand["updated_at"] = fl.iso(fl.now_utc())
    cand.setdefault("commits", []).append({
        "commit_id": op_id, "base_version": base_version, "at": cand["updated_at"],
        "writer": writer, "summary": fl.clean_text(summary, 200),
    })
    fl.validate(cand)
    return cand


def publish(folder, led, base_hash, base_version, writer="claude-code", summary="", batch=None, op_id=None,
            env=None):
    """Publish `led` (already changed in memory) as base_version + 1 through bin/commit.
    Returns the script's result: result=committed with version and hash, or refused with code and reason."""
    op_id = op_id or new_op_id()
    cand = prepare_candidate(led, base_version, op_id, writer, summary)
    name, h = stage(folder, cand, base_version, op_id, batch)
    res = run_script(folder, ["commit", op_id, base_hash, str(base_version), name, h], env=env)
    res["op_id"] = op_id
    if res.get("result") == "committed":
        led.clear()
        led.update(cand)
    return res


def create(folder, led, writer="claude-code"):
    """Publish a brand-new ledger as version 1 (refused if one exists)."""
    fl.validate(led)
    return publish(folder, led, "none", 0, writer, "first ledger")


def _preview_lines(text):
    # The preview's first line names the base version and its last line the batch hash; both change when
    # another writer published first, while the planned changes themselves may not.
    return [ln for ln in text.splitlines() if not ln.startswith(("Planned changes (ledger version", "Batch "))]


PREVIEW_MAX_AGE = 3600


def preview(folder, batch):
    """Render the preview the person must see and remember it in work/ for apply_and_publish.
    Returns (hash, text)."""
    root = _root(folder)
    led, _, _ = read(folder)
    if led is None:
        raise StoreError("There is no ledger in this folder yet. Set it up first.")
    h, text = fl.preview_batch(led, batch)
    rec = {"hash": h, "base_version": led["version"], "text": text, "at": fl.iso(fl.now_utc())}
    p = root / "work" / f"preview-{h}.json"
    tmp = p.with_name(f".{p.name}.{secrets.token_hex(4)}")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return h, text


def _seen_preview(root, batch, confirm_hash, led):
    p = root / "work" / f"preview-{confirm_hash}.json" if re.match(r"^[0-9a-f]{16}$", confirm_hash or "") else None
    if p is None or not p.exists():
        raise StoreError("Show the preview of this batch to the person before applying it.")
    rec = json.loads(p.read_text(encoding="utf-8"))
    age = fl.now_utc().timestamp() - fl.parse_iso(rec["at"]).timestamp()
    if age > PREVIEW_MAX_AGE:
        raise StoreError("That preview is more than an hour old. Show it to the person again.")
    expected = fl.sha({"base": rec["base_version"], "ledger": led["ledger_id"], "batch": batch})
    if expected != confirm_hash or rec["hash"] != confirm_hash:
        raise StoreError("This batch is not the one the person saw (hash mismatch). Show the preview again.")
    return rec["text"]


def apply_and_publish(folder, batch, confirm_hash, writer="claude-code", session=None, summary="", retries=3,
                      env=None):
    """Apply a previewed batch and publish it. If another writer published first, reload, preview the same batch
    on the new version and publish again only when the planned changes read exactly as the person saw them;
    otherwise return needs_preview with the new preview for the person."""
    root = _root(folder)
    led, bh, bv = read(folder)
    if led is None:
        raise StoreError("There is no ledger in this folder yet. Set it up first.")
    seen = _preview_lines(_seen_preview(root, batch, confirm_hash, led))
    res = None
    for _ in range(retries):
        h, text = fl.preview_batch(led, batch)
        if _preview_lines(text) != seen:
            return {"result": "needs_preview", "preview": text, "hash": h,
                    "reason": "The ledger changed in another conversation and this batch now reads differently."}
        results = fl.apply_batch(led, batch, h, session)
        res = publish(folder, led, bh, bv, writer, summary, batch=batch, env=env)
        res["results"] = results
        if res.get("result") == "committed" or res.get("code") != "10":
            return res
        led, bh, bv = read(folder)
    return res


# ---------------------------------------------------------------- household redaction of older copies

REMOVED = "(removed at a household member's request)"


def _rewrite_json(path, fn):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    new = fn(data)
    if new is None:
        return False
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return True


def scrub_person(folder, person_id, led_now):
    """Remove a household member's data from every older copy in the folder: backups, candidates, working
    reads, batches and saved previews. Claude Code or Cowork run it (a chat cannot rewrite these files);
    `open --cleanup` runs it for every redaction not yet applied to the files. Returns the files changed."""
    root = _root(folder)
    gone_accounts = set()
    for path in sorted((root / "backups").glob("*.json")) + sorted((root / "work").glob("cand-*.json")):
        def scrub_ledger(led):
            if not isinstance(led, dict) or "people" not in led:
                return None
            gone_accounts.update(f"{s_['id']}/{a['id']}" for s_ in led.get("sources", []) for a in s_["accounts"]
                                 if a.get("person") == person_id)
            fl.apply_redaction(led, person_id)
            return led
        _rewrite_json(path, scrub_ledger)
    gone_accounts.update(f"{s_['id']}/{a['id']}" for s_ in led_now.get("sources", []) for a in s_["accounts"]
                         if a.get("person") == person_id)
    changed = []

    def mentions(op):
        if not isinstance(op, dict):
            return False
        if person_id in fl._persons_named(op) or (op.get("op") == "add_person" and op.get("id") == person_id):
            return True
        return f"{op.get('source')}/{op.get('account')}" in gone_accounts

    for path in sorted((root / "journal").glob("*.batch.json")) + sorted((root / "work").glob("*.batch.json")) + \
            sorted((root / "work").glob("batch-*.json")):
        if _rewrite_json(path, lambda b: [op for op in b if not mentions(op)] if isinstance(b, list) else None):
            changed.append(str(path.relative_to(root)))
    for path in sorted((root / "work").glob("read-*.json")):
        def scrub_reads(r):
            reads = r if isinstance(r, list) else [r]
            keep = [x for x in reads if isinstance(x, dict) and not mentions(x)
                    and not mentions(x.get("source_op") or {})]
            return keep if isinstance(r, list) else (keep[0] if keep else {"removed": REMOVED})
        if _rewrite_json(path, scrub_reads):
            changed.append(str(path.relative_to(root)))
    for path in sorted((root / "work").glob("preview-*.json")):
        if _rewrite_json(path, lambda p: {**p, "text": REMOVED} if isinstance(p, dict) else None):
            changed.append(str(path.relative_to(root)))
    return changed


def scrub_pending_redactions(folder, writer="claude-code"):
    """Apply every redaction not yet applied to the folder's older copies, then record that it was."""
    led, bh, bv = read(folder)
    if led is None:
        return []
    todo = [r for r in led["_meta"].get("redactions", []) if r.get("person") and not r.get("files_scrubbed")]
    if not todo:
        return []
    changed = []
    for r in todo:
        changed += scrub_person(folder, r["person"], led)
        r["files_scrubbed"] = True
    res = publish(folder, led, bh, bv, writer, "older copies scrubbed after a household member's removal")
    if res.get("result") != "committed":
        raise StoreError(f"The older copies were scrubbed but the ledger could not record it: {res.get('reason')}")
    return changed


# ---------------------------------------------------------------- export

def export_archive(folder, out_path):
    """One portable archive: the ledger, the list of its backups and the journal entries (spec v2, appendix D).
    Working files and locks are left out. Returns the archive path."""
    import zipfile
    root = _root(folder)
    led, bh, bv = read(folder)
    if led is None:
        raise StoreError("There is no ledger in this folder yet.")
    out = Path(out_path).expanduser().resolve()
    if out == root or root in out.parents and out.parent.name not in ("reports",):
        raise StoreError("Write the archive outside the ledger folder, or into its reports/ folder.")
    backups = [{"file": b.name, "sha256": file_sha(b), "bytes": b.stat().st_size}
               for b in sorted((root / "backups").glob("ledger.v*.json"))]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("finerd-points/ledger.json", (root / "ledger.json").read_bytes())
        z.writestr("finerd-points/backups.json", json.dumps(backups, indent=1) + "\n")
        for j in sorted((root / "journal").glob("*.json")):
            if not j.name.endswith(".batch.json"):
                z.writestr(f"finerd-points/journal/{j.name}", j.read_bytes())
        z.writestr("finerd-points/README.txt",
                   f"finerd points ledger {led['ledger_id']}, version {bv}, sha256 {bh}.\n"
                   f"Restore: create an empty folder, run `ledger.py setup --folder <it> --import-file ledger.json`.\n")
    return str(out)


# ---------------------------------------------------------------- housekeeping (Claude Code / Cowork only)

def cleanup(folder, now=None, keep_days=30):
    """Remove committed or discarded work files older than keep_days, released locks, and backups beyond the last
    20 plus one per month. A chat cannot delete files, so this runs when Claude Code or Cowork opens the ledger.
    Returns the list of removed paths (relative)."""
    root = _root(folder)
    now = (now or fl.now_utc()).timestamp()
    removed = []
    live = set()
    for j in (root / "journal").glob("*.json"):
        if j.name.endswith(".batch.json"):
            continue
        try:
            entry = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if entry.get("state") == "planned":
            live.add(Path(entry.get("candidate", "")).name)
    for p in (root / "work").iterdir():
        base = p.name.split(".json")[0] + ".json" if ".json" in p.name else p.name
        if base in live or not p.is_file():
            continue
        if now - p.stat().st_mtime > keep_days * 86400:
            p.unlink()
            removed.append(f"work/{p.name}")
    for p in (root / "locks").iterdir():
        if p.is_dir():
            for f in p.iterdir():
                f.unlink()
            p.rmdir()
            removed.append(f"locks/{p.name}")
    backups = sorted((root / "backups").glob("ledger.v*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    months = set()
    for i, b in enumerate(backups):
        month = fl.iso(fl._dt.datetime.fromtimestamp(b.stat().st_mtime, fl._dt.timezone.utc))[:7]
        if i < BACKUPS_KEEP or month not in months:
            months.add(month)
            continue
        b.unlink()
        removed.append(f"backups/{b.name}")
    return removed
