#!/usr/bin/env python3
"""The finerd points report, built from the ledger alone (spec v2, «The report»).

Usage:
  report.py --ledger <folder>/ledger.json [--transactions *.txns.json] [--today YYYY-MM-DD]
            [--days 45] [--year YYYY] [--format md|json] [--html <folder>/reports/report.html]

Shows, in this order: balances per program with date, source and a link to check it; card credits
(allowance, used, left, deadline; the issuer tracker's caveat); deadlines in the coming weeks and
those whose date is unknown; Year in Review with its completeness; what could not be read and why;
and that a refresh re-checks the last 60 days. A finance app is optional: without `--transactions`
credits come from what the issuer's own benefits page showed and from the person's answers.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balances as bal  # noqa: E402
import credits as crd  # noqa: E402
import expirations as exp  # noqa: E402
import fpcollect as fc  # noqa: E402
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402
import yir  # noqa: E402

REFRESH_NOTE = ("A refresh re-reads the last 60 days of each history; a correction a site makes to older rows is "
                "found only by a full re-read, which compares the whole history.")


def _source_link(led, source):
    ref = (source or {}).get("ref")
    s = next((x for x in led.get("sources", []) if x["id"] == ref), None)
    if s and s.get("hosts"):
        return f"https://{s['hosts'][0]}"
    return None


def collection_state(led):
    """Per source account: rows counted, the interval covered, and what could not be read."""
    counted, excluded, prelim = fc.counted_records(led)
    out, problems = [], []
    for s in led.get("sources", []):
        for a in s["accounts"]:
            covs = [c for c in s.get("coverage", []) if c["account"] == a["id"]]
            last = {}
            for c in covs:
                last[c["section"]] = c
            rows = [r for r in counted if r["source"] == s["id"] and r["account"] == a["id"]]
            out.append({"source": s["name"], "kind": s["kind"], "account": a.get("label") or a["id"],
                        "rows_counted": len(rows),
                        "first": min((r["date"] for r in rows), default=None),
                        "last": max((r["date"] for r in rows), default=None),
                        "sections": {k: {"state": v["state"], "covered": v.get("covered"),
                                         "as_of_text": v.get("as_of_text"), "read_at": v["read_at"]}
                                     for k, v in last.items()},
                        "preliminary": (s["id"], a["id"]) in prelim})
            for sec, c in last.items():
                if c["state"] != "complete":
                    why = c.get("stop_reason") or {"partial": "the history was not read to its end",
                                                   "ends_unreconciled": "both ends were reached but continuity "
                                                                        "could not be shown",
                                                   "unavailable": "the site did not show it"}[c["state"]]
                    problems.append({"what": f"{s['name']} — {a.get('label') or a['id']} ({sec})",
                                     "state": c["state"], "why": why})
    open_links = [e for e in led.get("events", []) if e.get("kind") == "link" and e.get("state") == "unresolved"]
    not_shown = [r for r in led.get("records", []) if r.get("not_shown") and not r["not_shown"].get("decision")]
    return {"accounts": out, "problems": problems, "open_links": len(open_links), "rows_not_shown": len(not_shown),
            "preliminary": bool(prelim)}


def unknown_deadlines(led, catalog, table):
    out = []
    progs = catalog.get("programs", {})
    for r in table["accounts"]:
        pf = progs.get(r["program"]) or {}
        rule = pf.get("expiry")
        if r["expires_on"] is None and not (isinstance(rule, dict) and rule.get("kind") == "never"):
            out.append(f"{r['nickname']}: points expiry date not known")
    return out


CURRENCY = __import__("re").compile(r"^[A-Z]{3}$")


def _kind(desc, direction):
    import normalize as nz
    up = desc.upper()
    if nz.MARKER_RE.search(desc):
        return "noncash"
    if direction == "debit":
        return "fee" if nz.FEE_RE.search(desc) else "purchase"
    if "PAYMENT" in up or "AUTOPAY" in up or "THANK YOU" in up:
        return "payment"
    if "CREDIT" in up and not __import__("re").search(r"\b(REFUND|RETURN)", up):
        return "credit"
    return "refund"


def _merge(intervals):
    """Merge [from, to] date intervals that touch or overlap (a gap of one day or more stays a gap)."""
    import datetime as _dt
    out = []
    for f, t in sorted(intervals):
        if out and _dt.date.fromisoformat(f) <= _dt.date.fromisoformat(out[-1][1]) + _dt.timedelta(days=1):
            out[-1][1] = max(out[-1][1], t)
        else:
            out.append([f, t])
    return out


def _latest_contiguous(intervals):
    """The merged complete interval that reaches latest: coverage is only claimed where it has no gap."""
    m = _merge(intervals)
    return m[-1] if m else None


def ledger_transactions(led):
    """Appendix D bridge: counted rows a card's own site showed (money, not points) become transactions in the
    normalized contract, so credits are computed with no finance app. A source account belongs to a card when
    its inventory id is the card's id. Returns (ledger view with links, accounts, transactions)."""
    import json as _json
    import normalize as nz
    view = _json.loads(_json.dumps(led))
    cards = {c["id"]: c for c in view["cards"]}
    counted, _, _ = fc.counted_records(led)
    accounts, txns = {}, []
    rows_of = {}
    for r in counted:
        if r["section"] == "activity":  # issuer benefit trackers are observations, not rows: never counted twice
            rows_of.setdefault((r["source"], r["account"]), []).append(r)
    for r in counted:  # rows kept under «credits» by a pre-release build: used only where no activity exists
        if r["section"] == "credits" and (r["source"], r["account"]) not in rows_of:
            rows_of.setdefault(("legacy", r["source"], r["account"]), []).append(r)
    for k in [k for k in rows_of if k[0] == "legacy"]:
        rows_of[(k[1], k[2])] = rows_of.pop(k)
    # Only a card's own site or statements count as its transactions, never an aggregator. All of them are used:
    # rows the same event produced in two of them are one event group, of which counted_records keeps one.
    per_card = {}
    for s_ in led.get("sources", []):
        if s_["kind"] not in ("bank_card", "statement"):
            continue
        for a in s_["accounts"]:
            card = cards.get(a.get("inventory"))
            unit = a.get("unit") or s_.get("unit") or ""
            if not card or card.get("finance_link") or not CURRENCY.match(str(unit)):
                continue  # a finance app, when linked, stays the source of the card's transactions
            if rows_of.get((s_["id"], a["id"])):
                per_card.setdefault(card["id"], []).append((s_, a, unit))
    for card_id, parts in sorted(per_card.items()):
        card = cards[card_id]
        aid = f"ledger:card:{card_id}"
        card["finance_link"] = {"app": "ledger", "account_id": aid, "account_name": card.get("nickname") or card_id}
        covs = [fc.coverage_state(led, s_["id"], a["id"], "activity") for s_, a, _ in parts]
        full = [c["covered"] for c in covs if c and c["state"] == "complete" and c.get("covered")]
        span = _latest_contiguous(full)
        partial = [c["covered"] for c in covs if c and c.get("covered")]
        if span:
            cov = {"from": span[0], "to": span[1]}
            note = None if len(_merge(full)) == 1 else (f"Complete only from {span[0]} to {span[1]}; earlier "
                                                         f"periods have gaps between the statements read.")
        elif partial:
            cov = {"from": min(x[0] for x in partial), "to": max(x[1] for x in partial)}
            note = "The card's own site was not read completely."
        else:
            cov, note = {"from": None, "to": None}, "The card's own site was not read completely."
        accounts[aid] = {"account_id": aid, "name": card.get("nickname") or card_id, "coverage": cov,
                         "complete": bool(span), "coverage_note": note, "scope": "filtered"}
        for s_, a, unit in parts:
            for r in rows_of[(s_["id"], a["id"])]:
                direction = "credit" if r["amount"] > 0 else "debit"
                txns.append({"id": r["id"], "account_id": aid, "date": r["date"], "posted_date": None,
                             "amount": abs(float(r["amount"])), "currency": unit, "direction": direction,
                             "kind": _kind(r["description"], direction), "description": r["description"],
                             "merchant": None, "category": None, "pending": False, "reversal_of": None,
                             "reversal_hint": bool(nz.REVERSAL_RE.search(r["description"]))})
    return view, accounts, txns


