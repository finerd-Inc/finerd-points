#!/usr/bin/env python3
"""Acceptance check for goal item 3 (spec v2, «How we know it works», items 2–3).

Compares what a collection run put in the ledger with a reference captured separately from the
sites, against the same cutoff. Its own normalization (frozen here, independent of fpcollect's
identity rules): date as YYYY-MM-DD; signed amount rounded to the site's precision; description
case-folded, accents kept, everything but letters and digits removed, spaces collapsed.

Reference file (JSON):
{"cutoff": "2026-11-20T18:00:00Z",
 "accounts": [{"source": "hyatt", "account": "woh", "section": "activity", "interval": ["2025-01-01", "2026-11-20"],
               "precision": 0, "balance": {"subject": "account:inv-hyatt", "value": 52310},
               "rows": [["2026-10-05", 5000, "Stay at Park Hyatt"], …],
               "excluded": null}]}             # or {"reason": "…"} — frozen before the run

  acceptance_compare.py --ledger <folder>/ledger.json --reference reference.json
Exit 0 only when every non-excluded account passes.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import fpcollect as fc  # noqa: E402
import fpledger as fl  # noqa: E402


def norm(text):
    t = unicodedata.normalize("NFKC", str(text or "")).casefold()
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


def key(date, amount, desc, precision):
    return (date[:10], round(float(amount), precision), norm(desc))


def compare(led, ref):
    counted, _, prelim = fc.counted_records(led)
    out, ok = [], True
    for acc in ref["accounts"]:
        name = f"{acc['source']}/{acc['account']}/{acc.get('section', 'activity')}"
        if acc.get("excluded"):
            out.append({"account": name, "result": "excluded", "reason": acc["excluded"].get("reason")})
            continue
        res = {"account": name, "problems": []}
        lo, hi = acc["interval"]
        p = acc.get("precision", 0)
        got = Counter(key(r["date"], r["amount"], r["description"], p) for r in counted
                      if r["source"] == acc["source"] and r["account"] == acc["account"]
                      and r["section"] == acc.get("section", "activity") and lo <= r["date"] <= hi)
        want = Counter(key(d, a, t, p) for d, a, t in acc.get("rows", []))
        missing, extra = want - got, got - want
        if missing:
            res["problems"].append({"missing_rows": sorted(missing.elements())})
        if extra:
            res["problems"].append({"extra_rows": sorted(extra.elements())})
        cov = fc.coverage_state(led, acc["source"], acc["account"], acc.get("section", "activity"))
        if acc.get("rows") is not None and (not cov or cov["state"] != "complete"):
            res["problems"].append({"coverage": cov["state"] if cov else "none"})
        if (acc["source"], acc["account"]) in prelim:
            res["problems"].append({"preliminary": "rows wait for the person's decision"})
        if acc.get("balance"):
            b = acc["balance"]
            direct = [o for o in fl.active_observations(led)
                      if o["source"].get("kind") not in ("awardwallet", "aggregator")]  # as the report does
            cur = fl.current(led, b["subject"], b.get("field", "balance"), direct)
            if cur is None or round(float(cur["value"]), p) != round(float(b["value"]), p):
                res["problems"].append({"balance": {"ledger": cur["value"] if cur else None, "site": b["value"]}})
        res["result"] = "pass" if not res["problems"] else "fail"
        ok = ok and res["result"] == "pass"
        out.append(res)
    return ok, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--reference", required=True)
    a = ap.parse_args()
    led = fl.load(a.ledger)
    ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))
    ok, out = compare(led, ref)
    print(json.dumps({"pass": ok, "cutoff": ref.get("cutoff"), "accounts": out}, indent=1, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
