"""finerd points — what was read from a site, as ledger records (spec v2, appendix C).

`plan_read` turns one read of one account section (rows plus what the read covered) into a batch
for the person's preview: new records, rows already known, pending→posted revisions, «possibly the
same» links, rows no longer shown, dropped pending rows and the read's coverage. `counted_records`
says which records the report counts and which totals are preliminary.

Rules (spec v2, appendix C):
- A site's own id is the identity only when it is unique in the read and was seen with the same
  record in two reads; otherwise the row is treated as having no id.
- Without an id, rows are compared only with records of the same account whose dates lie inside the
  interval this read covers completely. Exact match = same date, signed amount, normalized
  description and status; identical rows on one complete day pair one to one by count. A day cut
  off by a partial read is matched only exactly.
- The only automatic revision is pending→posted. Every other difference becomes a «possibly the
  same» link: the report counts the earlier record, leaves the new one out and marks the totals
  preliminary until the person decides.
- A posted record no longer shown inside the covered interval is flagged and still counted until the
  person confirms. A pending record is dropped only by a complete read covering its date and the
  following 10 days.
- Rows from different sources are never merged: a likely match is linked «probably the same» and
  counted once, at the direct source's value, until the person confirms.

Python 3.9+, standard library only.
"""
import datetime as _dt
import re

import fpledger as fl

SOURCE_KINDS = ("program", "bank_card", "aggregator", "sheet", "email", "statement", "other")
INVENTORY_KINDS = ("program", "card", "bank", "app", "aggregator", "sheet", "other")
COVERAGE_STATES = ("complete", "ends_unreconciled", "partial", "unavailable")
STATUSES = ("posted", "pending")
METHODS = ("text", "screenshot", "file", "person")
RELATIONS = ("possibly_same", "probably_same")
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
WINDOW_DAYS = 14          # «possibly the same» window, either side
PENDING_POST_DAYS = 10    # a pending row posts within this many days
PENDING_TOLERANCE = 0.20  # posted amount within 20% of the pending one (tips)
CROSS_DAYS = 3            # cross-source «probably the same» window
DESC_LIMIT = 200
# Text that speaks to an AI assistant rather than describing an account row. It is stored as data and
# reported to the person (spec v2, appendix B «Untrusted content»); it never changes the task.
ADDRESSES_AI = re.compile(
    r"(?i)\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|rules|previous|above)\b|"
    r"\b(system|developer)\s+prompt\b|\byou\s+are\s+(now\s+)?(an?|the)\s+(ai|assistant|agent|model)\b|"
    r"\b(ai|assistant|claude|chatgpt|gpt|agent)\s*[:,]\s*(please\s+)?(open|go|send|transfer|redeem|click|"
    r"navigate|visit|email|forward|ignore|delete)\b|"
    r"\b(open|visit|navigate to|go to)\s+https?://|\bsend\b.{0,40}\b(to|at)\b.{0,40}@")
EVIDENCE_LIMIT = 300


# ---------------------------------------------------------------- small helpers

def _d(s):
    return _dt.date.fromisoformat(s)


def _days(a, b):
    return (_d(b) - _d(a)).days


def norm_desc(text):
    """Normalized description for exact matching: case-folded, punctuation removed, spaces collapsed."""
    t = re.sub(r"[^\w\s]", " ", str(text or "").casefold())
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text):
    return {t for t in norm_desc(text).split() if len(t) > 1}


