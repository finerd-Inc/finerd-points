#!/usr/bin/env python3
"""Year in Review by Rad's points-accounting method (framework v1.2, §5.1).

Usage:
  yir.py --ledger L --year 2025 [--spend spend.json] [--credits credits.json]
         [--compare sheet.json] [--format json|md]

Formula (year-in-review-formula.md):
  cash avoided   = Σ over the year's redemptions (fallback − fees)
  value redeemed = Σ over the year's redemptions (normalized − fees)
  costs          = purchased points + services/tools + annual fees + cancellation fees
                   + foregone cash back (rate × card spend − exclusions; personal and business apart)
  net (fallback) = cash avoided − costs;  net (value) = value redeemed − costs
Rules: a redemption counts in the year it was booked; transfers are movement, not income;
a fully refunded cancellation is removed, an unrefunded fee is a cost; purchased points are a
cost in the year of purchase and are never subtracted from a redemption's value (P1);
unredeemed points are not part of the result. Card credits are a separate line, so the
result is shown with and without them.

spend.json: {"personal": {"spend": 150000, "excluded": 20000}, "business": {"spend": 250000, "excluded": 0}}
compare (sheet.json): {"cash_avoided": …, "value_redeemed": …, "points_purchased": …, "tools": …,
                       "annual_fees": …, "foregone_cashback": …, "net_fallback": …, "net_value": …}
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpledger as fl  # noqa: E402


def _in_year(d, year):
    return str(d or "").startswith(str(year))


def _fx(rec, report):
    """Rate that turns this record's amounts into the report currency (1 when already in it)."""
    cur = rec.get("currency") or report
    if cur == report:
        return 1.0, None
    if rec.get("fx_rate"):
        return float(rec["fx_rate"]), None
    return None, f"{rec['id']}: amounts in {cur} have no rate to {report}; left out until a rate is added"


def credits_value(credits_json, settings):
    """Credits used in the year, each valued at what the person says it is really worth to them
    (settings.credit_values {"<card>/<benefit>": fraction}; face value when not set)."""
    if not credits_json:
        return None, []
    overrides = settings.get("credit_values") or {}
    total, lines = 0.0, []
    for c in credits_json.get("cards", []):
        for b in c.get("benefits", []):
            if b.get("counted_on_card"):
                continue
            used = (b.get("year_to_date") or {}).get("used") or 0
            if not used:
                continue
            # A pooled (shared) allowance is valued per card that actually used it.
            parts = b.get("pooled_used") or {c["card"]: used}
            scale = used / (sum(parts.values()) or used)
            for card_id, part in parts.items():
                if not part:
                    continue
                frac = overrides.get(f"{card_id}/{b['benefit']}", 1.0)
                total += part * scale * frac
                lines.append({"card": card_id, "benefit": b["benefit"], "name": b["name"], "used": round(part * scale, 2),
                              "value_fraction": frac, "value": round(part * scale * frac, 2)})
    return round(total, 2), lines


