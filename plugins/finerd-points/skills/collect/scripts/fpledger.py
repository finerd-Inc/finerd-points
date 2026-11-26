"""finerd points ledger library (Python 3.9+, standard library only).

The ledger is one JSON document. It can live in a file the person keeps and
re-attaches, or in a folder on their computer. The same schema is used everywhere.

Design rules (spec, appendix C and E):
- Observations are append-only. A wrong one is voided by a correction, never
  edited or deleted. Records (cards, redemptions, costs…) change only through
  `amend`, which keeps the old value in the record's `amendments` history. The
  only deletion is a household member's privacy withdrawal (`redact_person`).
- Every change goes through a batch: `preview_batch` renders exactly what goes
  where (including the actual values of writes to other apps) and returns the
  batch hash; `apply_batch` refuses any other batch. The hash proves the preview
  was produced for exactly this batch on this ledger version; showing it to the
  person and getting their yes is the skill's duty (the CLI also requires that
  `preview` ran first).
- Writes to other apps (calendar, finance app) are planned here as operations
  with a deterministic op_id and a state planned|sent|confirmed|unknown|failed.
  «confirmed» needs a read-back of every key the plan set, and the read-back
  values (not the plan) are what the ledger records. A retry of a failed write is
  a new operation; the failed one keeps its history.
- One conversation writes at a time: a 30-minute writer lease in `_meta.writer`,
  renewed on every write. Copies of a ledger file in different conversations
  cannot see each other's leases; the version number is the guard there.
- The file version only grows; saving over a newer or different file is refused.
"""

import csv
import datetime as _dt
import hashlib
import json
import math
import os
import re
import secrets
import tempfile
from pathlib import Path

FORMAT = "finerd-points-ledger"
SCHEMA_VERSION = 2
LEASE_MINUTES = 30

COLLECTIONS = (
    "people", "cards", "accounts", "observations", "corrections", "redemptions",
    "costs", "certificates", "signup_offers", "calendar_events", "oplog",
    # schema 2 (spec v2, appendix D)
    "inventory", "sources", "records", "events", "commits",
)
V2_COLLECTIONS = ("inventory", "sources", "records", "events", "commits")
RECORD_KEY = {"oplog": "op_id", "commits": "commit_id"}

# Source order per field: earlier = stronger evidence (spec «Why the numbers can be trusted»).
SOURCE_ORDER = {
    "credited": ["finance_app", "statement", "issuer_page", "person", "email"],
    "used_amount": ["finance_app", "statement", "person"],
    "enrolled": ["issuer_page", "person"],
    "balance": ["program_page", "program_api", "awardwallet", "email", "finance_app", "statement", "person"],
    "expires_on": ["program_page", "program_api", "email", "awardwallet", "statement", "person"],
    "status_tier": ["program_page", "program_api", "awardwallet", "email", "person"],
}
DEFAULT_SOURCE_ORDER = ["program_page", "program_api", "issuer_page", "finance_app", "statement",
                        "awardwallet", "email", "person"]
CONFIDENCE = ("confirmed", "likely", "unsure")
SOURCE_KINDS = ("program_page", "program_api", "issuer_page", "finance_app", "statement",
                "awardwallet", "email", "person", "calculation", "import")
OP_STATES = ("planned", "sent", "confirmed", "unknown", "failed")
EXTERNAL_TARGETS = ("calendar", "finance_app")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,120}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LedgerError(Exception):
    """A refusal the skill must show to the person as is."""


# ---------------------------------------------------------------- intake safety

# Keys whose values are identifiers (bank or app ids), never scanned as card numbers.
ID_KEYS = {"id", "ref", "op_id", "event_id", "destination_id", "account_id", "transaction_id", "target",
           "subject", "ledger_id", "match_key", "calendar_id", "observation"}
# In schema-2 operations these keys hold generated or site ids, never free text (v1 «source» is free text).
ID_KEYS_V2 = ID_KEYS | {"site_id", "read_id", "commit_id", "record", "link", "a", "b", "source", "account",
                        "inventory"}
SECRET_KEYS = re.compile(r"(?i)^(password|passcode|pin|otp|one[_ -]?time[_ -]?code|cvv|cvc|security[_ -]?code|"
                         r"api[_ -]?key|secret|token|access[_ -]?token|refresh[_ -]?token|ssn|"
                         r"social[_ -]?security|passport|member[_ -]?number|account[_ -]?number|card[_ -]?number)$")
SECRET_TEXT = [
    (re.compile(r"(?i)\b(password|passcode)\b\s*(is|:|=)\s*\S+|\bpin\b\s*(is|:|=)\s*\d{4,}"), "a password"),
    (re.compile(r"(?i)\b(otp|one[- ]time (pass)?code|verification code|security code|cvv|cvc)\b\D{0,12}\d{3,8}"),
     "a one-time or security code"),
    (re.compile(r"(?i)\b(api[_ -]?key|secret|token)\b\s*(is|:|=)\s*(?=\S*\d)\S{8,}"), "a key or token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bxox[abp]-[A-Za-z0-9-]{10,}"),
     "an API key"),
    (re.compile(r"(?i)\b(ssn|social security)\b\D{0,6}\d{3}[- ]?\d{2}[- ]?\d{4}\b"), "a social security number"),
    (re.compile(r"(?i)\bpassport\b\D{0,12}\b(?=[A-Z0-9]*\d[A-Z0-9]*\d)[A-Z0-9]{6,9}\b"), "a passport number"),
    (re.compile(r"(?i)\b(member(ship)?|honors|rewards|loyalty|account|card)\s*(number|no\.?|#)\D{0,6}\d{6,}"),
     "a member or account number"),
]
CARD_CANDIDATE = re.compile(r"(?<![\d.-])(?:\d[ .-]?){12,18}\d(?![\d.-])")
DATE_INSIDE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _luhn_ok(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _has_card_number(text):
    """13–19 digits (spaces, dots or dashes allowed) that pass the Luhn check and are not a date-based id."""
    for m in CARD_CANDIDATE.finditer(text):
        raw = m.group(0)
        if DATE_INSIDE.search(raw):
            continue
        digits = re.sub(r"\D", "", raw)
        if 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn_ok(digits):
            return True
    return False


def scan_forbidden(obj, _key=None, id_keys=None):
    """Return the kinds of data in obj that must never be stored (spec appendix F)."""
    id_keys = ID_KEYS if id_keys is None else id_keys
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SECRET_KEYS.match(str(k)) and v not in (None, "", False):
                found.add("a password, code, key or ID number")
            found |= set(scan_forbidden(v, str(k), id_keys))
            found |= set(scan_forbidden(str(k), None, id_keys))
        return sorted(found)
    if isinstance(obj, list):
        for v in obj:
            found |= set(scan_forbidden(v, _key, id_keys))
        return sorted(found)
    if not isinstance(obj, str):
        return []
    for rx, why in SECRET_TEXT:
        if rx.search(obj):
            found.add(why)
    if (_key not in id_keys) and _has_card_number(obj):
        found.add("a full card number")
    return sorted(found)


def _refuse_forbidden(obj, where, id_keys=None):
    bad = scan_forbidden(obj, None, id_keys)
    if bad:
        raise LedgerError(f"{where} contains {', '.join(bad)}. Remove it; finerd points never stores card "
                          f"numbers, passwords, codes, keys, member numbers or ID numbers.")


# ---------------------------------------------------------------- time & ids

def now_utc():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def iso(ts):
    return ts.isoformat().replace("+00:00", "Z")


def parse_iso(s):
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4)}"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(obj, n=16):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:n]