def similar(a, b):
    """Descriptions that could name the same event: one contains the other, or half the words are shared."""
    na, nb = norm_desc(a), norm_desc(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def _sign(x):
    return (x > 0) - (x < 0)


def _inside(date, interval):
    return bool(interval) and interval[0] <= date <= interval[1]


def _key(r):
    return (r["date"], r["amount"], norm_desc(r["description"]), r["status"])


def _active(rec):
    return rec.get("state", "active") == "active"


# ---------------------------------------------------------------- operations (registered with fpledger)

def _refuse(i, msg):
    raise fl.LedgerError(f"Step {i + 1}: {msg}")


def _person_ok(led, pid, staged):
    return any(p["id"] == pid and p.get("consent", {}).get("given") for p in led["people"]) or \
        ("people", pid) in staged


def _find(led, coll, rid, staged=None):
    rec = next((r for r in led[coll] if r.get("id") == rid), None)
    if rec is None and staged is not None and (coll, rid) in staged:
        return {}
    return rec


def _clean_or_refuse(i, field, value, limit):
    if value is None:
        return
    if not isinstance(value, str) or value != fl.clean_text(value, limit):
        _refuse(i, f"{field} must be stored as cleaned text (use fpcollect.plan_read, which removes markup, "
                   f"control characters and identifiers and caps the length).")


def _check_interval(i, name, v):
    if not (isinstance(v, list) and len(v) == 2 and all(fl.is_date(x) for x in v) and v[0] <= v[1]):
        _refuse(i, f"{name} is [from, to] with real dates, from ≤ to.")


def check_add_inventory(led, op, i, staged):
    if not fl.ID_RE.match(op["id"]) or _find(led, "inventory", op["id"]) or ("inventory", op["id"]) in staged:
        _refuse(i, f"inventory id {op['id']!r} is invalid or already used.")
    if op["kind"] not in INVENTORY_KINDS:
        _refuse(i, f"inventory kind must be one of {', '.join(INVENTORY_KINDS)}.")
    if not _person_ok(led, op["person"], staged):
        _refuse(i, f"person {op['person']} is not in the ledger with their consent.")
    _clean_or_refuse(i, "label", op["label"], 80)
    if op.get("found_by") not in (None, "person", "email", "source"):
        _refuse(i, "found_by is person, email or source.")
    staged.add(("inventory", op["id"]))


def check_add_source(led, op, i, staged):
    if not fl.ID_RE.match(op["id"]) or _find(led, "sources", op["id"]) or ("sources", op["id"]) in staged:
        _refuse(i, f"source id {op['id']!r} is invalid or already used.")
    if op["kind"] not in SOURCE_KINDS:
        _refuse(i, f"source kind must be one of {', '.join(SOURCE_KINDS)}.")
    _clean_or_refuse(i, "name", op["name"], 80)
    hosts = op.get("hosts") or []
    if not isinstance(hosts, list) or not all(isinstance(h, str) and HOST_RE.match(h) for h in hosts):
        _refuse(i, "hosts are plain lowercase host names (for example global.americanexpress.com).")
    accounts = op["accounts"]
    if not isinstance(accounts, list) or not accounts:
        _refuse(i, "a source lists the accounts inside it.")
    seen = set()
    for a in accounts:
        if not isinstance(a, dict) or not fl.ID_RE.match(str(a.get("id", ""))) or a["id"] in seen:
            _refuse(i, "each account in a source has a unique id.")
        seen.add(a["id"])
        if set(a) - {"id", "label", "person", "unit", "inventory"}:
            _refuse(i, "a source account has only id, label, person, unit and inventory.")
        if not _person_ok(led, a.get("person"), staged):
            _refuse(i, f"account {a['id']}: person {a.get('person')} is not in the ledger with their consent; "
                       f"another person's accounts are skipped.")
        _clean_or_refuse(i, "account label", a.get("label"), 80)
        if a.get("inventory") and not (_find(led, "inventory", a["inventory"], staged) is not None):
            _refuse(i, f"account {a['id']}: inventory item {a['inventory']} not found.")
    staged.add(("sources", op["id"]))


def _source(led, sid, staged, i):
    s = _find(led, "sources", sid, staged)
    if s is None:
        _refuse(i, f"source {sid} not found.")
    return s


def _account_ok(led, op, staged, i):
    s = _source(led, op["source"], staged, i)
    if s and not any(a["id"] == op["account"] for a in s["accounts"]):
        _refuse(i, f"account {op['account']} is not in source {op['source']}.")


def check_add_coverage(led, op, i, staged):
    _account_ok(led, op, staged, i)
    if op["state"] not in COVERAGE_STATES:
        _refuse(i, f"coverage state must be one of {', '.join(COVERAGE_STATES)}.")
    _check_interval(i, "requested", op["requested"])
    if op.get("covered") is not None:
        _check_interval(i, "covered", op["covered"])
    if op["state"] == "complete" and not (op.get("terminal") and op.get("continuity") and op.get("covered")):
        _refuse(i, "«complete» needs terminal evidence, continuity and the covered interval (spec v2 step 6).")
    for f, n in (("terminal", 200), ("continuity", 200), ("stop_reason", 200), ("as_of_text", 80)):
        _clean_or_refuse(i, f, op.get(f), n)
    for d in op.get("incomplete_days") or []:
        if not fl.is_date(d):
            _refuse(i, "incomplete_days are dates.")


def check_add_record(led, op, i, staged):
    if not fl.ID_RE.match(op["id"]) or _find(led, "records", op["id"]) or ("records", op["id"]) in staged:
        _refuse(i, f"record id {op['id']!r} is invalid or already used.")
    _account_ok(led, op, staged, i)
    if not fl.is_date(op["date"]):
        _refuse(i, "date must be a real date, YYYY-MM-DD.")
    if not fl._num(op["amount"], minimum=-float("inf")):
        _refuse(i, "amount is a signed number.")
    if op["status"] not in STATUSES:
        _refuse(i, "status is posted or pending.")
    _clean_or_refuse(i, "description", op["description"], DESC_LIMIT)
    ev = op["evidence"]
    if not isinstance(ev, dict) or ev.get("method") not in METHODS or set(ev) - {"text", "where", "method"}:
        _refuse(i, "evidence is {text, where, method}, method text, screenshot, file or person.")
    _clean_or_refuse(i, "evidence text", ev.get("text"), EVIDENCE_LIMIT)
    _clean_or_refuse(i, "evidence place", ev.get("where"), 120)
    if op.get("site_id") is not None and not re.match(r"^[A-Za-z0-9._:-]{1,80}$", str(op["site_id"])):
        _refuse(i, "site_id is the site's own row id (letters, digits, . _ : -).")
    staged.add(("records", op["id"]))


def check_record_change(led, op, i, staged):
    rec = _find(led, "records", op["record"], staged)
    if rec is None:
        _refuse(i, f"record {op['record']} not found.")
    k = op["op"]
    if k == "revise_record":
        if op["reason"] not in ("pending_posted", "site_id"):
            _refuse(i, "a record is revised automatically only pending→posted or by a stable site id.")
        if rec and op["reason"] == "pending_posted" and rec.get("status") != "pending":
            _refuse(i, "only a pending record becomes posted.")
        for f in ("date",):
            if not fl.is_date(op["new"].get(f, "")):
                _refuse(i, "a revision carries the new date.")
        _clean_or_refuse(i, "description", op["new"].get("description"), DESC_LIMIT)
        if op["new"].get("status") not in STATUSES:
            _refuse(i, "a revision carries the new status.")
    if k == "drop_pending" and rec and rec.get("status") != "pending":
        _refuse(i, "only a pending record is dropped.")


def check_link(led, op, i, staged):
    if op["relation"] not in RELATIONS:
        _refuse(i, f"relation is one of {', '.join(RELATIONS)}.")
    for r in (op["a"], op["b"]):
        if _find(led, "records", r, staged) is None:
            _refuse(i, f"record {r} not found.")
    _clean_or_refuse(i, "basis", op.get("basis"), 200)


def check_resolve(led, op, i, staged):
    k = op["op"]
    if k == "resolve_link":
        ev = _find(led, "events", op["link"])
        if not ev or ev.get("kind") != "link":
            _refuse(i, f"link {op['link']} not found.")
        if op["decision"] not in ("same", "different"):
            _refuse(i, "the decision is same or different.")
    else:  # resolve_not_shown
        rec = _find(led, "records", op["record"])
        if not rec or not rec.get("not_shown"):
            _refuse(i, f"record {op['record']} is not flagged as no longer shown.")
        if op["decision"] not in ("gone", "keep"):
            _refuse(i, "the decision is gone (leave it out of totals) or keep.")


def _apply_add_inventory(led, op, ts):
    rec = {k: v for k, v in op.items() if k != "op"}
    rec["added_at"] = ts
    led["inventory"].append(rec)
    return {"op": op["op"], "id": rec["id"]}


def _apply_add_source(led, op, ts):
    rec = {k: v for k, v in op.items() if k != "op"}
    rec["added_at"] = ts
    rec["coverage"] = []
    led["sources"].append(rec)
    return {"op": op["op"], "id": rec["id"]}


def _apply_add_coverage(led, op, ts):
    s = _find(led, "sources", op["source"])
    rec = {k: v for k, v in op.items() if k not in ("op", "source")}
    rec["recorded_at"] = ts
    s["coverage"].append(rec)
    return {"op": op["op"], "source": op["source"], "account": op["account"], "state": op["state"]}


def _apply_add_record(led, op, ts):
    rec = {k: v for k, v in op.items() if k not in ("op",)}
    rec["state"] = "active"
    rec["seen_in"] = [op["read_id"]]
    rec["added_at"] = ts
    led["records"].append(rec)
    return {"op": op["op"], "id": rec["id"]}


def _apply_record_change(led, op, ts):
    rec = _find(led, "records", op["record"])
    k = op["op"]
    if k == "seen_record":
        if op["read_id"] not in rec["seen_in"]:
            rec["seen_in"].append(op["read_id"])
    elif k == "revise_record":
        old = {f: rec.get(f) for f in ("date", "amount", "description", "status", "site_id")}
        rec.setdefault("revisions", []).append({"old": old, "reason": op["reason"], "read_id": op["read_id"],
                                                "at": ts})
        for f, v in op["new"].items():
            rec[f] = v
        if op["read_id"] not in rec["seen_in"]:
            rec["seen_in"].append(op["read_id"])
    elif k == "flag_not_shown":
        rec["not_shown"] = {"read_id": op["read_id"], "at": ts, "decision": None}
    elif k == "drop_pending":
        rec["state"] = "dropped"
        rec["dropped"] = {"read_id": op["read_id"], "at": ts}
    elif k == "resolve_not_shown":
        rec["not_shown"]["decision"] = op["decision"]
        rec["not_shown"]["decided_at"] = ts
        if op["decision"] == "gone":
            rec["state"] = "no_longer_shown"
    return {"op": k, "record": op["record"]}


def _apply_link(led, op, ts):
    ev = {"id": op.get("id") or fl.new_id("lnk"), "kind": "link", "relation": op["relation"],
          "records": [op["a"], op["b"]], "basis": op.get("basis", ""), "state": "unresolved", "added_at": ts}
    led["events"].append(ev)
    return {"op": op["op"], "id": ev["id"]}


def _apply_resolve_link(led, op, ts):
    ev = _find(led, "events", op["link"])
    ev["state"] = op["decision"]
    ev["decided_at"] = ts
    return {"op": op["op"], "id": ev["id"], "decision": op["decision"]}


def _describe_record(r):
    sign = "+" if r["amount"] > 0 else ""
    return f"{r['date']} {sign}{r['amount']:,} {r.get('unit', '')} «{r['description']}»".replace("  ", " ")


def _describe(led, op):
    k = op["op"]
    if k == "add_inventory":
        return f"Inventory: {op['label']} ({op['kind']}, {op['person']})" + \
            (" — found in your email, confirmed by you" if op.get("found_by") == "email" else "")
    if k == "add_source":
        names = ", ".join(a.get("label") or a["id"] for a in op["accounts"])
        return f"Source {op['name']} ({op['kind']}): {names}"
    if k == "add_coverage":
        cov = f"{op['covered'][0]} to {op['covered'][1]}" if op.get("covered") else "nothing completely"
        why = f"; stopped: {op['stop_reason']}" if op.get("stop_reason") else ""
        return f"Coverage of {op['source']}/{op['account']} {op['section']}: {op['state']}, covers {cov}{why}"
    if k == "add_record":
        st = "" if op["status"] == "posted" else " (pending, not counted)"
        return f"New row {_describe_record(op)}{st}"
    if k == "seen_record":
        return f"Already in the ledger: {op['record']}"
    if k == "revise_record":
        return f"Pending row {op['record']} has posted: {_describe_record({**op['new'], 'unit': ''})}"
    if k == "link_records":
        return f"Possibly the same as an earlier row: {op['b']} ↔ {op['a']} ({op.get('basis', '')}); " \
               f"the earlier one is counted until you decide"
    if k == "flag_not_shown":
        return f"No longer shown on the site: {op['record']} (still counted until you confirm it is gone)"
    if k == "drop_pending":
        return f"Pending row {op['record']} never posted; dropped"
    if k == "resolve_link":
        return f"Your decision on {op['link']}: {op['decision']}"
    if k == "resolve_not_shown":
        return f"Your decision on {op['record']}: {op['decision']}"
    return k


V2 = {
    "add_inventory": (("id", "kind", "label", "person"), {"id", "kind", "label", "person", "catalog_ref",
                                                            "found_by", "note"},
                      check_add_inventory, _apply_add_inventory),
    "add_source": (("id", "kind", "name", "accounts"), {"id", "kind", "name", "hosts", "market", "unit",
                                                        "catalog_ref", "accounts"},
                   check_add_source, _apply_add_source),
    "add_coverage": (("source", "account", "section", "read_id", "requested", "state", "read_at"),
                     {"source", "account", "section", "read_id", "requested", "covered", "state", "terminal",
                      "continuity", "stop_reason", "incomplete_days", "opening_balance", "as_of_text", "read_at",
                      "filters"},
                     check_add_coverage, _apply_add_coverage),
    "add_record": (("id", "source", "account", "section", "read_id", "date", "amount", "unit", "description",
                    "status", "evidence"),
                   {"id", "source", "account", "section", "read_id", "date", "amount", "unit", "description",
                    "status", "evidence", "site_id"},
                   check_add_record, _apply_add_record),
    "seen_record": (("record", "read_id"), {"record", "read_id"}, check_record_change, _apply_record_change),
    "revise_record": (("record", "read_id", "reason", "new"), {"record", "read_id", "reason", "new"},
                      check_record_change, _apply_record_change),
    "flag_not_shown": (("record", "read_id"), {"record", "read_id"}, check_record_change, _apply_record_change),
    "drop_pending": (("record", "read_id"), {"record", "read_id"}, check_record_change, _apply_record_change),
    "link_records": (("a", "b", "relation"), {"id", "a", "b", "relation", "basis"}, check_link, _apply_link),
    "resolve_link": (("link", "decision"), {"link", "decision"}, check_resolve, _apply_resolve_link),
    "resolve_not_shown": (("record", "decision"), {"record", "decision"}, check_resolve, _apply_record_change),
}
for _name, (_req, _allowed, _check, _apply) in V2.items():
    fl.register_op(_name, _req, _allowed, _check, _apply, _describe)


# ---------------------------------------------------------------- planning one read

def clean_row(row):
    ev = row.get("evidence") or {}
    out = {
        "date": row["date"],
        "amount": row["amount"],
        "description": fl.clean_text(row.get("description"), DESC_LIMIT),
        "status": row.get("status", "posted"),
        "evidence": {"text": fl.clean_text(ev.get("text") or row.get("description"), EVIDENCE_LIMIT),
                     "where": fl.clean_text(ev.get("where"), 120), "method": ev.get("method", "text")},
    }
    if row.get("site_id") not in (None, ""):
        out["site_id"] = str(row["site_id"])
    return out


def plan_read(led, read):
    """Plan the batch for one read of one account section. Returns (batch, summary).

    read = {source, account, section, read_id, requested: [from, to], covered: [from, to] | None,
            state, terminal, continuity, stop_reason, incomplete_days, opening_balance, as_of_text,
            read_at, unit, rows: [{date, amount, description, status, site_id, evidence}]}
    The source (and its accounts) must already be in the ledger or added earlier in the same batch;
    pass `source_op` to add it in this batch."""
    src_id, acc, sec, rid = read["source"], read["account"], read["section"], read["read_id"]
    covered = read.get("covered")
    cut = set(read.get("incomplete_days") or [])
    unit = read.get("unit", "")
    rows = [clean_row(r) for r in read["rows"]]
    for r in rows:
        r["_norm"] = norm_desc(r["description"])
    batch = []
    if read.get("source_op"):
        batch.append(read["source_op"])
    cov = {"op": "add_coverage", "source": src_id, "account": acc, "section": sec, "read_id": rid,
           "requested": read["requested"], "state": read["state"], "read_at": read["read_at"]}
    for f in ("covered", "terminal", "continuity", "stop_reason", "opening_balance", "as_of_text", "filters"):
        if read.get(f) not in (None, ""):
            cov[f] = fl.clean_text(read[f], 200) if f in ("terminal", "continuity", "stop_reason", "as_of_text") \
                else read[f]
    if cut:
        cov["incomplete_days"] = sorted(cut)
    batch.append(cov)

    mine = [r for r in led["records"] if r["source"] == src_id and r["account"] == acc and r["section"] == sec
            and _active(r)]
    matched = set()   # existing record ids accounted for by this read
    taken = set()     # indexes of rows accounted for
    summary = {"new": 0, "known": 0, "revised": 0, "possibly_same": 0, "not_shown": 0, "dropped_pending": 0,
               "probably_same_other_source": 0,
               "addressed_to_ai": [raw.get("description", "")[:120] for raw in read["rows"]
                                   if ADDRESSES_AI.search(str(raw.get("description", "")) + " " +
                                                          str((raw.get("evidence") or {}).get("text", "")))]}

    # 1. the site's own ids
    id_count = {}
    for r in rows:
        if "site_id" in r:
            id_count[r["site_id"]] = id_count.get(r["site_id"], 0) + 1
    for n, r in enumerate(rows):
        sid = r.get("site_id")
        if not sid:
            continue
        if id_count[sid] != 1:
            del r["site_id"]  # not unique in this read: treated as a row without an id
            continue
        cands = [e for e in mine if e.get("site_id") == sid and e["id"] not in matched]
        if len(cands) != 1:
            continue
        e = cands[0]
        r_key = (r["date"], r["amount"], r["_norm"], r["status"])
        if _key(e) == r_key:
            batch.append({"op": "seen_record", "record": e["id"], "read_id": rid})
            summary["known"] += 1
        elif len(e.get("seen_in", [])) >= 2:
            # a stable id (seen with this record in two reads): the changed row is a revision
            batch.append({"op": "revise_record", "record": e["id"], "read_id": rid,
                          "reason": "pending_posted" if e["status"] == "pending" and r["status"] == "posted"
                          else "site_id",
                          "new": {"date": r["date"], "amount": r["amount"], "description": r["description"],
                                  "status": r["status"]}})
            summary["revised"] += 1
        else:
            continue  # an id seen in only one read is not trusted with changed content
        matched.add(e["id"])
        taken.add(n)

    # 2. exact matches, one to one by count within a day
    def in_scope(date):
        return _inside(date, covered) or date in cut

    pool = {}
    for e in mine:
        if e["id"] not in matched and in_scope(e["date"]):
            pool.setdefault(_key(e), []).append(e)
    for n, r in enumerate(rows):
        if n in taken or not in_scope(r["date"]):
            continue
        k = (r["date"], r["amount"], r["_norm"], r["status"])
        lst = pool.get(k)
        if lst:
            e = lst.pop(0)
            matched.add(e["id"])
            taken.add(n)
            batch.append({"op": "seen_record", "record": e["id"], "read_id": rid})
            summary["known"] += 1

    # 3. pending → posted
    left_rows = [n for n in range(len(rows)) if n not in taken]
    pend = [e for e in mine if e["id"] not in matched and e["status"] == "pending"]

    def fits(e, r):
        return (r["status"] == "posted" and _sign(e["amount"]) == _sign(r["amount"])
                and abs(r["amount"] - e["amount"]) <= PENDING_TOLERANCE * abs(e["amount"])
                and 0 <= _days(e["date"], r["date"]) <= PENDING_POST_DAYS)
    for e in pend:
        cands = [n for n in left_rows if fits(e, rows[n])]
        if len(cands) != 1:
            continue
        n = cands[0]
        if sum(1 for p in pend if p["id"] not in matched and fits(p, rows[n])) != 1:
            continue
        r = rows[n]
        batch.append({"op": "revise_record", "record": e["id"], "read_id": rid, "reason": "pending_posted",
                      "new": {"date": r["date"], "amount": r["amount"], "description": r["description"],
                              "status": "posted"}})
        matched.add(e["id"])
        taken.add(n)
        left_rows.remove(n)
        summary["revised"] += 1

    # 4. records no longer shown inside the covered interval (complete days only)
    not_shown = []
    for e in mine:
        if e["id"] in matched or not _inside(e["date"], covered) or e["date"] in cut:
            continue
        if e["status"] == "pending":
            if read["state"] == "complete" and covered[1] >= (_d(e["date"]) + _dt.timedelta(days=PENDING_POST_DAYS)).isoformat():
                batch.append({"op": "drop_pending", "record": e["id"], "read_id": rid})
                summary["dropped_pending"] += 1
            continue
        if not e.get("not_shown"):
            batch.append({"op": "flag_not_shown", "record": e["id"], "read_id": rid})
            summary["not_shown"] += 1
        not_shown.append(e)

    # 5. new rows, with their possible counterparts
    others = [e for e in led["records"] if _active(e) and e["source"] != src_id]
    inv = _inventory_of(led, src_id, acc)
    used_ids = {e["id"] for e in led["records"]}
    for n in left_rows:
        r = rows[n]
        new_id = _record_id(src_id, acc, r, used_ids)
        used_ids.add(new_id)
        rec = {"op": "add_record", "id": new_id, "source": src_id, "account": acc, "section": sec, "read_id": rid,
               "date": r["date"], "amount": r["amount"], "unit": unit, "description": r["description"],
               "status": r["status"], "evidence": r["evidence"]}
        if r.get("site_id"):
            rec["site_id"] = r["site_id"]
        batch.append(rec)
        summary["new"] += 1
        if r["status"] != "posted":
            continue
        counterpart = None
        for e in mine:
            if e["id"] in matched or e["status"] != "posted" or _sign(e["amount"]) != _sign(r["amount"]):
                continue
            near = abs(_days(e["date"], r["date"])) <= WINDOW_DAYS and \
                (e["amount"] == r["amount"] or similar(e["description"], r["description"]))
            gone = e in not_shown
            if near or gone:
                counterpart = (e, "within 14 days" if near else "no longer shown in the same interval")
                break
        if counterpart:
            e, why = counterpart
            batch.append({"op": "link_records", "a": e["id"], "b": new_id, "relation": "possibly_same",
                          "basis": f"same account and sign, {why}"})
            summary["possibly_same"] += 1
            continue
        if inv:
            for e in others:
                if e["status"] != "posted" or _inventory_of(led, e["source"], e["account"]) != inv:
                    continue
                if _sign(e["amount"]) == _sign(r["amount"]) and abs(_days(e["date"], r["date"])) <= CROSS_DAYS \
                        and abs(e["amount"] - r["amount"]) <= 0.01 * abs(r["amount"]):
                    batch.append({"op": "link_records", "a": e["id"], "b": new_id, "relation": "probably_same",
                                  "basis": f"same account in {e['source']}, date and amount close"})
                    summary["probably_same_other_source"] += 1
                    break
    return batch, summary


def _inventory_of(led, source_id, account_id):
    s = next((x for x in led["sources"] if x["id"] == source_id), None)
    if not s:
        return None
    a = next((x for x in s["accounts"] if x["id"] == account_id), None)
    return a.get("inventory") if a else None


def _record_id(src, acc, r, used):
    base = f"rec-{fl.sha({'s': src, 'a': acc, 'd': r['date'], 'm': r['amount'], 't': r['description']}, 10)}"
    rid, n = base, 1
    while rid in used:
        n += 1
        rid = f"{base}-{n}"
    return rid


def plan_reads(led, reads):
    """Plan several reads into one batch (one preview per source). Records added earlier in the batch are
    visible to later reads through a working copy of the ledger."""
    import json
    work = json.loads(json.dumps(led))
    batch, summaries = [], []
    for read in reads:
        b, s = plan_read(work, read)
        h, _ = fl.preview_batch(work, b)
        fl.apply_batch(work, b, h)
        batch += b
        summaries.append(s)
    return batch, summaries


# ---------------------------------------------------------------- what the report counts

def counted_records(led):
    """Return (counted, excluded, preliminary_accounts).

    counted: posted, active records the totals use. excluded: {record id: reason}. A «possibly the same» or
    «probably the same» link that is unresolved counts the earlier record (or, across sources, the direct
    source's) and leaves the other out; the account's totals are preliminary until the person decides."""
    recs = {r["id"]: r for r in led["records"]}
    excluded = {}
    prelim = set()
    for r in recs.values():
        if r["status"] != "posted":
            excluded[r["id"]] = "pending"
        elif r.get("state") == "dropped":
            excluded[r["id"]] = "pending row that never posted"
        elif r.get("state") == "no_longer_shown":
            excluded[r["id"]] = "no longer shown (you confirmed)"
        elif r.get("not_shown") and not r["not_shown"].get("decision"):
            prelim.add((r["source"], r["account"]))
    kinds = {s["id"]: s["kind"] for s in led["sources"]}
    for ev in led["events"]:
        if ev.get("kind") != "link":
            continue
        a, b = (recs.get(x) for x in ev["records"])
        if not a or not b:
            continue
        if ev["state"] == "different":
            continue
        if ev["relation"] == "probably_same":
            # count the direct source's row, never the aggregator's
            keep, drop = (a, b) if kinds.get(b["source"]) == "aggregator" or kinds.get(a["source"]) != "aggregator" \
                else (b, a)
        elif ev["state"] == "same":
            # the person said one event: count the row the site still shows (its corrected value)
            gone = [x for x in (a, b) if x.get("state") == "no_longer_shown" or x.get("not_shown")]
            if len(gone) == 1:
                drop = gone[0]
                keep = b if drop is a else a
            else:
                keep, drop = (b, a) if a.get("added_at", "") <= b.get("added_at", "") else (a, b)
        else:
            # undecided: the earlier record stays counted, the new one waits (spec v2, appendix C)
            keep, drop = (a, b) if a.get("added_at", "") <= b.get("added_at", "") else (b, a)
        excluded.setdefault(drop["id"], "same event as " + keep["id"] if ev["state"] == "same"
                            else "possibly the same as " + keep["id"] + " (you have not decided)")
        if ev["state"] == "unresolved":
            prelim.add((drop["source"], drop["account"]))
            prelim.add((keep["source"], keep["account"]))
    counted = [r for r in recs.values() if r["id"] not in excluded]
    return counted, excluded, prelim


def coverage_state(led, source_id, account_id, section):
    """The latest coverage of an account section, or None."""
    s = next((x for x in led["sources"] if x["id"] == source_id), None)
    if not s:
        return None
    covs = [c for c in s["coverage"] if c["account"] == account_id and c["section"] == section]
    return covs[-1] if covs else None
