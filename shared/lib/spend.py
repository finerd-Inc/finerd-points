#!/usr/bin/env python3
"""Card spend for a year, split personal/business, with the person's exclusions — the input
for foregone cash back in the Year in Review.

Usage:
  spend.py --ledger L --transactions T.json [T2.json …] --year 2025 [--facts DIR] > spend.json

Purchases are debits of kind «purchase» on each linked card; merchant refunds on the same card
are subtracted. A purchase is excluded when one of the ledger's foregone_cashback_exclusions
words (for example «rent», «amazon») appears as a whole word in its description, merchant or
category. A card's segment comes from the facts catalog (personal or business). Needs every
transaction of the year for each card (not a filtered search); a card whose transactions do not
cover the whole year is reported as partial.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import credits as cr  # noqa: E402
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402


def summarize(led, catalog, accounts, txns, year):
    words = [w for w in (led["_meta"]["settings"].get("foregone_cashback_exclusions") or []) if w]
    rx = [re.compile(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])") for w in words]
    report = led["_meta"]["setup"]["report_currency"]
    out = {"year": year, "personal": {"spend": 0.0, "excluded": 0.0}, "business": {"spend": 0.0, "excluded": 0.0},
           "by_card": [], "notes": []}
    ys, ye = dt.date(year, 1, 1), dt.date(year, 12, 31)
    for card in led["cards"]:
        link = card.get("finance_link") or {}
        acc = accounts.get(link.get("account_id"))
        if not acc:
            if card.get("opened_on") and card["opened_on"][:4] > str(year):
                continue
            out["notes"].append(f"{card['nickname']}: no transactions supplied; its spend is not included.")
            continue
        if card.get("opened_on") and card["opened_on"][:4] > str(year):
            continue  # opened after this year: no spend to count
        if acc.get("scope") != "all":
            out["notes"].append(f"{card['nickname']}: the supplied transactions are a filtered search, not every "
                                f"transaction of {year}; its spend is not counted. Fetch all transactions "
                                f"(normalize.py finerd --all-transactions) or use a CSV export.")
            continue
        seg = (catalog["cards"].get(card.get("catalog_ref") or "") or {}).get("segment", "personal")
        spend = excluded = 0.0
        foreign = 0
        for t in txns:
            if t["account_id"] != link["account_id"] or not t["date"].startswith(str(year)) or t.get("pending"):
                continue
            if t["currency"] != report:
                foreign += 1
                continue
            text = " ".join(str(t.get(k) or "") for k in ("description", "merchant", "category")).lower()
            sign = 1 if (t["direction"] == "debit" and t["kind"] == "purchase") else \
                -1 if (t["direction"] == "credit" and t["kind"] == "refund") else 0
            if not sign:
                continue
            spend += sign * t["amount"]
            if any(r.search(text) for r in rx):
                excluded += sign * t["amount"]
        cov = cr.coverage_state(acc, ys, ye)
        out[seg]["spend"] += spend
        out[seg]["excluded"] += excluded
        out["by_card"].append({"card": card["id"], "segment": seg, "spend": round(spend, 2),
                               "excluded": round(excluded, 2), "coverage": cov})
        if cov != "full":
            out["notes"].append(f"{card['nickname']}: transactions do not cover all of {year}; spend is partial.")
        if foreign:
            out["notes"].append(f"{card['nickname']}: {foreign} transactions not in {report} were left out.")
    for seg in ("personal", "business"):
        out[seg] = {k: round(v, 2) for k, v in out[seg].items()}
    out["exclusions"] = words
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--transactions", nargs="+", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--facts")
    a = ap.parse_args()
    try:
        led = fl.load(a.ledger)
        accounts, txns = cr.load_txns(a.transactions)
        res = summarize(led, ff.load_catalog(a.facts), accounts, txns, a.year)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
