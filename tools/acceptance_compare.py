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


def match_rows(want, got):
    """Largest one-to-one matching of reference rows to ledger rows (frozen 16 Nov 2026, before run 1).

    A reference row is ([first, last], amount, name): the date the site shows, or the range it shows
    for a stay. A ledger row matches when its amount is equal at the site's precision, its date lies in
    that range, and the site's name (normalized) is part of its description; a reference row with no
    name (the site shows only an amount) matches any description. Rows with a zero amount are left out
    on both sides by the caller."""
    def fits(w, g):
        (lo, hi), amount, name = w
        return g[1] == amount and lo <= g[0] <= hi and (not name or name in g[2])

    owner = [None] * len(got)

    def assign(i, seen):
        for j, g in enumerate(got):
            if j in seen or not fits(want[i], g):
                continue
            seen.add(j)
            if owner[j] is None or assign(owner[j], seen):
                owner[j] = i
                return True
        return False

    matched = {i for i in range(len(want)) if assign(i, set())}
    missing = sorted([w[0][0] if w[0][0] == w[0][1] else "..".join(w[0]), w[1], w[2]]
                     for i, w in enumerate(want) if i not in matched)
    extra = sorted(list(g) for j, g in enumerate(got) if owner[j] is None)
    wording = sorted([got[j][0], got[j][1], got[j][2], want[i][2]] for j, i in enumerate(owner)
                     if i is not None and want[i][2] and got[j][2] != want[i][2])
    return missing, extra, wording


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
        got = [key(r["date"], r["amount"], r["description"], p) for r in counted
               if r["source"] == acc["source"] and r["account"] == acc["account"]
               and r["section"] == acc.get("section", "activity") and lo <= r["date"] <= hi
               and round(float(r["amount"]), p) != 0]
        want = [(d if isinstance(d, list) else [d, d], round(float(a), p), norm(t))
                for d, a, t in acc.get("rows", []) if round(float(a), p) != 0]
        missing, extra, wording = match_rows(want, got)
        if missing:
            res["problems"].append({"missing_rows": missing})
        if extra:
            res["problems"].append({"extra_rows": extra})
        if wording:
            res["wording_differs"] = wording   # information only: the site's name is inside the description
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