def compute(led, year, spend=None, credits_used=None, rate=None, credit_lines=None):
    s = led["_meta"]["settings"]
    report = led["_meta"]["setup"]["report_currency"]
    rate = s.get("foregone_cashback_rate") if rate is None else rate
    reds, cancelled, notes, problems = [], [], [], []
    cash_avoided = value_redeemed = 0.0
    missing_values = []
    for r in led["redemptions"]:
        if not _in_year(r["booked_on"], year):
            continue
        if r["status"] in ("cancelled", "cancelled_with_fee"):
            cancelled.append(r["id"])
            continue
        fx, why = _fx(r, report)
        if fx is None:
            problems.append(why)
            continue
        fb = None if r.get("fallback") is None else r["fallback"] * fx
        nv = None if r.get("normalized") is None else r["normalized"] * fx
        fees = r["fees"] * fx
        if fb is None or nv is None:
            missing_values.append(r["id"])
        ca = (fb - fees) if fb is not None else None
        vr = (nv - fees) if nv is not None else None
        cash_avoided += ca or 0
        value_redeemed += vr or 0
        reds.append({"id": r["id"], "booked_on": r["booked_on"], "program": r["program"], "points": r["points"],
                     "fees": round(fees, 2), "fallback": fb, "normalized": nv, "cash_avoided": ca, "value_redeemed": vr,
                     "description": r.get("description"), "fx_rate": None if fx == 1.0 else fx,
                     "purchased_points_cost": r.get("purchased_points_cost")})
        if r.get("purchased_points_cost"):
            by = int(r["booked_on"][:4])
            bought = [c for c in led["costs"] if c["kind"] == "points_purchase" and c["date"][:4] in (str(by), str(by - 1))]
            if bought:
                notes.append(f"{r['id']}: ${r['purchased_points_cost']:,.0f} of purchased points is a cost in the year of "
                             f"purchase (recorded as a points purchase) and is not subtracted from this redemption's "
                             f"value (rule 4).")
            else:
                problems.append(f"{r['id']}: says ${r['purchased_points_cost']:,.0f} of purchased points were used, but no "
                                f"points purchase is recorded as a cost; add it (add_cost kind points_purchase) so it "
                                f"counts once, in the year it was bought.")
    costs = {"points_purchased": 0.0, "tools": 0.0, "annual_fees": 0.0, "cancellation_fees": 0.0, "other": 0.0}
    kind_map = {"points_purchase": "points_purchased", "tool": "tools", "annual_fee": "annual_fees",
                "cancellation_fee": "cancellation_fees", "other": "other"}
    for c in led["costs"]:
        if _in_year(c["date"], year):
            fx, why = _fx(c, report)
            if fx is None:
                problems.append(why)
                continue
            costs[kind_map[c["kind"]]] += float(c["amount"]) * fx
    # A cancellation fee recorded on the redemption counts in the year it was charged (cancelled_on).
    for r in led["redemptions"]:
        if r["status"] != "cancelled_with_fee":
            continue
        if not r.get("cancelled_on") and r["booked_on"][:4] < str(year):
            problems.append(f"{r['id']}: a cancellation fee without a cancellation date; it may belong to {year}. "
                            f"Add cancelled_on.")
            continue
        when = r.get("cancelled_on") or r["booked_on"]
        if not _in_year(when, year):
            continue
        if any(c["kind"] == "cancellation_fee" and c.get("redemption") == r["id"] for c in led["costs"]):
            continue
        fx, why = _fx(r, report)
        if fx is None:
            problems.append(why)
            continue
        costs["cancellation_fees"] += float(r.get("cancellation_fee") or 0) * fx
        if not r.get("cancelled_on"):
            problems.append(f"{r['id']}: no cancellation date recorded; its fee is counted in the booking year "
                            f"until cancelled_on is added.")
    fee_cards = {c.get("card") for c in led["costs"] if c["kind"] == "annual_fee" and _in_year(c["date"], year)}
    for card in led["cards"]:
        opened = card.get("opened_on")
        if card.get("catalog_ref") and card["id"] not in fee_cards and not (opened and opened[:4] > str(year)):
            notes.append(f"No annual fee is recorded for {card['nickname']} in {year}. If it was charged, add it "
                         f"(the card-credits proposals include fees found in transactions).")
    foregone = {"personal": 0.0, "business": 0.0}
    for note in (spend or {}).get("notes", []):
        problems.append(f"Card spend: {note}")
    if spend and rate is not None:
        for seg in ("personal", "business"):
            seg_s = spend.get(seg) or {}
            base = float(seg_s.get("spend", 0)) - float(seg_s.get("excluded", 0))
            foregone[seg] = round(rate * max(base, 0), 2)
    elif rate is None:
        problems.append("Foregone cash back is not counted: set your cash-back rate (for example 2%) first.")
    else:
        problems.append("Foregone cash back is not counted: card spend for the year is missing.")
    if missing_values:
        problems.append(f"{len(missing_values)} redemptions have no fallback or normalized price "
                        f"({', '.join(missing_values)}); they count as zero until the prices are added.")
    total_costs = sum(costs.values()) + foregone["personal"] + foregone["business"]
    res = {
        "year": year, "currency": report, "complete": not problems, "problems": problems,
        "redemptions": reds, "cancelled_removed": cancelled,
        "income": {"cash_avoided": round(cash_avoided, 2), "value_redeemed": round(value_redeemed, 2)},
        "costs": {**{k: round(v, 2) for k, v in costs.items()},
                  "foregone_cashback": round(foregone["personal"] + foregone["business"], 2),
                  "foregone_cashback_split": foregone, "total": round(total_costs, 2)},
        "net_fallback": round(cash_avoided - total_costs, 2),
        "net_value": round(value_redeemed - total_costs, 2),
        "credits_used": credits_used, "credit_lines": credit_lines or [],
        "notes": notes, "missing_values": missing_values,
        "settings": {"foregone_cashback_rate": rate, "exclusions": s.get("foregone_cashback_exclusions")},
    }
    if credits_used is not None:
        res["with_credits"] = {"net_fallback": round(res["net_fallback"] + credits_used, 2),
                               "net_value": round(res["net_value"] + credits_used, 2)}
    return res


