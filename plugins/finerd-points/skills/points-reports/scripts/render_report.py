#!/usr/bin/env python3
"""Render finerd points results as one self-contained HTML page (finerd design tokens).

Usage:
  render_report.py --ledger L --out report.html [--yir yir.json] [--credits credits.json]
                   [--expirations expirations.json] [--today YYYY-MM-DD] [--title "…"]

Inputs are the JSON outputs of yir.py, credits.py and expirations.py; balances come from
the ledger. Every text from outside (merchant descriptions, notes) is HTML-escaped. The
page loads nothing from the network.
"""
import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balances as bal  # noqa: E402
import credits as crd  # noqa: E402
import fpledger as fl  # noqa: E402

E = html.escape
CHIP = {
    "used": "green", "partly used": "blue", "not used yet": "warning", "no credit posted": "red",
    "unknown": "gray", "ask": "gray", "available (percentage back, up to the cap)": "gray",
    "current": "green", "stale": "warning", "conflicting": "red", "preliminary": "warning",
}


SYM = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$", "UAH": "₴", "JPY": "¥", "CHF": "CHF "}
CUR = {"sym": "$"}


def money(v, sign=False):
    c = E(CUR["sym"])
    if v is None:
        return "—"
    if abs(v) < 0.5:
        return f"{c}0"
    if v < 0:
        return f"−{c}{-v:,.0f}"
    return (f"+{c}{v:,.0f}" if sign and v > 0 else f"{c}{v:,.0f}")


def money2(v):
    return "—" if v is None else f"{E(CUR['sym'])}{v:,.2f}"


def chip(text):
    hue = CHIP.get(text, "gray")
    return f'<span class="chip chip-{hue}">{E(text)}</span>'


def tokens_css():
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "assets" / "fw-tokens.css", here.parent.parent / "assets" / "fw-tokens.css"):
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    return ":root{--finerd-colors-surface-flat:#000202;--finerd-colors-on-surface:#fffffff2;}"


CSS = """
body{margin:0;background:var(--finerd-colors-surface-flat);color:var(--finerd-colors-on-surface);
 font-family:var(--font-sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px;display:flex;flex-direction:column;gap:28px}
main>*{min-width:0}
header h1{font-size:28px;line-height:1.2;margin:0 0 6px;font-weight:600;text-wrap:balance}
.meta,.note{color:var(--finerd-colors-on-surface-variant);font-size:13px}
section{min-width:0;background:var(--finerd-colors-surface);border:1px solid var(--finerd-colors-stroke-solid);
 border-radius:var(--radius-2xl);padding:20px}
section h2{font-size:18px;margin:0 0 4px;font-weight:600}
section h3{font-size:15px;margin:18px 0 8px;font-weight:600}
.lead{color:var(--finerd-colors-on-surface-high);margin:4px 0 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:12px 0 16px}
.tile{background:var(--finerd-colors-container);border-radius:var(--radius-xl);padding:14px 16px}
.tile .k{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--finerd-colors-on-surface-variant)}
.tile .v{font-size:28px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:4px}
.tile .v.pos{color:var(--finerd-colors-badges-on-green)} .tile .v.neg{color:var(--finerd-colors-badges-on-red)}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:12px;font-weight:500;text-align:left;color:var(--finerd-colors-on-surface-variant);
 border-bottom:1px solid var(--finerd-colors-stroke-solid);padding:8px 10px;white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--finerd-colors-stroke-solid);vertical-align:top}
td.r,th.r{text-align:right;white-space:nowrap}
td.d{white-space:nowrap}
tr.total td{font-weight:600}
.chip{display:inline-block;font-size:12px;line-height:18px;padding:1px 8px;border-radius:var(--radius-full);white-space:nowrap}
.chip-green{background:var(--finerd-colors-badges-green);color:var(--finerd-colors-badges-on-green)}
.chip-blue{background:var(--finerd-colors-badges-blue);color:var(--finerd-colors-badges-on-blue)}
.chip-warning{background:var(--finerd-colors-badges-warning);color:var(--finerd-colors-badges-on-warning)}
.chip-red{background:var(--finerd-colors-badges-red);color:var(--finerd-colors-badges-on-red)}
.chip-gray{background:var(--finerd-colors-badges-gray);color:var(--finerd-colors-badges-on-gray)}
ul.q{margin:8px 0 0;padding-left:18px;color:var(--finerd-colors-on-surface-high)}
footer{color:var(--finerd-colors-on-surface-variant);font-size:12px;line-height:1.6}
a{color:var(--finerd-colors-primary-100)}
@media (max-width:520px){section{padding:14px}.tile .v{font-size:24px}td,th{padding:8px 6px}}
"""


