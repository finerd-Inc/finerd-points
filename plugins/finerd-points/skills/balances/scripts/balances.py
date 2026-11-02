#!/usr/bin/env python3
"""Points and miles balances with a date and a source next to every number.

Usage:
  balances.py --ledger L [--today YYYY-MM-DD] [--format json|md]
  balances.py --ledger L --input observed.json --proposals batch.json   # propose new observations

Input file `finerd-points/balances@1`:
{"contract": "finerd-points/balances@1", "source": {"app": "finerd"},
 "balances": [{"account_id": "<finance app account id>" | null, "program": "Hyatt",
               "amount": 123456, "unit": "points", "as_of": "YYYY-MM-DD",
               "kind": "verified" | "computed" | "statement" | "program_page" | "person",
               "note": null}]}
A balance is matched to a ledger account by its finance-app account id, else by program name.
Unknown is never zero: an account without any observation shows «unknown».
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpledger as fl  # noqa: E402

KIND_TO_SOURCE = {"verified": "finance_app", "computed": "finance_app", "statement": "statement",
                  "program_page": "program_page", "program_api": "program_api", "email": "email",
                  "awardwallet": "awardwallet", "person": "person"}


def table(led, today):
    stale_days = led["_meta"]["settings"].get("stale_after_days", 30)
    obs = fl.active_observations(led)
    rows = []
    for acc in led["accounts"]:
        cur = fl.current(led, f"account:{acc['id']}", "balance", obs)
        exp = fl.current(led, f"account:{acc['id']}", "expires_on", obs)
        row = {"account": acc["id"], "nickname": acc["nickname"], "program": acc["program"], "unit": acc["unit"],
               "person": acc.get("person"), "balance": None, "as_of": None, "source": None, "state": "unknown",
               "expires_on": exp["value"] if exp else None, "conflicts": []}
        if cur:
            age = (today - dt.date.fromisoformat(cur["as_of"])).days
            row.update({"balance": cur["value"], "as_of": cur["as_of"], "source": cur["source"],
                        "confidence": cur["confidence"], "age_days": age,
                        "state": "stale" if age > stale_days else "current",
                        "conflicts": cur["conflicts"]})
        rows.append(row)
    return {"as_of": today.isoformat(), "accounts": rows,
            "unknown": [r["nickname"] for r in rows if r["state"] == "unknown"],
            "stale": [r["nickname"] for r in rows if r["state"] == "stale"]}


def propose(led, data):
    if not isinstance(data, dict) or data.get("contract") != "finerd-points/balances@1":
        raise SystemExit(json.dumps({"refused": 'The input must be {"contract": "finerd-points/balances@1", '
                                            '"source": {"app": …}, "balances": [ … ]}.'}))
    app = (data.get("source") or {}).get("app")
    by_link = {(a.get("finance_link") or {}).get("account_id"): a for a in led["accounts"]
               if (a.get("finance_link") or {}).get("account_id")}
    by_prog = {}
    norm = lambda x: re.sub(r"[^a-z0-9]+", "", (x or "").lower())  # noqa: E731
    for a in led["accounts"]:
        for key in {norm(a["program"]), norm(a["nickname"])}:
            by_prog.setdefault(key, []).append(a)
    existing = {(o["subject"], o["field"], o["as_of"], json.dumps(o["value"])) for o in fl.active_observations(led)}
    ops, unmatched = [], []
    for b in data["balances"]:
        acc = by_link.get(b.get("account_id"))
        if acc is None:
            cands = by_prog.get(norm(b.get("program")), []) or by_prog.get(norm(b.get("program_id")), [])
            acc = cands[0] if len(cands) == 1 else None
        if acc is None:
            unmatched.append(b)
            continue
        subj = f"account:{acc['id']}"
        key = (subj, "balance", b["as_of"], json.dumps(b["amount"]))
        if key in existing:
            continue
        ops.append({"op": "observe", "subject": subj, "field": "balance", "value": b["amount"],
                    "unit": b.get("unit") or acc["unit"], "as_of": b["as_of"],
                    "source": {"kind": KIND_TO_SOURCE.get(b.get("kind"), "person"), "name": app,
                               "ref": b.get("account_id")},
                    "confidence": "confirmed" if b.get("kind") in ("verified", "program_page", "program_api",
                                                                   "statement") else "likely",
                    "method": f"{b.get('kind')} balance", "note": b.get("note")})
    return ops, unmatched


def to_markdown(t):
    out = [f"**Balances** (as of {t['as_of']})", "", "| Program | Balance | As of | Source | Note |",
           "|---|---:|---|---|---|"]
    for r in t["accounts"]:
        bal = "unknown" if r["balance"] is None else f"{r['balance']:,} {r['unit']}"
        src = "" if not r["source"] else (r["source"].get("name") or r["source"]["kind"])
        note = []
        if r["state"] == "stale":
            note.append(f"{r['age_days']} days old")
        if r["conflicts"]:
            note.append("sources disagree: " + ", ".join(f"{c['value']:,} ({c['source'].get('name') or c['source']['kind']})"
                                                         for c in r["conflicts"]))
        if r["expires_on"]:
            note.append(f"expires {r['expires_on']}")
        out.append(f"| {r['nickname']} | {bal} | {r['as_of'] or '—'} | {src} | {'; '.join(note)} |")
    out.append("")
    out.append(f"{len(t['accounts'])} programs; {len(t['stale'])} stale, {len(t['unknown'])} unknown. Balances of "
               f"different programs are not added up: a point in one program is not a point in another, and "
               f"points are not money, so they never enter net worth.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--today")
    ap.add_argument("--input")
    ap.add_argument("--proposals")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    try:
        led = fl.load(a.ledger)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    if a.input:
        ops, unmatched = propose(led, json.loads(Path(a.input).read_text(encoding="utf-8")))
        if a.proposals:
            Path(a.proposals).write_text(json.dumps(ops, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"proposed": len(ops), "unmatched": unmatched}, indent=1, ensure_ascii=False))
        return
    t = table(led, today)
    print(to_markdown(t) if a.format == "md" else json.dumps(t, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
