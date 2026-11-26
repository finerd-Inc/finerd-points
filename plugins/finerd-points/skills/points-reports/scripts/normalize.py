#!/usr/bin/env python3
"""Turn a connector's transaction output into the normalized transaction contract.

Contract (spec appendix D), file `finerd-points/transactions@1`:
{
  "contract": "finerd-points/transactions@1",
  "source": {"app": "finerd", "fetched_at": "…"},
  "accounts": [{"account_id", "name", "coverage": {"from", "to"}, "complete": bool,
                "coverage_note": str|null}],
  "transactions": [{"id", "account_id", "date", "posted_date", "amount" (>0), "currency",
                    "direction": "credit"|"debit", "kind": purchase|credit|refund|payment|transfer|fee|noncash|other,
                    "description", "merchant", "category", "pending", "reversal_of"}]
}
`direction` is relative to the card or bank account: debit = money spent on the card,
credit = money back onto the card (statement credit, refund, payment).

Usage:
  normalize.py finerd --account-name "AmEx Gold" --account-id <uuid> --from 2026-01-01 --to 2026-11-02 \
      raw1.json [raw2.json …] > amex-gold.txns.json
  normalize.py csv --file export.csv --account-name "Gold" --date-col Date --desc-col Description \
      --amount-col Amount --negative-is debit|credit --from … --to … > gold.txns.json
  normalize.py merge a.json b.json > all.json

The raw finerd file is the JSON the finerd MCP `search_transactions` tool returned
(either the tool's {"result": "<json string>"} wrapper or the inner object).
Only the fields above are kept; nothing else from the source is copied.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

CONTRACT = "finerd-points/transactions@1"
FEE_RE = re.compile(r"(?i)\b(annual|membership)\s+fee\b")
REVERSAL_RE = re.compile(r"(?i)\b(reversal|reversed|adj(ustment)?|clawback)\b")
# Entries finerd points itself recorded in a finance app (a trip paid with points…) carry this marker.
# Read back, they are never cash spending, a credit or a second redemption (spec v2, app skills).
MARKER_RE = re.compile(r"\[finerd points (op|c)-?[0-9a-f-]+")


def _date(s):
    return s[:10] if s else None


def _load_finerd(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("result"), str):
        raw = json.loads(raw["result"])
    if isinstance(raw, list):
        return {"transactions": raw, "complete": True}
    return raw


def from_finerd(paths, account_name, account_id, date_from, date_to, covered_from=None, all_txns=False):
    txns, pages = [], []
    for p in paths:
        page = _load_finerd(p)
        txns.extend(page.get("transactions", []))
        pages.append(page)
    # Each search must end on a page that says there is nothing more. Files are read in order; a page
    # numbered n > 0 continues the search of the file before it. A page without pagination fields
    # counts as complete only if it says so itself.
    def done(pg):
        return (not pg["has_more"]) if "has_more" in pg else pg.get("complete") is True
    complete, i = bool(pages), 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and isinstance(pages[j + 1].get("page"), int) and pages[j + 1]["page"] > 0:
            j += 1
        complete = complete and done(pages[j])
        i = j + 1
    names = sorted({j.get("account") for t in txns for j in t.get("journals", []) if j.get("account")})
    if txns and not any(account_name in [j.get("account") for j in t.get("journals", [])] for t in txns):
        raise SystemExit(json.dumps({"refused": f"No transaction in these files belongs to an account named "
                                                f"«{account_name}». Use the card's finance_link.account_name exactly. "
                                                f"Accounts seen: {', '.join(names[:20])}"}))
    latest = {}
    for t in txns:  # the posted copy of a transaction replaces its pending copy
        if t["id"] not in latest or (latest[t["id"]].get("pending") and not t.get("pending")):
            latest[t["id"]] = t
    txns = list(latest.values())
    out, seen = [], set()
    for t in txns:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        frm = [j["account"] for j in t.get("journals", []) if j.get("type") == "FROM"]
        to = [j["account"] for j in t.get("journals", []) if j.get("type") == "TO"]
        if account_name in frm:
            direction, other = "debit", (to[0] if to else None)
        elif account_name in to:
            direction, other = "credit", (frm[0] if frm else None)
        else:
            continue
        ftype = (t.get("type") or "").upper()
        desc = t.get("description") or ""
        marked = MARKER_RE.search(desc) or MARKER_RE.search(str(t.get("comment") or ""))
        if marked:
            kind = "noncash"
        elif FEE_RE.search(desc) and direction == "debit":
            kind = "fee"
        elif direction == "debit":
            kind = "transfer" if ftype == "TRANSFER" else "purchase"
        elif ftype == "INCOME":
            kind = "credit"
        elif ftype == "TRANSFER":
            kind = "payment"
        elif ftype in ("REFUND", "EXPENSE"):
            kind = "refund"
        else:
            kind = "other"
        out.append({
            "id": t["id"], "account_id": account_id, "date": _date(t.get("date")),
            "posted_date": _date(t.get("posted_date")), "amount": abs(float(t.get("amount", 0))),
            "currency": t.get("currency") or "USD", "direction": direction, "kind": kind,
            "description": desc, "merchant": t.get("merchant"), "category": other,
            "pending": bool(t.get("pending")), "reversal_of": None,
            "reversal_hint": bool(REVERSAL_RE.search(desc)),
        })
    acc = _account(account_id, account_name, date_from, date_to, complete, out, covered_from=covered_from,
                   infer=all_txns)
    acc["scope"] = "all" if all_txns else "filtered"  # spend.py needs every transaction, not a search
    return _wrap("finerd", [acc], out)


def from_csv(path, account_name, date_col, desc_col, amount_col, negative_is, date_from, date_to,
             currency="USD", date_format=None):
    out, seen_rows = [], {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            raw_amt = (row.get(amount_col) or "0").replace("$", "").replace(",", "").strip()
            if raw_amt.startswith("(") and raw_amt.endswith(")"):
                raw_amt = "-" + raw_amt[1:-1]
            amt = float(raw_amt or 0)
            neg_dir = negative_is
            pos_dir = "credit" if negative_is == "debit" else "debit"
            direction = neg_dir if amt < 0 else pos_dir
            d = row.get(date_col, "").strip()
            if date_format:
                d = dt.datetime.strptime(d, date_format).date().isoformat()
            desc = row.get(desc_col, "")
            up = desc.upper()
            if MARKER_RE.search(desc):
                kind = "noncash"
            elif direction == "debit":
                kind = "fee" if FEE_RE.search(desc) else "purchase"
            elif "PAYMENT" in up or "AUTOPAY" in up or "THANK YOU" in up:
                kind = "payment"
            elif "CREDIT" in up and not re.search(r"\b(REFUND|RETURN)", up):
                kind = "credit"
            else:
                kind = "refund"  # money back that does not say «credit» is a merchant refund
            # The same row in overlapping exports gets the same id; identical rows on one day are numbered.
            sig = (d[:10], desc.strip().upper(), round(amt, 2))
            seen_rows[sig] = seen_rows.get(sig, 0) + 1
            digest = hashlib.sha256(repr((account_name, sig, seen_rows[sig])).encode()).hexdigest()[:12]
            out.append({"id": f"csv-{digest}", "account_id": account_name, "date": d[:10], "posted_date": None,
                        "amount": abs(amt), "currency": currency, "direction": direction, "kind": kind,
                        "description": desc, "merchant": None, "category": None, "pending": False,
                        "reversal_of": None, "reversal_hint": bool(REVERSAL_RE.search(desc))})
    acc = _account(account_name, account_name, date_from, date_to, True, out)
    acc["scope"] = "all"  # an export holds every transaction of its dates
    return _wrap("csv", [acc], out)


def _account(account_id, name, date_from, date_to, complete, txns, covered_from=None, infer=True):
    note = None
    cov_from = date_from
    dates = sorted(t["date"] for t in txns if t["date"])
    if covered_from:
        # The oldest transaction the app holds for this account (asked separately), so a
        # filtered search (credits only) still says which periods the app really covers.
        cov_from = max(date_from or covered_from, covered_from)
        if cov_from != date_from:
            note = f"The app has transactions for this account only from {covered_from}."
        return {"account_id": account_id, "name": name, "coverage": {"from": cov_from, "to": date_to},
                "complete": complete, "coverage_note": note}
    if not infer:
        return {"account_id": account_id, "name": name, "coverage": {"from": None, "to": None},
                "complete": complete,
                "coverage_note": "Coverage unknown: pass --covered-from (oldest transaction date) or --all-transactions."}
    if dates and date_from:
        first = dt.date.fromisoformat(dates[0])
        if (first - dt.date.fromisoformat(date_from)).days > 31:
            cov_from = dates[0]
            note = (f"No transactions before {dates[0]} although {date_from} was requested; "
                    f"treating coverage as starting {dates[0]}.")
    if not dates:
        note = "No transactions in the requested window; coverage unknown."
        cov_from = None
    return {"account_id": account_id, "name": name,
            "coverage": {"from": cov_from, "to": date_to if dates else None},
            "complete": complete, "coverage_note": note}


def _wrap(app, accounts, txns):
    return {"contract": CONTRACT,
            "source": {"app": app, "fetched_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()},
            "accounts": accounts, "transactions": txns}


def merge(paths):
    accounts, txns, apps = [], [], set()
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if d.get("contract") != CONTRACT:
            raise SystemExit(f"{p} is not a {CONTRACT} file")
        apps.add(d["source"]["app"])
        accounts += d["accounts"]
        txns += d["transactions"]
    return _wrap("+".join(sorted(apps)), accounts, txns)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("finerd")
    s.add_argument("--account-name", required=True)
    s.add_argument("--account-id", required=True)
    s.add_argument("--from", dest="date_from", required=True)
    s.add_argument("--to", dest="date_to", required=True)
    s.add_argument("--covered-from", help="oldest transaction date the app holds for this account")
    s.add_argument("--all-transactions", action="store_true",
                   help="the files hold every transaction of the window (not a filtered search)")
    s.add_argument("files", nargs="+")
    s = sub.add_parser("csv")
    s.add_argument("--file", required=True)
    s.add_argument("--account-name", required=True)
    s.add_argument("--date-col", required=True)
    s.add_argument("--desc-col", required=True)
    s.add_argument("--amount-col", required=True)
    s.add_argument("--negative-is", choices=["debit", "credit"], required=True)
    s.add_argument("--currency", default="USD")
    s.add_argument("--date-format")
    s.add_argument("--from", dest="date_from")
    s.add_argument("--to", dest="date_to")
    s = sub.add_parser("merge")
    s.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd == "finerd":
        res = from_finerd(a.files, a.account_name, a.account_id, a.date_from, a.date_to,
                          a.covered_from, a.all_transactions)
    elif a.cmd == "csv":
        res = from_csv(a.file, a.account_name, a.date_col, a.desc_col, a.amount_col, a.negative_is,
                       a.date_from, a.date_to, a.currency, a.date_format)
    else:
        res = merge(a.files)
    json.dump(res, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