def build(led, today, txn_paths=None, days=45, year=None, facts_dir=None):
    year = year or today.year
    catalog = ff.load_catalog(facts_dir)
    accounts, txns = crd.load_txns(txn_paths) if txn_paths else ({}, [])
    view, l_accounts, l_txns = ledger_transactions(led)
    accounts.update(l_accounts)
    txns = list(txns) + l_txns
    cr = crd.analyze(view, catalog, accounts, txns, today, year)
    cr["totals"] = crd.totals(cr)
    items = exp.collect(led, cr, today, days)
    table = bal.table(led, today)
    for r in table["accounts"]:
        r["link"] = _source_link(led, r.get("source"))
    credits_used, credit_lines = yir.credits_value(cr, led["_meta"]["settings"])
    y = yir.compute(led, year, None, credits_used, None, credit_lines)
    return {
        "as_of": today.isoformat(), "ledger_version": led["version"],
        "balances": table, "credits": cr, "deadlines": {"items": items, "days": days,
                                                        "unknown": unknown_deadlines(led, catalog, table)},
        "year_in_review": y, "collection": collection_state(led), "refresh_note": REFRESH_NOTE,
    }


def to_markdown(r):
    out = [f"# Points & Miles — as of {r['as_of']} (ledger version {r['ledger_version']})", ""]
    if r.get("from_backup"):
        out += [f"**{r['from_backup']}**", ""]
    out.append("## Balances")
    out.append("| Program | Balance | As of | Source | State |")
    out.append("|---|---:|---|---|---|")
    for a in r["balances"]["accounts"]:
        b = "unknown" if a["balance"] is None else f"{a['balance']:,} {a['unit']}"
        src = (a.get("source") or {}).get("name") or (a.get("source") or {}).get("kind") or ""
        if a.get("link"):
            src = f"[{src}]({a['link']})"
        state = a["state"] + (f" ({a['age_days']} days old)" if a["state"] == "stale" else "")
        out.append(f"| {a['nickname']} | {b} | {a['as_of'] or '—'} | {src} | {state} |")
        if a.get("aggregator"):
            g = a["aggregator"]
            out.append(f"| ↳ {g['source'].get('name') or 'aggregator'} | {g['balance']:,} | "
                       f"{g.get('freshness') or 'age unknown'} | not counted | |")
    out += ["", crd.to_markdown(r["credits"]), ""]
    out.append(exp.to_markdown(r["deadlines"]["items"], r["deadlines"]["days"], dt.date.fromisoformat(r["as_of"])))
    if r["deadlines"]["unknown"]:
        out.append("")
        out.append("**Deadlines whose date is unknown** (unknown is not safe): " + "; ".join(r["deadlines"]["unknown"]))
    out += ["", yir.to_markdown(r["year_in_review"]), ""]
    c = r["collection"]
    out.append("## What was read")
    for a in c["accounts"]:
        span = f"{a['first']} to {a['last']}" if a["first"] else "no rows"
        flag = " — totals preliminary until you decide on the marked rows" if a["preliminary"] else ""
        out.append(f"- {a['source']} — {a['account']}: {a['rows_counted']} rows, {span}{flag}")
    if c["problems"]:
        out.append("")
        out.append("**Could not be read completely:**")
        out += [f"- {p['what']}: {p['state']} — {p['why']}" for p in c["problems"]]
    if c["open_links"] or c["rows_not_shown"]:
        out.append("")
        out.append(f"**Waiting for your decision:** {c['open_links']} pair(s) of rows that may be the same, "
                   f"{c['rows_not_shown']} row(s) no longer shown on a site. The earlier rows stay counted until "
                   f"you decide.")
    out += ["", r["refresh_note"]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--transactions", nargs="*", default=[])
    ap.add_argument("--today")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--year", type=int)
    ap.add_argument("--facts")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--html", help="also write the HTML page here (in the ledger folder's reports/)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    from_backup = None
    try:
        led = fl.load(a.ledger)
    except fl.LedgerError as e:
        import fpstore
        good = fpstore.newest_good_backup(Path(a.ledger).resolve().parent)
        if not good:
            print(json.dumps({"refused": str(e)}))
            sys.exit(2)
        led, from_backup = good
    r = build(led, today, a.transactions, a.days, a.year, a.facts)
    if from_backup:
        r["from_backup"] = (f"ledger.json cannot be read; this report is shown read-only from the backup "
                            f"{from_backup} (version {led['version']}). Nothing is written until you decide how to "
                            f"restore.")
    if a.html:
        import render_report as rr
        page = rr.render(led, today, "Points & Miles", r["year_in_review"], r["credits"],
                         {"items": r["deadlines"]["items"], "days": r["deadlines"]["days"]},
                         collection=r["collection"], unknown_deadlines=r["deadlines"]["unknown"],
                         balances_table=r["balances"], refresh_note=r["refresh_note"])
        Path(a.html).write_text(page, encoding="utf-8")
    print(to_markdown(r) if a.format == "md" else json.dumps(r, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