def yir_section(y):
    c = y["costs"]
    tiles = []
    for k, v in (("Net result at fallback prices", y["net_fallback"]), ("Net result at normalized value", y["net_value"])):
        cls = "pos" if v > 0 else ("neg" if v < 0 else "")
        tiles.append(f'<div class="tile"><div class="k">{E(k)}</div><div class="v {cls}">{money(v)}</div></div>')
    if y.get("credits_used") is not None:
        tiles.append(f'<div class="tile"><div class="k">Card credits used (separate line)</div>'
                     f'<div class="v">{money(y["credits_used"])}</div></div>')
    rows = [("Cash avoided (fallback − fees)", y["income"]["cash_avoided"]),
            ("Value redeemed (normalized − fees)", y["income"]["value_redeemed"]),
            ("Purchased points", -c["points_purchased"]), ("Services and tools", -c["tools"]),
            ("Annual fees", -c["annual_fees"]), ("Cancellation fees", -c["cancellation_fees"]),
            ("Foregone cash back", -c["foregone_cashback"])]
    body = "".join(f"<tr><td>{E(n)}</td><td class='r'>{money(v)}</td></tr>" for n, v in rows)
    body += (f"<tr class='total'><td>Net result, fallback</td><td class='r'>{money(y['net_fallback'])}</td></tr>"
             f"<tr class='total'><td>Net result, value</td><td class='r'>{money(y['net_value'])}</td></tr>")
    out = [f"<section id='yir'><h2>Points &amp; Miles Year in Review {E(str(y['year']))}</h2>",
           "<p class='lead'>Income only when points turn into money or measured cash savings; purchased points "
           "are a cost once, in the year of purchase; unredeemed points are not part of the result.</p>",
           (("<p class='lead'><strong>Incomplete:</strong> " + " ".join(E(x) for x in y["problems"]) + "</p>")
            if y.get("problems") else ""),
           f"<div class='tiles'>{''.join(tiles)}</div>",
           f"<div class='scroll'><table><thead><tr><th>Line</th><th class='r'>{E(str(y['year']))}</th></tr></thead>"
           f"<tbody>{body}</tbody></table></div>"]
    reds = sorted(y["redemptions"], key=lambda r: r["booked_on"])
    if reds:
        rb = "".join(
            f"<tr><td class='d'>{E(r['booked_on'][:7])}</td><td>{E(r.get('description') or '')}</td><td>{E(r['program'])}</td>"
            f"<td class='r'>{r['points']:,}</td><td class='r'>{money(r['fees'])}</td>"
            f"<td class='r'>{money(r['cash_avoided'])}</td><td class='r'>{money(r['value_redeemed'])}</td></tr>"
            for r in reds)
        out.append("<h3>Redemptions</h3><div class='scroll'><table><thead><tr><th>Booked</th><th>What</th>"
                   "<th>Program</th><th class='r'>Points</th><th class='r'>Fees</th><th class='r'>Cash avoided</th>"
                   f"<th class='r'>Value</th></tr></thead><tbody>{rb}</tbody></table></div>")
    if y.get("comparison"):
        cb = "".join(
            f"<tr><td>{E(r['line'])}</td><td class='r'>{money(r['recomputed'])}</td><td class='r'>{money(r['sheet'])}</td>"
            f"<td class='r'>{money(r['difference'], sign=True) if r['difference'] else '0'}</td></tr>"
            for r in y["comparison"])
        why = "".join(f"<li><strong>{E(r['line'])}:</strong> {E(r['explanation'])}</li>"
                      for r in y["comparison"] if r.get("explanation"))
        out.append("<h3>Compared with your own sheet</h3><div class='scroll'><table><thead><tr><th>Line</th>"
                   "<th class='r'>Recomputed</th><th class='r'>Your sheet</th><th class='r'>Difference</th>"
                   f"</tr></thead><tbody>{cb}</tbody></table></div>"
                   + (f"<ul class='q'>{why}</ul>" if why else ""))
    notes = list(y.get("notes") or [])
    if y.get("explanations"):
        notes = list(y["explanations"]) + notes
    if notes:
        out.append("<ul class='q'>" + "".join(f"<li>{E(n)}</li>" for n in notes) + "</ul>")
    out.append("</section>")
    return "\n".join(out)