def compare(res, sheet):
    lines = [
        ("Cash avoided", res["income"]["cash_avoided"], sheet.get("cash_avoided")),
        ("Value redeemed", res["income"]["value_redeemed"], sheet.get("value_redeemed")),
        ("Purchased points", res["costs"]["points_purchased"], sheet.get("points_purchased")),
        ("Services and tools", res["costs"]["tools"], sheet.get("tools")),
        ("Annual fees", res["costs"]["annual_fees"], sheet.get("annual_fees")),
        ("Foregone cash back", res["costs"]["foregone_cashback"], sheet.get("foregone_cashback")),
        ("Net (fallback)", res["net_fallback"], sheet.get("net_fallback")),
        ("Net (value)", res["net_value"], sheet.get("net_value")),
    ]
    rows = [{"line": n, "recomputed": a, "sheet": b, "difference": None if b is None else round(a - b, 2),
             "explanation": None} for n, a, b in lines]
    bought = sum(r.get("purchased_points_cost") or 0 for r in res["redemptions"])
    for r in rows:
        d = r["difference"]
        if d is None or abs(d) < 0.5:
            continue
        if r["line"] == "Value redeemed" and bought and abs(d - bought) < 1:
            r["explanation"] = (f"The sheet subtracts ${bought:,.0f} of purchased points from redemption value; "
                                f"rule 4 counts purchased points once, as a cost in the year of purchase.")
        elif abs(d) <= 1:
            r["explanation"] = "Rounding of individual lines."
    return rows


def to_markdown(res, cmp=None):
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(res.get("currency", "USD"), res.get("currency", "") + " ")
    m = lambda v: "—" if v is None else (f"−{sym}{-v:,.0f}" if v < 0 else f"{sym}{v:,.0f}")  # noqa: E731
    c = res["costs"]
    neg = lambda v: f"{sym}0" if not v else f"−{sym}{v:,.0f}"  # noqa: E731
    out = [f"**Points & Miles Year in Review {res['year']}**", ""]
    if not res.get("complete", True):
        out += ["**Incomplete — the numbers below leave things out:**"] + [f"- {p}" for p in res["problems"]] + [""]
    out += [f"Net result at fallback prices: **{m(res['net_fallback'])}**. "
           f"At normalized value: **{m(res['net_value'])}**.", ""]
    out += [
           "| Line | Amount |", "|---|---:|",
           f"| Cash avoided (fallback − fees) | {m(res['income']['cash_avoided'])} |",
           f"| Value redeemed (normalized − fees) | {m(res['income']['value_redeemed'])} |",
           f"| Purchased points | {neg(c['points_purchased'])} |",
           f"| Services and tools | {neg(c['tools'])} |",
           f"| Annual fees | {neg(c['annual_fees'])} |",
           f"| Cancellation fees | {neg(c['cancellation_fees'])} |",
           f"| Foregone cash back | {neg(c['foregone_cashback'])} |",
           f"| **Net (fallback)** | **{m(res['net_fallback'])}** |",
           f"| **Net (value)** | **{m(res['net_value'])}** |"]
    if res.get("with_credits"):
        out += ["", f"Card credits used: {m(res['credits_used'])} (separate line). With credits: "
                    f"{m(res['with_credits']['net_fallback'])} at fallback, {m(res['with_credits']['net_value'])} at value."]
    nc = len(res["cancelled_removed"])
    out += ["", f"{len(res['redemptions'])} redemptions counted; {nc} cancelled {'one' if nc == 1 else 'ones'} removed. "
                "Unredeemed points are not part of the result."]
    out += [f"- {n}" for n in res["notes"]]
    if cmp:
        out += ["", "| Line | Recomputed | Your sheet | Difference |", "|---|---:|---:|---:|"]
        def diff(v):
            return "—" if v is None else f"{v:+,.0f}".replace("-", "−")
        out += [f"| {r['line']} | {m(r['recomputed'])} | {m(r['sheet'])} | {diff(r['difference'])} |" for r in cmp]
        out += [f"- {r['line']}: {r['explanation']}" for r in cmp if r.get("explanation")]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--spend")
    ap.add_argument("--credits", help="credits.py JSON for the same year; adds the credits line")
    ap.add_argument("--rate", type=float, help="override the cash-back rate from settings")
    ap.add_argument("--compare")
    ap.add_argument("--explain", help="JSON {line: explanation} for differences only the person can explain")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    a = ap.parse_args()
    try:
        led = fl.load(a.ledger)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    spend = json.loads(Path(a.spend).read_text()) if a.spend else None
    credits_used, credit_lines = None, None
    if a.credits:
        cj = json.loads(Path(a.credits).read_text())
        if cj.get("year") != a.year:
            print(json.dumps({"refused": f"The credits file is for {cj.get('year')}, not {a.year}."}))
            sys.exit(2)
        if cj.get("currency", led["_meta"]["setup"]["report_currency"]) != led["_meta"]["setup"]["report_currency"]:
            print(json.dumps({"refused": "The credits file is in another currency than this ledger's report."}))
            sys.exit(2)
        credits_used, credit_lines = credits_value(cj, led["_meta"]["settings"])
    res = compute(led, a.year, spend, credits_used, a.rate, credit_lines)
    cmp = compare(res, json.loads(Path(a.compare).read_text())) if a.compare else None
    if cmp and a.explain:
        extra = json.loads(Path(a.explain).read_text())
        for r in cmp:
            if r["line"] in extra:
                r["explanation"] = extra[r["line"]] if not r["explanation"] else r["explanation"] + " " + extra[r["line"]]
    if cmp:
        res["comparison"] = cmp
    print(to_markdown(res, cmp) if a.format == "md" else json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