def is_date(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        _dt.date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _num(v, allow_none=False, minimum=0):
    if v is None:
        return allow_none
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= minimum


# ---------------------------------------------------------------- create / load / save

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def new_ledger(person_name, currency="USD", timezone="UTC", storage="file",
               household_mode="single", person_id="me"):
    _refuse_forbidden({"name": person_name}, "The name")
    if not CURRENCY_RE.match(str(currency)):
        raise LedgerError("The report currency is a three-letter code such as USD or EUR.")
    ts = iso(now_utc())
    led = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "ledger_id": "led-" + secrets.token_hex(6),
        "version": 0,
        "created_at": ts,
        "updated_at": ts,
        "_meta": {
            "writer": None,
            "setup": {
                "storage": storage,          # file | folder (a Google Sheet is an export until probes pass)
                "location": None,            # path or file name (never a secret)
                "calendar_id": None,
                "finance_app": None,         # e.g. "finerd" or "CSV"
                "timezone": timezone,
                "household_mode": household_mode,  # single | shared | separate
                "report_currency": currency,
                "first_run_notice_shown": False,
            },
            "settings": {
                "foregone_cashback_rate": None,      # e.g. 0.02; the person's own choice
                "foregone_cashback_exclusions": [],  # e.g. ["rent", "amazon"]
                "calendar_min_value": 25,            # propose events only for deadlines worth at least this
                "reminder_days_before": 3,
                "stale_after_days": 30,
                "credit_values": {},                 # {"<card>/<benefit>": 0.5}: what a credit is really worth to you
            },
            "redactions": [],
        },
    }
    for c in COLLECTIONS:
        led[c] = []
    led["people"].append({"id": person_id, "name": person_name, "role": "owner",
                          "consent": {"given": True, "on": ts[:10], "by": "self"}})
    return led