def credits_section(cr):
    t = cr.get("totals") or {}
    out = [f"<section id='credits'><h2>Card credits {E(str(cr['year']))}</h2>",
           f"<p class='lead'>Used {money2(t.get('used'))} of {money2(t.get('allowance_so_far'))} available to date; "
           f"{money2(t.get('open_this_period'))} still open this period; {money2(t.get('not_used_in_ended_periods'))} "
           f"not used in periods that ended; {money2(t.get('without_evidence'))} without evidence either way.</p>"]
    for c in cr["cards"]:
        cur = [(b, b["current"] or (b["periods"][-1] if b["periods"] else None)) for b in c["benefits"]
               if not (b.get("retired") and not b["current"])]  # older versions still count in the year
        cur = [(b, p) for b, p in cur if p]
        out.append(f"<h3>{E(c['nickname'])}</h3>")
        if c.get("facts_checked_on"):
            out.append(f"<p class='note'>Card terms checked {E(c['facts_checked_on'])}"
                       f"{', older than 90 days: unverified' if c.get('facts_stale') else ''}.</p>")
        if c.get("coverage_note"):
            out.append(f"<p class='note'>{E(c['coverage_note'])}</p>")
        for k in ("note", "note_soft"):
            if c.get(k):
                out.append(f"<p class='note'>{E(c[k])}</p>")
        if not cur:
            out.append("<p class='note'>No money credits to track on this card this year.</p>")
            continue
        rows = []
        for b, p in cur:
            status = p["status"]
            extra = ""
            if b.get("enrollment_note") and "not confirmed" in b["enrollment_note"]:
                extra = " <span class='note'>enrollment not confirmed</span>"
            if b.get("counted_on_card"):
                extra += " <span class='note'>shared allowance</span>"
            if b.get("fact_state") == "unverified":
                extra += f" <span class='note'>catalog fact unverified (checked {E(str(b.get('fact_checked_on')))})</span>"
            if b.get("gated"):
                extra += f" <span class='note'>opens only after {E(b['requires'].get('note') or '')}</span>"
            if p.get("notes"):
                extra += "<br><span class='note'>" + E("; ".join(p["notes"][:3])) + "</span>"
            # a per-stay or one-time credit has no period of its own, so no year-end deadline
            period = crd.EVENT_LABELS.get(b["period"], b["period"]) if b.get("event_like") else p["key"]
            ends = "—" if b.get("event_like") else p["end"]
            rows.append(f"<tr><td>{E(b['name'])}</td><td class='d'>{E(period)}</td><td class='r'>{money2(p['allowance'])}</td>"
                        f"<td class='r'>{money2(p['used'])}</td><td class='r'>{money2(p['remaining'])}</td>"
                        f"<td class='d'>{E(ends)}</td><td>{chip(status)}{extra}</td></tr>")
        out.append("<div class='scroll'><table><thead><tr><th>Credit</th><th>Period</th><th class='r'>Amount</th>"
                   "<th class='r'>Used</th><th class='r'>Left</th><th>Ends</th><th>Status</th></tr></thead><tbody>"
                   + "".join(rows) + "</tbody></table></div>")
    if cr.get("questions"):
        out.append("<h3>Please tell me</h3><ul class='q'>" + "".join(f"<li>{E(q)}</li>" for q in cr["questions"]) + "</ul>")
    out.append("</section>")
    return "\n".join(out)


def expirations_section(ex):
    items = [i for i in ex["items"] if i["kind"] != "credit_used"]
    out = [f"<section id='deadlines'><h2>Deadlines in the next {E(str(ex['days']))} days</h2>"]
    if not items:
        out.append("<p class='lead'>Nothing known expires in this window. Unknown deadlines are not safe ones.</p>")
    else:
        rows = "".join(
            f"<tr><td class='d'>{E(i['date'])}</td><td>{E(i['what'])}</td><td>{chip(i['status'])}"
            f"{' <span class=note>never used this year: no reminder</span>' if i.get('never_used') else ''}</td>"
            f"<td class='r'>{money2(i['value']) if i['kind'] == 'credit' else ''}</td></tr>" for i in items)
        out.append("<div class='scroll'><table><thead><tr><th>Date</th><th>What</th><th>Status</th>"
                   f"<th class='r'>Value</th></tr></thead><tbody>{rows}</tbody></table></div>")
    out.append("</section>")
    return "\n".join(out)


def _safe_link(url):
    return url if isinstance(url, str) and url.startswith("https://") and "\"" not in url and "'" not in url else None


def balances_section(t):
    rows = []
    for r in t["accounts"]:
        b = "unknown" if r["balance"] is None else f"{r['balance']:,} {r['unit']}"
        src = "" if not r["source"] else (r["source"].get("name") or r["source"]["kind"])
        link = _safe_link(r.get("link"))
        src_html = f"<a href='{E(link)}' rel='noopener noreferrer'>{E(src)}</a>" if link else E(src)
        note = f"{r['age_days']} days old" if r["state"] == "stale" else ""
        rows.append(f"<tr><td>{E(r['nickname'])}</td><td class='r'>{E(b)}</td><td>{E(r['as_of'] or '—')}</td>"
                    f"<td>{src_html}</td><td>{chip(r['state'])} <span class='note'>{E(note)}</span></td></tr>")
        g = r.get("aggregator")
        if g:
            rows.append(f"<tr><td class='note'>↳ {E(g['source'].get('name') or 'aggregator')}</td>"
                        f"<td class='r note'>{g['balance']:,}</td><td class='note'>{E(g.get('freshness') or 'age unknown')}"
                        f"</td><td class='note'>not counted</td><td></td></tr>")
    return ("<section id='balances'><h2>Balances</h2><p class='lead'>Each number with its date and source. Balances of "
            "different programs are not added up, and points never enter net worth.</p><div class='scroll'><table>"
            "<thead><tr><th>Program</th><th class='r'>Balance</th><th>As of</th><th>Source</th><th>State</th></tr>"
            "</thead><tbody>" + "".join(rows) + "</tbody></table></div></section>")


def collection_section(c, refresh_note):
    rows = "".join(
        f"<tr><td>{E(a['source'])}</td><td>{E(a['account'])}</td><td class='r'>{a['rows_counted']:,}</td>"
        f"<td class='d'>{E(a['first'] or '—')} – {E(a['last'] or '—')}</td>"
        f"<td>{chip('preliminary') if a['preliminary'] else ''}</td></tr>" for a in c["accounts"])
    out = ["<section id='collected'><h2>What was read</h2>",
           "<div class='scroll'><table><thead><tr><th>Source</th><th>Account</th><th class='r'>Rows</th>"
           f"<th>Dates</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"]
    if c["problems"]:
        out.append("<h3>Could not be read completely</h3><ul class='q'>" + "".join(
            f"<li><strong>{E(p['what'])}</strong>: {E(p['state'])} — {E(p['why'])}</li>" for p in c["problems"]) + "</ul>")
    if c["open_links"] or c["rows_not_shown"]:
        out.append(f"<p class='lead'>Waiting for your decision: {c['open_links']} pair(s) of rows that may be the same, "
                   f"{c['rows_not_shown']} row(s) no longer shown on a site. The earlier rows stay counted until you "
                   f"decide.</p>")
    out.append(f"<p class='note'>{E(refresh_note)}</p></section>")
    return "\n".join(out)


def render(led, today, title, yir=None, credits=None, expirations=None, collection=None, unknown_deadlines=None,
           balances_table=None, refresh_note=None):
    cur = led["_meta"]["setup"]["report_currency"]
    CUR["sym"] = SYM.get(cur, cur + " ")
    person = next((p["name"] for p in led["people"] if p.get("role") == "owner"), "")
    parts = [f"<header><h1>{E(title)}</h1><div class='meta'>{E(person)} · as of {today.isoformat()} · "
             f"ledger version {led['version']} · amounts in {E(led['_meta']['setup']['report_currency'])}</div></header>"]
    # The order of the report (spec v2): balances, credits, deadlines, Year in Review, what was read.
    if led["accounts"]:
        parts.append(balances_section(balances_table or bal.table(led, today)))
    if credits:
        parts.append(credits_section(credits))
    if expirations:
        sec = expirations_section(expirations)
        if unknown_deadlines:
            sec = sec.replace("</section>", "<h3>Deadlines whose date is unknown</h3><ul class='q'>" + "".join(
                f"<li>{E(u)}</li>" for u in unknown_deadlines) + "</ul></section>")
        parts.append(sec)
    if yir:
        parts.append(yir_section(yir))
    if collection:
        parts.append(collection_section(collection, refresh_note or ""))
    parts.append("<footer>Made with finerd points from your own ledger; nothing was sent anywhere. Card terms come "
                 "from the finerd points facts catalog (issuer pages plus independent reviews, with check dates). "
                 "Method: «Points Are Not Just Points» framework v1.2, §5.1. Estimates for your information, not "
                 "financial advice.</footer>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{E(title)}</title><style>{tokens_css()}\n{CSS}</style></head><body><main>"
            + "\n".join(parts) + "</main></body></html>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--yir")
    ap.add_argument("--credits")
    ap.add_argument("--expirations")
    ap.add_argument("--today")
    ap.add_argument("--title", default="Points & Miles")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    try:
        led = fl.load(a.ledger)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    rd = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if p else None  # noqa: E731
    page = render(led, today, a.title, rd(a.yir), rd(a.credits), rd(a.expirations))
    Path(a.out).write_text(page, encoding="utf-8")
    print(json.dumps({"written": a.out, "bytes": len(page.encode("utf-8"))}))


if __name__ == "__main__":
    main()