def validate(led):
    """Raise LedgerError on anything that would make the ledger unsafe to use."""
    if not isinstance(led, dict) or led.get("format") != FORMAT:
        raise LedgerError("This file is not a finerd points ledger.")
    if not isinstance(led.get("schema_version"), int) or led["schema_version"] > SCHEMA_VERSION:
        raise LedgerError(
            f"This ledger was written by a newer finerd points (schema {led.get('schema_version')}); "
            f"update the skills before using it.")
    if not isinstance(led.get("version"), int) or led["version"] < 0:
        raise LedgerError("The ledger has no valid version number.")
    meta = led.get("_meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("setup"), dict) or not isinstance(meta.get("settings"), dict):
        raise LedgerError("The ledger's setup record is missing or damaged.")
    for k in ("report_currency", "timezone", "storage"):
        if not meta["setup"].get(k):
            raise LedgerError(f"The ledger's setup record has no {k}.")
    if not CURRENCY_RE.match(str(meta["setup"]["report_currency"])):
        raise LedgerError("The ledger's report currency is not a three-letter code.")
    meta.setdefault("redactions", [])
    meta["settings"].setdefault("credit_values", {})
    for c in COLLECTIONS:
        if not isinstance(led.get(c), list):
            raise LedgerError(f"The ledger is missing its {c} list.")
    ids = set()
    for c in COLLECTIONS:
        key = RECORD_KEY.get(c, "id")
        for rec in led[c]:
            rid = rec.get(key) if isinstance(rec, dict) else None
            if not rid:
                raise LedgerError(f"A record in {c} has no {key}.")
            if (c, rid) in ids:
                raise LedgerError(f"Duplicate {key} {rid} in {c}.")
            ids.add((c, rid))
    if not any(p.get("role") == "owner" for p in led["people"]):
        raise LedgerError("The ledger has no owner.")
    return True


def migrate(led):
    """Forward-only schema migrations, in memory. Returns (ledger, migrated?). The version the migration
    replaces is kept by bin/commit's backup when the migrated ledger is first published (spec v2, appendix D)."""
    v = led.get("schema_version")
    if v == SCHEMA_VERSION:
        return led, False
    if v == 1:
        for c in V2_COLLECTIONS:
            led.setdefault(c, [])
        led["schema_version"] = 2
        led.setdefault("_meta", {}).setdefault("migrations", []).append({"from": 1, "to": 2, "at": iso(now_utc())})
        return led, True
    raise LedgerError(f"No migration path from schema {v} to {SCHEMA_VERSION}.")


def loads(text):
    """Parse, migrate and validate a ledger. Free text never makes loading fail (spec v2, appendix C): run
    `forbidden_report` to show the person anything that should not be there."""
    try:
        led = json.loads(text)
    except json.JSONDecodeError as e:
        raise LedgerError(f"The ledger file is damaged (invalid JSON at line {e.lineno}).")
    if not isinstance(led, dict):
        raise LedgerError("This file is not a finerd points ledger.")
    if isinstance(led.get("schema_version"), int) and led["schema_version"] > SCHEMA_VERSION:
        validate(led)  # raises the «newer finerd points» message
    led, _ = migrate(led)
    validate(led)
    keys = _secret_keys({**{k: led[k] for k in COLLECTIONS}, "_meta": led["_meta"]})
    if keys:
        raise LedgerError(f"This ledger file has field(s) named {', '.join(sorted(keys))} with values in them. "
                          f"finerd points never keeps passwords, codes, keys or ID numbers; remove those fields "
                          f"from the file before using it.")
    return led


def _secret_keys(obj):
    """Structured fields that may only exist empty (password, card_number…). Free text is not checked here."""
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SECRET_KEYS.match(str(k)) and v not in (None, "", False):
                found.add(str(k))
            found |= _secret_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _secret_keys(v)
    return found


def load(path):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LedgerError(f"No ledger at {p}. Ask the person for their ledger file or setup record; "
                          f"never create a second ledger without asking.")
    return loads(text)


def forbidden_report(led):
    """Where the ledger holds something finerd points never keeps: [(collection, record id, kinds)]."""
    out = []
    for c in COLLECTIONS:
        key = RECORD_KEY.get(c, "id")
        for rec in led.get(c, []):
            bad = scan_forbidden(rec)
            if bad:
                out.append((c, rec.get(key), bad))
    bad = scan_forbidden(led.get("_meta", {}))
    if bad:
        out.append(("_meta", None, bad))
    return out


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
MARKUP = re.compile(r"<[^>]{0,200}>|\[([^\]]{0,200})\]\([^)]{0,500}\)|```|`")


URL_TAIL = re.compile(r"(?i)\b((?:https?://|www\.)[^\s?#<>\"']+)[?#][^\s<>\"']*")
KV_SECRET = re.compile(r"(?i)\b[\w.-]*(token|secret|passw(or)?d|session|sid|sig(nature)?|auth|code|key|otp|"
                       r"ticket|nonce|jwt|bearer)[\w.-]*\s*[=:]\s*[^\s&;,]{6,}")
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")


def redact_text(text):
    """Remove what must never be stored from free text. Returns (clean text, kinds removed)."""
    kinds = set()
    if URL_TAIL.search(text):
        kinds.add("a link's query or fragment")
        text = URL_TAIL.sub(lambda m: m.group(1), text)
    for rx in (BEARER, KV_SECRET):
        if rx.search(text):
            kinds.add("a token or code")
            text = rx.sub("[removed]", text)
    for rx, why in SECRET_TEXT:
        if rx.search(text):
            kinds.add(why)
            text = rx.sub("[removed]", text)

    def card(m):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not DATE_INSIDE.search(raw) and 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn_ok(digits):
            kinds.add("a full card number")
            return "[removed]"
        return raw
    text = CARD_CANDIDATE.sub(card, text)
    return text, sorted(kinds)


def clean_text(text, limit=300):
    """Free text from pages, emails, files or the person, as stored: control characters and markup removed,
    identifiers redacted, whitespace collapsed, length capped (spec v2, appendix B «Untrusted content»)."""
    if text is None:
        return ""
    text = str(text)
    text = CONTROL.sub(" ", text)
    text = MARKUP.sub(lambda m: m.group(1) or " ", text)
    text, _ = redact_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class _Lock:
    def __init__(self, path):
        self.lock = Path(str(path) + ".lock")
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = now_utc().timestamp() - self.lock.stat().st_mtime
            if age < 120:
                raise LedgerError("Another process is writing this ledger right now. Try again in a minute.")
            self.lock.unlink()  # stale lock from a crashed writer
            self.fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.lock.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(p, led):
    fd, tmp = tempfile.mkstemp(prefix=".fp-", suffix=".json", dir=str(p.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def _refuse_folder_ledger(p, led):
    """A ledger in a folder is replaced only by bin/commit (spec v2, appendix E); these v1 file writes refuse it."""
    if led.get("_meta", {}).get("setup", {}).get("storage") == "folder" or (p.parent / "bin" / "commit").exists():
        raise LedgerError("This ledger lives in a ledger folder and is written only through bin/commit "
                          "(ledger.py apply --folder …).")


def create(path, led):
    """Write a brand-new ledger as version 1; refuses if anything already exists at path."""
    p = Path(path)
    _refuse_folder_ledger(p, led)
    validate(led)
    led["version"] = 1
    with _Lock(p):
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # claims the name atomically
        except FileExistsError:
            raise LedgerError(f"A file already exists at {p}. Load it instead of creating a second ledger.")
        os.close(fd)
        _atomic_write(p, led)
    return 1


def save(path, led, base_version):
    """Atomically write `led` as version base_version + 1.

    Refuses when the file on disk is not at base_version (someone else wrote,
    or an older copy is being saved over a newer one).
    """
    p = Path(path)
    _refuse_folder_ledger(p, led)
    validate(led)
    with _Lock(p):
        if p.exists():
            try:
                on_disk = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raise LedgerError("The ledger file on disk is damaged; refusing to overwrite it.")
            if not isinstance(on_disk, dict) or on_disk.get("ledger_id") != led["ledger_id"]:
                raise LedgerError("A different ledger already lives at this path; refusing to overwrite it.")
            disk_version = on_disk.get("version", -1)
            if disk_version != base_version:
                raise LedgerError(
                    f"The ledger on disk is version {disk_version}, but this change was prepared from "
                    f"version {base_version}. Reload the ledger and prepare the change again.")
        led["version"] = base_version + 1
        led["updated_at"] = iso(now_utc())
        _atomic_write(p, led)
    return led["version"]


# ---------------------------------------------------------------- writer lease

def lease_status(led, now=None):
    now = now or now_utc()
    w = led["_meta"].get("writer")
    if not w:
        return {"held": False}
    expired = parse_iso(w["expires_at"]) <= now
    return {"held": not expired, "expired": expired, **w}


def acquire_lease(led, session, now=None, transfer=False):
    """Grant or renew the writer lease. `transfer=True` only after the person explicitly
    hands write access to this conversation; another conversation's lease, live or expired but not
    released, needs that hand-over too."""
    if not session or not re.match(r"^[A-Za-z0-9._:-]{4,80}$", session):
        raise LedgerError("A session id of 4–80 letters, digits or . _ : - is required.")
    now = now or now_utc()
    st = lease_status(led, now)
    w = led["_meta"].get("writer")
    if w and w.get("session") != session and not transfer:
        raise LedgerError(
            f"Another conversation ({w['session']}) {'holds' if st['held'] else 'held and did not release'} write "
            f"access ({w['expires_at']}). This conversation can read. Ask the person whether to hand write access "
            f"over here (--transfer).")
    granted = st["granted_at"] if (st["held"] and st.get("session") == session) else iso(now)
    led["_meta"]["writer"] = {
        "session": session,
        "granted_at": granted,
        "expires_at": iso(now + _dt.timedelta(minutes=LEASE_MINUTES)),
    }
    return led["_meta"]["writer"]


def require_lease(led, session, now=None):
    st = lease_status(led, now)
    if not st["held"] or st["session"] != session:
        raise LedgerError("This conversation does not hold write access to the ledger. "
                          "Acquire it first (or ask the person to hand it over).")


def ensure_lease(led, session, now=None):
    """Renew our own lease or take a free one. Another conversation's lease — live or expired — is
    taken only when the person hands write access over (`lease acquire --transfer`)."""
    w = led["_meta"].get("writer")
    if w and w.get("session") != session:
        st = lease_status(led, now)
        raise LedgerError(
            f"Another conversation ({w['session']}) {'holds' if st['held'] else 'held'} write access "
            f"{'until' if st['held'] else 'and did not release it; it expired'} {w['expires_at']}. Ask the person whether "
            f"to hand write access over to this conversation, then run `ledger.py lease acquire --transfer`.")
    return acquire_lease(led, session, now)


def release_lease(led, session):
    st = lease_status(led)
    if st.get("session") == session:
        led["_meta"]["writer"] = None


# ---------------------------------------------------------------- reading values

def active_observations(led):
    voided = {c["target"] for c in led["corrections"] if c.get("action") == "void"}
    return [o for o in led["observations"] if o["id"] not in voided]


def _rank(field, kind):
    order = SOURCE_ORDER.get(field, DEFAULT_SOURCE_ORDER)
    return order.index(kind) if kind in order else len(order)


def current(led, subject, field, obs=None):
    """Best current value for subject/field.

    Latest `as_of` wins; on the same date the stronger source wins. Returns
    {"value", "as_of", "source", "confidence", "observation", "conflicts": [...]}
    or None when nothing is known (unknown is not zero).
    """
    cands = [o for o in (obs if obs is not None else active_observations(led))
             if o["subject"] == subject and o["field"] == field]
    if not cands:
        return None
    cands.sort(key=lambda o: (o.get("as_of") or "", -_rank(field, o["source"]["kind"])), reverse=True)
    best = cands[0]
    conflicts = [
        {"value": o["value"], "as_of": o.get("as_of"), "source": o["source"], "observation": o["id"]}
        for o in cands[1:]
        if o.get("as_of") == best.get("as_of") and o["value"] != best["value"]
    ]
    return {"value": best["value"], "as_of": best.get("as_of"), "source": best["source"],
            "confidence": best.get("confidence"), "observation": best["id"], "conflicts": conflicts}


def history(led, subject, field):
    return sorted((o for o in active_observations(led) if o["subject"] == subject and o["field"] == field),
                  key=lambda o: o.get("as_of") or "")


# ---------------------------------------------------------------- batches

RECORD_OPS = {
    "add_person": "people", "add_card": "cards", "add_account": "accounts",
    "add_redemption": "redemptions", "add_cost": "costs", "add_certificate": "certificates",
    "add_signup_offer": "signup_offers",
}
REQUIRED = {
    "add_person": ("id", "name", "consent"),
    "add_card": ("id", "person", "nickname"),
    "add_account": ("id", "person", "program", "nickname", "unit"),
    "add_redemption": ("id", "person", "program", "booked_on", "points", "fees", "status"),
    "add_cost": ("id", "date", "kind", "amount", "currency"),
    "add_certificate": ("id", "account", "type"),
    "add_signup_offer": ("id", "card", "bonus", "spend", "deadline"),
    "observe": ("subject", "field", "value", "source", "as_of", "confidence"),
    "void": ("target", "reason"),
    "set_setting": ("key", "value"),
    "set_setup": ("key", "value"),
    "amend": ("target", "id", "field", "reason"),
    "external": ("target", "action", "payload", "summary"),
}
# Every key a record may carry. Unknown keys are refused, so a misspelt field never
# silently counts as missing (for example «fallback_price» instead of «fallback»).
ALLOWED = {
    "add_person": {"id", "name", "consent", "role", "note"},
    "add_card": {"id", "person", "nickname", "catalog_ref", "variant", "last4", "opened_on", "anniversary",
                 "finance_link", "note"},
    "add_account": {"id", "person", "program", "nickname", "unit", "finance_link", "note"},
    "add_redemption": {"id", "person", "program", "booked_on", "points", "fees", "fallback", "normalized",
                       "status", "description", "note", "source", "purchased_points_cost", "cancellation_fee",
                       "cancelled_on", "currency", "fx_rate", "fx_source"},
    "add_cost": {"id", "date", "kind", "amount", "currency", "card", "program", "person", "description",
                 "source", "redemption", "fx_rate", "fx_source", "note"},
    "add_certificate": {"id", "account", "type", "issued_on", "expires_on", "value_cap", "source", "note"},
    "add_signup_offer": {"id", "card", "bonus", "spend", "deadline", "start_date", "source", "note"},
    "observe": {"subject", "field", "value", "source", "as_of", "confidence", "method", "note", "unit", "person",
                "caveat"},
    "void": {"target", "reason", "by"},
    "set_setting": {"key", "value"},
    "set_setup": {"key", "value"},
    "amend": {"target", "id", "field", "value", "reason"},
    "external": {"target", "action", "payload", "summary", "app", "subject", "match_key"},
}
AMENDABLE = {
    "cards": ("nickname", "anniversary", "opened_on", "finance_link", "last4", "person", "catalog_ref", "variant"),
    "accounts": ("nickname", "finance_link", "person", "program"),
    "redemptions": ("status", "fees", "fallback", "normalized", "points", "booked_on", "cancellation_fee",
                    "cancelled_on", "purchased_points_cost", "description", "currency", "fx_rate", "fx_source"),
    "costs": ("amount", "date", "kind", "currency", "fx_rate", "fx_source", "description", "card"),
    "certificates": ("expires_on", "type", "value_cap", "issued_on"),
    "signup_offers": ("deadline", "spend", "bonus", "start_date"),
}
DATE_FIELDS = ("booked_on", "date", "issued_on", "expires_on", "opened_on", "deadline", "cancelled_on",
               "start_date")
MONEY_FIELDS = ("fees", "fallback", "normalized", "amount", "purchased_points_cost", "cancellation_fee", "spend")
COST_KINDS = ("annual_fee", "points_purchase", "tool", "cancellation_fee", "other")
REDEMPTION_STATUS = ("booked", "cancelled", "cancelled_with_fee")
SETTINGS_KEYS = ("foregone_cashback_rate", "foregone_cashback_exclusions", "calendar_min_value",
                 "reminder_days_before", "stale_after_days", "credit_values")
SETUP_KEYS = ("storage", "location", "calendar_id", "timezone", "household_mode", "report_currency",
              "finance_app", "first_run_notice_shown", "history_from")
# Keys a destination must echo back before a write counts as confirmed.
READBACK_KEYS = {
    "calendar": ("title", "date", "reminder_minutes", "visibility"),
    "finance_app": None,  # every key of the payload, nested values included
}
TITLE_LEAK = re.compile(r"(?i)\d[\d,. ]{2,}\s*(points|pts|miles|avios)\b|\d{6,}")


def external_op_id(op):
    """Deterministic id: the same planned write always gets the same op_id, so a repeated
    plan is recognized instead of written twice."""
    key = {"target": op["target"], "action": op["action"], "app": op.get("app"),
           "match_key": op.get("match_key") or op["payload"]}
    return "op-" + sha(key, 12)


def _latest_op(led, base_id):
    ops = [x for x in led["oplog"] if x["op_id"] == base_id or x.get("retry_of") == base_id]
    return ops[-1] if ops else None


def _check_value(op, i, k):
    v = op.get(k)
    if k in DATE_FIELDS and v is not None and not is_date(v):
        raise LedgerError(f"Step {i + 1}: {k} must be a real date, YYYY-MM-DD.")
    if k in MONEY_FIELDS and v is not None and not _num(v):
        raise LedgerError(f"Step {i + 1}: {k} must be a number of 0 or more.")
    if k == "points" and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
        raise LedgerError(f"Step {i + 1}: points must be a whole number of 0 or more.")
    if k == "fx_rate" and v is not None and not (_num(v) and v > 0):
        raise LedgerError(f"Step {i + 1}: fx_rate must be a positive number (report currency per unit).")
    if k == "anniversary" and v is not None and not (isinstance(v, str) and re.match(r"^\d{2}-\d{2}$", v)
                                                      and is_date("2024-" + v)):
        raise LedgerError(f"Step {i + 1}: anniversary is MM-DD (for example 03-13).")
    if k == "last4" and v not in (None, "") and not re.match(r"^\d{4}$", str(v)):
        raise LedgerError(f"Step {i + 1}: last4 must be exactly four digits.")


EXTRA_OPS = {}  # name → {"check", "apply", "describe"}; schema-2 operations register here (fpcollect.py)


def register_op(name, required, allowed, check, apply, describe):
    REQUIRED[name] = tuple(required)
    ALLOWED[name] = set(allowed)
    EXTRA_OPS[name] = {"check": check, "apply": apply, "describe": describe}


def _persons_named(obj):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "person" and isinstance(v, str):
                out.add(v)
            out |= _persons_named(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _persons_named(v)
    return out


def _check_op(led, op, i, staged_ids):
    kind = op.get("op") if isinstance(op, dict) else None
    if led["_meta"].get("redactions") and isinstance(op, dict) and names_removed(op, _removed_refs(led)):
        raise LedgerError(f"Step {i + 1}: this change names a household member, or a card, account or row, whose data "
                          f"was removed at their request; it cannot bring that data back.")
    if kind in EXTRA_OPS:
        missing = [k for k in REQUIRED[kind] if op.get(k) in (None, "")]
        if missing:
            raise LedgerError(f"Step {i + 1} ({kind}): missing {', '.join(missing)}.")
        unknown = sorted(set(op) - ALLOWED[kind] - {"op"})
        if unknown:
            raise LedgerError(f"Step {i + 1} ({kind}): unknown field(s) {', '.join(unknown)}.")
        if _secret_keys(op):
            raise LedgerError(f"Step {i + 1} ({kind}): passwords, codes, keys and ID numbers are never stored.")
        _refuse_forbidden(op, f"Step {i + 1} ({kind})", ID_KEYS_V2)
        EXTRA_OPS[kind]["check"](led, op, i, staged_ids)
        return
    if kind not in REQUIRED:
        raise LedgerError(f"Step {i + 1}: unknown operation {kind!r}.")
    missing = [k for k in REQUIRED[kind] if op.get(k) in (None, "")]
    if missing:
        raise LedgerError(f"Step {i + 1} ({kind}): missing {', '.join(missing)}.")
    unknown = sorted(set(op) - ALLOWED[kind] - {"op"})
    if unknown:
        raise LedgerError(f"Step {i + 1} ({kind}): unknown field(s) {', '.join(unknown)}. "
                          f"Allowed: {', '.join(sorted(ALLOWED[kind]))}.")
    _refuse_forbidden(op, f"Step {i + 1} ({kind})")
    if kind in RECORD_OPS:
        coll = RECORD_OPS[kind]
        if not ID_RE.match(op["id"]):
            raise LedgerError(f"Step {i + 1} ({kind}): id {op['id']!r} must be lowercase letters, digits, . _ : / -.")
        if any(r["id"] == op["id"] for r in led[coll]) or (coll, op["id"]) in staged_ids:
            raise LedgerError(f"Step {i + 1} ({kind}): {op['id']} already exists. Records are never overwritten; "
                              f"use amend (with a reason) or observe/void to change what is known.")
        staged_ids.add((coll, op["id"]))
        for k in op:
            _check_value(op, i, k)
        if kind == "add_cost" and op["kind"] not in COST_KINDS:
            raise LedgerError(f"Step {i + 1}: cost kind must be one of {', '.join(COST_KINDS)}.")
        if kind == "add_redemption" and op["status"] not in REDEMPTION_STATUS:
            raise LedgerError(f"Step {i + 1}: redemption status must be one of {', '.join(REDEMPTION_STATUS)}.")
        if kind == "add_person":
            if not isinstance(op["consent"], dict) or not op["consent"].get("given"):
                raise LedgerError(f"Step {i + 1}: a person is added only with their consent.")
            if op.get("role", "member") == "owner":
                raise LedgerError(f"Step {i + 1}: the ledger already has its owner.")
        if kind in ("add_card", "add_account", "add_redemption") and op.get("person"):
            if not any(p["id"] == op["person"] for p in led["people"]) and ("people", op["person"]) not in staged_ids:
                raise LedgerError(f"Step {i + 1}: person {op['person']} is not in the ledger (add them with consent first).")
        cur = op.get("currency")
        if cur and cur != led["_meta"]["setup"]["report_currency"] and kind in ("add_cost", "add_redemption") \
                and not op.get("fx_rate"):
            raise LedgerError(f"Step {i + 1}: amounts in {cur} need fx_rate to {led['_meta']['setup']['report_currency']} "
                              f"(from the finance app, or the ECB rate of that date) and fx_source.")
    elif kind == "observe":
        if not isinstance(op["source"], dict) or op["source"].get("kind") not in SOURCE_KINDS:
            raise LedgerError(f"Step {i + 1}: source.kind must be one of {', '.join(SOURCE_KINDS)}.")
        if op["confidence"] not in CONFIDENCE:
            raise LedgerError(f"Step {i + 1}: confidence must be one of {', '.join(CONFIDENCE)}.")
        if not is_date(op["as_of"]):
            raise LedgerError(f"Step {i + 1}: as_of must be a real date, YYYY-MM-DD.")
        if op["field"] in ("expires_on", "deadline") and not is_date(op["value"]):
            raise LedgerError(f"Step {i + 1}: {op['field']} values are dates, YYYY-MM-DD.")
        if op["field"] in ("balance", "credited", "used_amount") and not _num(op["value"]):
            raise LedgerError(f"Step {i + 1}: {op['field']} must be a number of 0 or more.")
        if op.get("caveat") not in (None, "may_lag"):
            raise LedgerError(f"Step {i + 1}: caveat is may_lag (the issuer's tracker says it may lag) or absent.")
    elif kind == "void":
        if not any(o["id"] == op["target"] for o in led["observations"]):
            raise LedgerError(f"Step {i + 1}: observation {op['target']} not found.")
    elif kind == "amend":
        coll = op["target"]
        if coll not in AMENDABLE:
            raise LedgerError(f"Step {i + 1}: only {', '.join(AMENDABLE)} can be amended.")
        if op["field"] not in AMENDABLE[coll]:
            raise LedgerError(f"Step {i + 1}: {coll} field must be one of {', '.join(AMENDABLE[coll])}.")
        if not any(r["id"] == op["id"] for r in led[coll]) and (coll, op["id"]) not in staged_ids:
            raise LedgerError(f"Step {i + 1}: {op['id']} not found in {coll}.")
        required_by = {"redemptions": REQUIRED["add_redemption"], "costs": REQUIRED["add_cost"],
                       "certificates": REQUIRED["add_certificate"], "signup_offers": REQUIRED["add_signup_offer"],
                       "cards": REQUIRED["add_card"], "accounts": REQUIRED["add_account"]}[coll]
        if op["field"] in required_by and op.get("value") in (None, ""):
            raise LedgerError(f"Step {i + 1}: {op['field']} is required on {coll}; amend it to a real value.")
        if "value" not in op:
            raise LedgerError(f"Step {i + 1}: amend needs a value (null only for optional fields).")
        probe = {op["field"]: op.get("value")}
        _check_value(probe, i, op["field"])
        if op["field"] == "status" and op.get("value") not in REDEMPTION_STATUS:
            raise LedgerError(f"Step {i + 1}: redemption status must be one of {', '.join(REDEMPTION_STATUS)}.")
        if op["field"] == "kind" and op.get("value") not in COST_KINDS:
            raise LedgerError(f"Step {i + 1}: cost kind must be one of {', '.join(COST_KINDS)}.")
        if op["field"] == "person":
            ok = any(pp["id"] == op.get("value") and pp.get("consent", {}).get("given") for pp in led["people"]) or \
                ("people", op.get("value")) in staged_ids
            if not ok:
                raise LedgerError(f"Step {i + 1}: a card or account moves only to a person already in the ledger "
                                  f"with their consent.")
    elif kind == "set_setting":
        if op["key"] not in SETTINGS_KEYS:
            raise LedgerError(f"Step {i + 1}: setting must be one of {', '.join(SETTINGS_KEYS)}.")
        if op["key"] == "foregone_cashback_rate" and not (_num(op["value"]) and op["value"] < 1):
            raise LedgerError(f"Step {i + 1}: the cash-back rate is a fraction, for example 0.02 for 2%.")
    elif kind == "set_setup":
        if op["key"] not in SETUP_KEYS:
            raise LedgerError(f"Step {i + 1}: setup key must be one of {', '.join(SETUP_KEYS)}.")
        if op["key"] == "report_currency" and not CURRENCY_RE.match(str(op["value"])):
            raise LedgerError(f"Step {i + 1}: the report currency is a three-letter code such as USD.")
        if op["key"] == "storage" and op["value"] not in ("file", "folder"):
            raise LedgerError(f"Step {i + 1}: storage is file or folder; a Google Sheet is an export until the "
                              f"platform probe passes.")
    elif kind == "external":
        if op["target"] not in EXTERNAL_TARGETS:
            raise LedgerError(f"Step {i + 1}: external target must be one of {', '.join(EXTERNAL_TARGETS)}.")
        if op["action"] not in ("create", "update"):
            raise LedgerError(f"Step {i + 1}: finerd points only creates or updates in other apps; it never "
                              f"deletes, archives or shares.")
        p = op["payload"]
        if not isinstance(p, dict) or not p:
            raise LedgerError(f"Step {i + 1}: payload must list exactly what will be written.")
        if op["target"] == "calendar":
            if p.get("visibility", "private") != "private" or p.get("attendees"):
                raise LedgerError(f"Step {i + 1}: calendar events must be private and have no guests.")
            if TITLE_LEAK.search(str(p.get("title", ""))):
                raise LedgerError(f"Step {i + 1}: event titles carry no balances, member or account numbers.")
            if op["action"] == "create" and not (p.get("title") and is_date(p.get("date", ""))):
                raise LedgerError(f"Step {i + 1}: a new event needs a title and a date.")
            if op["action"] == "update" and not p.get("event_id"):
                raise LedgerError(f"Step {i + 1}: an event update needs the existing event_id.")
        base = external_op_id(op)
        prev = _latest_op(led, base)
        if prev and prev["state"] != "failed" and prev["payload_hash"] != sha(p):
            raise LedgerError(f"Step {i + 1}: an earlier write with the same key ({prev['op_id']}, {prev['state']}) had "
                              f"different values. Resolve it first, or plan an update of that record instead.")


def _payload_text(op):
    p = op["payload"]
    if op["target"] == "calendar":
        parts = []
        for k in ("title", "date", "reminder_minutes", "calendar_id", "event_id", "visibility"):
            if k in p:
                v = p[k]
                if k == "reminder_minutes":
                    v = "none" if v is None else f"{v // 1440} days before" if v % 1440 == 0 else f"{v} minutes before"
                parts.append(f"{k.replace('_minutes', '')}={v}")
        if p.get("description"):
            parts.append("details: " + " / ".join(str(p["description"]).splitlines()))
        return "; ".join(parts)
    return canonical(p)


def _describe(led, op):
    k = op["op"]
    if k == "add_person":
        return f"Add person «{op['name']}» (consent recorded {op['consent'].get('on', '')})"
    if k == "add_card":
        tail = f" ending {op['last4']}" if op.get("last4") else ""
        link = f", linked to {op['finance_link'].get('app')} account «{op['finance_link'].get('account_name') or op['finance_link'].get('account_id')}»" \
            if op.get("finance_link") else ""
        return f"Add card «{op['nickname']}»{tail} → catalog {op.get('catalog_ref') or 'not in catalog'}{link}"
    if k == "add_account":
        return f"Add {op['unit']} account «{op['nickname']}» ({op['program']})"
    if k == "add_redemption":
        cur = op.get("currency") or led["_meta"]["setup"]["report_currency"]
        return (f"Add redemption {op['booked_on']}: {op['points']:,} {op['program']} points + {op['fees']} {cur} fees, "
                f"fallback {op.get('fallback')}, normalized {op.get('normalized')} — {op.get('description', '')} "
                f"[{op['status']}]")
    if k == "add_cost":
        on = f" on {op['card']}" if op.get("card") else ""
        fx = f" × {op['fx_rate']}" if op.get("fx_rate") else ""
        return f"Add cost {op['date']}: {op['kind']}{on} {op['amount']} {op['currency']}{fx} — {op.get('description', '')}"
    if k == "add_certificate":
        return f"Add certificate «{op['type']}» on {op['account']}, expires {op.get('expires_on') or 'unknown'}"
    if k == "add_signup_offer":
        return f"Add sign-up offer on {op['card']}: {op['bonus']} after {op['spend']} by {op['deadline']}"
    if k == "observe":
        src = op["source"]
        return (f"Record {op['field']} = {op['value']} for {op['subject']} as of {op['as_of']} "
                f"(from {src['kind']}{': ' + str(src.get('name')) if src.get('name') else ''}, {op['confidence']})")
    if k == "void":
        return f"Mark observation {op['target']} as wrong: {op['reason']}"
    if k == "amend":
        rec = next((r for r in led[op["target"]] if r["id"] == op["id"]), {})
        return f"Change {op['field']} of {op['id']} from {rec.get(op['field'])!r} to {op.get('value')!r}: {op['reason']}"
    if k == "set_setting":
        return f"Set {op['key']} = {op['value']}"
    if k == "set_setup":
        return f"Set setup {op['key']} = {op['value']}"
    if k == "external":
        app = op.get("app") or op["target"]
        prev = _latest_op(led, external_op_id(op))
        state = ""
        if prev and prev["state"] in ("planned", "sent", "unknown", "confirmed"):
            state = f" — already {prev['state']}, will not be repeated"
        elif prev and prev["state"] == "failed":
            state = " — an earlier attempt failed; this is a retry"
        return f"{op['action'].capitalize()} in {app}: {_payload_text(op)}{state}"
    return k


def preview_batch(led, batch):
    """Validate a batch and return (hash, text). The text is what the person must see."""
    if not isinstance(batch, list) or not batch:
        raise LedgerError("A batch is a non-empty list of operations. If nothing was proposed, there is "
                          "nothing to record.")
    staged = set()
    keys = {}
    for i, op in enumerate(batch):
        _check_op(led, op, i, staged)
        if op.get("op") == "external":
            k = external_op_id(op)
            if k in keys and keys[k] != sha(op["payload"]):
                raise LedgerError(f"Step {i + 1}: two writes in this batch share one key but differ; keep one.")
            keys[k] = sha(op["payload"])
    groups = {}
    for op in batch:
        dest = "this ledger" if op["op"] != "external" else (op.get("app") or op["target"])
        text = EXTRA_OPS[op["op"]]["describe"](led, op) if op["op"] in EXTRA_OPS else _describe(led, op)
        groups.setdefault(dest, []).append(text)
    lines = [f"Planned changes (ledger version {led['version']}):"]
    for dest, items in groups.items():
        lines.append(f"\nIn {dest}:")
        lines += [f"  {n}. {t}" for n, t in enumerate(items, 1)]
    lines.append("\nNothing is deleted. Nothing else is changed.")
    h = sha({"base": led["version"], "ledger": led["ledger_id"], "batch": batch})
    lines.append(f"Batch {h}")
    return h, "\n".join(lines)


def apply_batch(led, batch, confirm_hash, session=None, now=None):
    """Apply a previewed batch to the in-memory ledger. Returns a list of results.
    External operations are only recorded as planned; the skill performs them
    through the person's connector and then records sent/confirmed.
    A ledger in a folder is guarded by bin/commit (lock and base hash), so it needs no lease;
    a ledger file still needs the v1 writer lease."""
    if led["_meta"]["setup"].get("storage") != "folder":
        require_lease(led, session, now)
    h, _ = preview_batch(led, batch)
    if confirm_hash != h:
        raise LedgerError("This batch is not the one the person saw (hash mismatch). Show the preview again.")
    ts = iso(now or now_utc())
    results = []
    for op in batch:
        k = op["op"]
        if k in EXTRA_OPS:
            results.append(EXTRA_OPS[k]["apply"](led, op, ts))
            continue
        if k in RECORD_OPS:
            rec = {key: val for key, val in op.items() if key != "op"}
            rec["added_at"] = ts
            led[RECORD_OPS[k]].append(rec)
            results.append({"op": k, "id": rec["id"]})
        elif k == "observe":
            rec = {key: op[key] for key in ("subject", "field", "value", "source", "as_of", "confidence")}
            for opt in ("method", "note", "unit", "person", "caveat"):
                if op.get(opt) is not None:
                    rec[opt] = op[opt]
            rec["id"] = new_id("obs")
            rec["observed_at"] = ts
            led["observations"].append(rec)
            results.append({"op": k, "id": rec["id"]})
        elif k == "void":
            rec = {"id": new_id("cor"), "action": "void", "target": op["target"], "reason": op["reason"],
                   "by": op.get("by", "person"), "at": ts}
            led["corrections"].append(rec)
            results.append({"op": k, "id": rec["id"]})
        elif k == "amend":
            rec = next(r for r in led[op["target"]] if r["id"] == op["id"])
            rec.setdefault("amendments", []).append({"field": op["field"], "old": rec.get(op["field"]),
                                                     "new": op.get("value"), "reason": op["reason"], "at": ts})
            rec[op["field"]] = op.get("value")
            results.append({"op": k, "id": op["id"], "field": op["field"]})
        elif k == "set_setting":
            led["_meta"]["settings"][op["key"]] = op["value"]
            results.append({"op": k, "key": op["key"]})
        elif k == "set_setup":
            led["_meta"]["setup"][op["key"]] = op["value"]
            results.append({"op": k, "key": op["key"]})
        elif k == "external":
            results.append(_plan_external(led, op, ts))
    return results


def _plan_external(led, op, ts):
    """Record an external write as planned (or recognize one already planned or done)."""
    base = external_op_id(op)
    prev = _latest_op(led, base)
    if prev and prev["state"] in ("confirmed", "sent", "planned", "unknown"):
        return {"op": "external", "op_id": prev["op_id"], "state": prev["state"], "skipped": True}
    op_id = base
    retry_of = None
    if prev and prev["state"] == "failed":
        n = sum(1 for x in led["oplog"] if x["op_id"] == base or x.get("retry_of") == base)
        op_id, retry_of = f"{base}-r{n + 1}", base
    entry = {
        "op_id": op_id, "target": op["target"], "app": op.get("app"), "action": op["action"],
        "summary": op["summary"], "payload": op["payload"], "payload_hash": sha(op["payload"]),
        "subject": op.get("subject"), "state": "planned", "destination_id": None,
        "created_at": ts, "updated_at": ts, "history": [{"state": "planned", "at": ts}],
    }
    if retry_of:
        entry["retry_of"] = retry_of
    led["oplog"].append(entry)
    return {"op": "external", "op_id": op_id, "state": "planned"}


# ---------------------------------------------------------------- external op states

def _readback_problems(op, read_back, destination_id):
    p = op["payload"]
    if not isinstance(read_back, dict) or not read_back:
        return ["the read-back is empty"]
    keys = READBACK_KEYS.get(op["target"])
    if keys is None:
        keys = tuple(p.keys())
    if op["target"] == "calendar":
        extra = ("calendar_id",) if p.get("calendar_id") else ()
        if op["action"] == "create":
            keys = keys + ("attendees",) + (("description",) if p.get("description") else ()) + extra
        else:
            keys = tuple(k for k in keys if k in p) + tuple(k for k in ("description", "attendees") if k in p) + extra
    elif op["action"] == "update":
        keys = tuple(k for k in keys if k in p)
    probs = []
    for k in keys:
        if k not in read_back:
            probs.append(f"{k} was not read back")
        elif k == "description" or (k == "attendees" and not read_back[k]):
            continue  # description: compared through the marker below; attendees: checked below
        elif k in p and read_back[k] != p[k]:
            probs.append(f"{k}: planned {p[k]!r}, found {read_back[k]!r}")
    for k, v in read_back.items():
        if k in p and k not in keys and k not in ("description", "members", "done", "all_day", "timezone",
                                                 "calendar_id") and v != p[k]:
            probs.append(f"{k}: planned {p[k]!r}, found {v!r}")
    if op["target"] == "calendar":
        if read_back.get("attendees"):
            probs.append("the event has guests")
        marker = re.search(r"\[finerd points op-[0-9a-f]+(-r\d+)?\]", str(p.get("description") or ""))
        if marker and "description" in read_back and marker.group(0) not in str(read_back["description"]):
            probs.append("the event description lost its finerd points marker")
        if p.get("calendar_id") and "calendar_id" in read_back and read_back["calendar_id"] != p["calendar_id"]:
            probs.append(f"the event is in calendar {read_back['calendar_id']}, not {p['calendar_id']}")
        if read_back.get("event_id") and destination_id and read_back["event_id"] != destination_id:
            probs.append(f"the read-back is for event {read_back['event_id']}, not {destination_id}")
    if op["action"] == "update" and p.get("event_id") and destination_id and destination_id != p["event_id"]:
        probs.append(f"the update was planned for {p['event_id']} but {destination_id} was read back")
    return probs


def set_op_state(led, op_id, state, session=None, destination_id=None, read_back=None, error=None, now=None):
    if led["_meta"]["setup"].get("storage") != "folder":
        require_lease(led, session, now)
    if state not in OP_STATES:
        raise LedgerError(f"State must be one of {', '.join(OP_STATES)}.")
    op = next((x for x in led["oplog"] if x["op_id"] == op_id), None)
    if not op:
        raise LedgerError(f"No planned operation {op_id}.")
    allowed = {
        "planned": {"sent", "unknown", "failed"},
        "sent": {"confirmed", "unknown", "failed"},
        "unknown": {"confirmed", "failed"},
        "confirmed": set(),
        "failed": set(),
    }
    if state not in allowed[op["state"]]:
        raise LedgerError(f"{op_id} is {op['state']}; it cannot become {state}. "
                          f"An unknown outcome is resolved (confirmed or failed) before any retry.")
    if read_back is not None:
        _refuse_forbidden(read_back, "The read-back")
    if error:
        _refuse_forbidden(str(error), "The error text")
    if not destination_id and op["action"] == "update" and op["payload"].get("event_id"):
        destination_id = op["payload"]["event_id"]  # an update targets the existing record
    if state == "confirmed":
        if read_back is None:
            raise LedgerError("«confirmed» needs a read-back of the destination's values.")
        probs = _readback_problems(op, read_back, destination_id)
        if probs:
            raise LedgerError("The read-back does not confirm the plan: " + "; ".join(probs)
                              + ". Mark the write unknown or failed, or read it back again.")
        if not (destination_id or op.get("destination_id")):
            raise LedgerError("«confirmed» needs the destination id (for example the calendar event id).")
    ts = iso(now or now_utc())
    op["state"] = state
    op["updated_at"] = ts
    if destination_id:
        op["destination_id"] = destination_id
    if read_back is not None:
        op["read_back"] = read_back
    if error:
        op["error"] = str(error)[:500]
    op["history"].append({"state": state, "at": ts})
    if state == "confirmed" and op["target"] == "calendar":
        _track_event(led, op, ts)
    return op


def _track_event(led, op, ts):
    """Record the event as the destination reported it (read-back values, not the plan)."""
    p, rb = op["payload"], op.get("read_back") or {}
    seen = {k: rb.get(k, p.get(k)) for k in ("title", "date", "reminder_minutes")}
    if "description" in rb:
        p = {**p, "description": rb["description"]}
    elif "description" in p:
        p = {**p, "description_unverified": True}
    ev = next((e for e in led["calendar_events"] if e["event_id"] == op["destination_id"]), None)
    if ev is None:
        led["calendar_events"].append({
            "id": "cal-" + re.sub(r"[^a-z0-9]", "", op["destination_id"].lower())[:24] + "-" + op["op_id"][3:9],
            "event_id": op["destination_id"], "calendar_id": p.get("calendar_id"), "subject": op.get("subject"),
            "members": p.get("members") or [], "description": p.get("description"), "done": p.get("done", False),
            "description_unverified": bool(p.get("description_unverified")),
            "created_at": ts, "updated_at": ts, "op_id": op["op_id"], **seen,
        })
    else:
        for k, v in seen.items():
            if k in p or k in rb:
                ev[k] = v
        for k in ("done", "members", "description"):
            if k in p:
                ev[k] = p[k]
        ev["updated_at"] = ts


def pending_ops(led):
    return [x for x in led["oplog"] if x["state"] in ("planned", "sent", "unknown")]


# ---------------------------------------------------------------- household privacy withdrawal

def _owned_subjects(led, person_id):
    cards = {c["id"] for c in led["cards"] if c.get("person") == person_id}
    accounts = {a["id"] for a in led["accounts"] if a.get("person") == person_id}
    cert_ids = {x["id"] for x in led["certificates"] if x.get("account") in accounts}
    offer_ids = {x["id"] for x in led["signup_offers"] if x.get("card") in cards}

    def owned(s):
        if not s:
            return False
        if s in {f"card:{c}" for c in cards} | {f"account:{a}" for a in accounts}:
            return True
        if any(s.startswith(f"benefit:{c}/") for c in cards):
            return True
        if s.startswith("certificate:") and s.split(":", 1)[1] in cert_ids:
            return True
        return s.startswith("signup:") and s.split(":", 1)[1] in offer_ids
    return cards, accounts, owned


def _word_in(name, text):
    return bool(name) and len(str(name)) >= 3 and re.search(r"(?<!\w)" + re.escape(str(name)) + r"(?!\w)", text) is not None


def redaction_plan(led, person_id):
    """What a member's privacy withdrawal would remove from the current ledger."""
    if person_id == next((p["id"] for p in led["people"] if p.get("role") == "owner"), None):
        raise LedgerError("The ledger owner cannot be redacted; delete the ledger file instead.")
    if not any(p["id"] == person_id for p in led["people"]):
        raise LedgerError(f"No person {person_id} in this ledger.")
    cards, accounts, owned = _owned_subjects(led, person_id)
    names = [c["nickname"] for c in led["cards"] if c["id"] in cards] + \
            [a["nickname"] for a in led["accounts"] if a["id"] in accounts] + \
            [p.get("name") for p in led["people"] if p["id"] == person_id]
    for coll in ("cards", "accounts"):
        for rec in led[coll]:
            for a in rec.get("amendments", []):
                if a.get("field") == "person" and person_id in (a.get("old"), a.get("new")):
                    names += [x.get("old") for x in rec.get("amendments", []) if x.get("field") == "nickname"]
    transferred_obs = []
    for c in led["cards"]:
        moves = [a for a in c.get("amendments", []) if a.get("field") == "person" and a.get("old") == person_id]
        if moves:
            when = min(a["at"] for a in moves)
            transferred_obs += [o["id"] for o in led["observations"]
                                if (o["subject"] == f"card:{c['id']}" or o["subject"].startswith(f"benefit:{c['id']}/"))
                                and o.get("observed_at", "") <= when]
    plan = {
        "people": [person_id],
        "cards": sorted(cards),
        "accounts": sorted(accounts),
        "observations": sorted({o["id"] for o in led["observations"] if o.get("person") == person_id or owned(o["subject"])}
                               | set(transferred_obs)),
        "redemptions": sorted(r["id"] for r in led["redemptions"] if r.get("person") == person_id),
        "costs": sorted(c["id"] for c in led["costs"] if c.get("person") == person_id or c.get("card") in cards),
        "certificates": sorted(c["id"] for c in led["certificates"] if c.get("account") in accounts),
        "signup_offers": sorted(s["id"] for s in led["signup_offers"] if s.get("card") in cards),
        "calendar_events": sorted(e["event_id"] for e in led["calendar_events"]
                                  if owned(e.get("subject")) or any(owned(m) for m in e.get("members") or [])),
        "oplog": sorted(x["op_id"] for x in led["oplog"]
                        if owned(x.get("subject")) or any(owned(m) for m in (x["payload"].get("members") or []))
                        or any(_word_in(n, canonical(x)) for n in names if n and len(str(n)) >= 3)),
    }
    # schema 2: what was collected from sites for this person
    src_accounts = sorted(f"{s_['id']}/{a['id']}" for s_ in led.get("sources", []) for a in s_["accounts"]
                          if a.get("person") == person_id)
    owned_acc = set(src_accounts)
    recs = sorted(r["id"] for r in led.get("records", []) if f"{r['source']}/{r['account']}" in owned_acc)
    rset = set(recs)
    plan.update({
        "inventory": sorted(x["id"] for x in led.get("inventory", []) if x.get("person") == person_id),
        "source_accounts": src_accounts,
        "records": recs,
        "events": sorted(e["id"] for e in led.get("events", []) if set(e.get("records", [])) & rset),
    })
    text = [f"Removing {person_id}'s data from the current ledger:"]
    for k, v in plan.items():
        if v and k not in ("calendar_events", "oplog", "_names"):
            text.append(f"  {k}: {len(v)}")
    if plan["oplog"]:
        text.append(f"  write-log entries scrubbed of their details: {len(plan['oplog'])}")
    if plan["calendar_events"]:
        text.append(f"  calendar events to clear (details and reminders removed, events kept): {len(plan['calendar_events'])}")
    text.append("Not changed: earlier exports or copies of this file, copies in old conversations, and anything "
                "in finance apps. The person deletes those themselves.")
    plan["_names"] = sorted({n for n in names if n and len(str(n)) >= 3})
    h = sha({"ledger": led["ledger_id"], "base": led["version"], "plan": plan})
    text.append(f"Redaction {h}")
    return h, plan, "\n".join(text)


def redact_person(led, person_id, confirm_hash, session=None, now=None):
    if led["_meta"]["setup"].get("storage") != "folder":
        require_lease(led, session, now)
    h, plan, _ = redaction_plan(led, person_id)
    if h != confirm_hash:
        raise LedgerError("This is not the removal the person saw (hash mismatch). Show the plan again.")
    apply_redaction(led, person_id, plan)
    ts = iso(now or now_utc())
    ops = []
    for ev in led["calendar_events"]:
        if ev["event_id"] in plan["calendar_events"]:
            ops.append({"op": "external", "target": "calendar", "action": "update", "app": "calendar",
                        "summary": f"Clear details and reminders of event {ev['event_id']}",
                        "payload": {"event_id": ev["event_id"], "calendar_id": ev.get("calendar_id"),
                                    "title": "finerd points (removed)", "description": "",
                                    "reminder_minutes": None, "visibility": "private"},
                        "match_key": f"redact:{ev['event_id']}"})
            ev["subject"] = None
            ev["members"] = []
            ev["title"] = "finerd points (removed)"
            ev["description"] = ""
    for op in ops:  # the person agreed to clearing these events with the removal: planned in the same commit
        _plan_external(led, op, ts)
    led["_meta"]["redactions"].append({"at": ts, "person": person_id, "files_scrubbed": False,
                                       "removed": tombstones(plan),
                                       "counts": {k: len(v) for k, v in plan.items() if k != "_names"}})
    return ops


def tombstones(plan):
    """The ids a removal took away; no later change may name them again (no replay brings data back)."""
    return {k: sorted(plan.get(k, [])) for k in ("cards", "accounts", "records", "inventory", "source_accounts",
                                                   "certificates", "signup_offers", "redemptions", "costs")}


def _removed_refs(led):
    out = {"person": set(), "card": set(), "account": set(), "record": set(), "inventory": set(),
           "source_account": set(), "certificate": set(), "signup": set(), "other": set()}
    for r in led["_meta"].get("redactions", []):
        if r.get("person"):
            out["person"].add(r["person"])
        t = r.get("removed") or {}
        out["card"].update(t.get("cards", []))
        out["account"].update(t.get("accounts", []))
        out["record"].update(t.get("records", []))
        out["inventory"].update(t.get("inventory", []))
        out["source_account"].update(t.get("source_accounts", []))
        out["certificate"].update(t.get("certificates", []))
        out["signup"].update(t.get("signup_offers", []))
        out["other"].update(t.get("redemptions", []) + t.get("costs", []))
    return out


def names_removed(op, refs):
    """True when an operation names a removed person or anything a removal took away, directly or through a
    subject such as benefit:<card>/…, account:<id> or certificate:<id>."""
    if not isinstance(op, dict):
        return False
    if _persons_named(op) & refs["person"] or (op.get("op") == "add_person" and op.get("id") in refs["person"]):
        return True
    ids = refs["card"] | refs["account"] | refs["record"] | refs["inventory"] | refs["certificate"] | \
        refs["signup"] | refs["other"]

    def walk(x, key=None):
        if isinstance(x, dict):
            if "source" in x and "account" in x and f"{x.get('source')}/{x.get('account')}" in refs["source_account"]:
                return True
            return any(walk(v, k) for k, v in x.items())
        if isinstance(x, list):
            return any(walk(v, key) for v in x)
        if isinstance(x, str):
            if key in ("id", "card", "account", "record", "a", "b", "inventory", "target", "redemption") and x in ids:
                return True
            m = re.match(r"^(card|account|benefit|certificate|signup):([^/]+)", x)
            if m and m.group(2) in ids:
                return True
        return False
    return walk(op)


def apply_redaction(led, person_id, plan=None):
    """Remove a household member's data from a ledger (the current one, a backup or a candidate). The
    person's confirmation is checked by redact_person for the current ledger; older copies in the
    ledger folder are scrubbed with the same plan by fpstore.scrub_person."""
    if plan is None:
        if not any(p["id"] == person_id for p in led["people"]):
            plan = {k: [] for k in ("people", "cards", "accounts", "observations", "redemptions", "costs",
                                    "certificates", "signup_offers", "calendar_events", "oplog", "inventory",
                                    "source_accounts", "records", "events")}
            plan["_names"] = []
            src = {f"{s_['id']}/{a['id']}" for s_ in led.get("sources", []) for a in s_["accounts"]
                   if a.get("person") == person_id}
            plan["source_accounts"] = sorted(src)
            plan["records"] = [r["id"] for r in led.get("records", []) if f"{r['source']}/{r['account']}" in src]
            plan["inventory"] = [x["id"] for x in led.get("inventory", []) if x.get("person") == person_id]
        else:
            _, plan, _ = redaction_plan(led, person_id)
    for coll in ("people", "cards", "accounts", "observations", "redemptions", "costs", "certificates", "signup_offers",
                 "inventory", "records", "events"):
        drop = set(plan.get(coll, []))
        if coll in led:
            led[coll] = [r for r in led[coll] if r["id"] not in drop]
    gone = set(plan.get("source_accounts", []))
    keep_sources = []
    for s_ in led.get("sources", []):
        s_["accounts"] = [a for a in s_["accounts"] if f"{s_['id']}/{a['id']}" not in gone]
        s_["coverage"] = [c for c in s_.get("coverage", []) if f"{s_['id']}/{c['account']}" not in gone]
        if s_["accounts"]:
            keep_sources.append(s_)
    if "sources" in led:
        led["sources"] = keep_sources
    dropped_obs = set(plan["observations"])
    led["corrections"] = [c for c in led.get("corrections", []) if c["target"] not in dropped_obs]
    names = plan.get("_names", [])
    for coll in COLLECTIONS:
        for rec in led.get(coll, []):
            for a in rec.get("amendments", []) if isinstance(rec, dict) else []:
                text = canonical([a.get("old"), a.get("new"), a.get("reason")])
                if person_id in (a.get("old"), a.get("new")) or any(_word_in(n, text) for n in names):
                    a["old"] = a["new"] = "(removed at a household member's request)"
                    a["reason"] = "(removed)"
    for x in led["oplog"]:
        if x["op_id"] in plan["oplog"]:
            x["summary"] = "(removed at a household member's request)"
            x["payload"] = {"redacted": True}
            x.pop("read_back", None)
            x.pop("error", None)
            x["subject"] = None


# ---------------------------------------------------------------- export

def export_csv(led, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for coll in COLLECTIONS:
        rows = led[coll]
        if not rows:
            continue
        keys = sorted({k for r in rows for k in r.keys()})
        path = out / f"{coll}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([_cell(k) for k in keys])
            for r in rows:
                w.writerow([_cell(r.get(k)) for k in keys])
        written.append(str(path))
    return written


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = canonical(v)
    s = str(v)
    # Spreadsheet formula injection guard: text from outside is always literal.
    if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.match(r"^-?\d+(\.\d+)?$", s):
        s = "'" + s
    return s


def summary(led):
    obs = active_observations(led)
    return {
        "ledger_id": led["ledger_id"], "version": led["version"], "updated_at": led["updated_at"],
        "setup": led["_meta"]["setup"], "writer": lease_status(led),
        "counts": {c: len(led[c]) for c in COLLECTIONS},
        "active_observations": len(obs),
        "pending_external_writes": [{"op_id": x["op_id"], "state": x["state"], "summary": x["summary"]}
                                    for x in pending_ops(led)],
    }
