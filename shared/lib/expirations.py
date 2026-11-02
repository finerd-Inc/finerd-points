#!/usr/bin/env python3
"""What expires soon: credits, points, certificates and sign-up bonus deadlines.

Usage:
  expirations.py --ledger L [--credits credits.json] [--days 45] [--today YYYY-MM-DD]
                 [--format json|md] [--calendar-plan batch.json]

`--credits` is the JSON output of credits.py (so credit deadlines use the same evidence).
`--calendar-plan` writes a batch of calendar operations to preview with ledger.py:
new deadlines → create a private event without guests; a changed deadline → update the
existing event; a used credit → «✓» in the title and its reminder removed. Nothing is deleted.
In the first version every deadline comes from a source (program account, email, statement,
bank page, the person); no rule-derived expiry dates.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpledger as fl  # noqa: E402


NEVER_USED_MIN_PERIODS = 3


def collect(led, credits, today, days):
    end = today + dt.timedelta(days=days)
    obs = fl.active_observations(led)
    items = []
    cards = {c["id"]: c for c in led["cards"]}
    for c in (credits or {}).get("cards", []):
        for b in c.get("benefits", []):
            p = b.get("current")
            if not p or b.get("counted_on_card") or b.get("cap_only") or b.get("gated") or b.get("event_like"):
                continue
            d = dt.date.fromisoformat(p["end"])
            if not (today <= d <= end):
                continue
            ended = [q for q in b["periods"] if not q["current"] and q.get("in_year", True)]
            never_used = (len(ended) >= NEVER_USED_MIN_PERIODS
                          and all(q["status"] == "no credit posted" for q in ended))
            base = {"date": p["end"], "currency": "USD", "card": c["card"],
                    "subject": f"benefit:{c['card']}/{b['benefit']}/{p['key']}",
                    "what": f"{b['name']} ({c['nickname']})", "source": "card terms (facts catalog) + transactions"}
            if p["status"] in ("not used yet", "partly used", "ask", "unknown"):
                value = p["remaining"] if p["remaining"] is not None else p["allowance"]
                items.append({**base, "kind": "credit", "value": value, "status": p["status"],
                              "never_used": never_used})
            elif p["status"] == "used":
                items.append({**base, "kind": "credit_used", "value": 0, "status": "used", "never_used": False})
    for acc in led["accounts"]:
        e = fl.current(led, f"account:{acc['id']}", "expires_on", obs)
        if e and today <= dt.date.fromisoformat(e["value"]) <= end:
            items.append({"date": e["value"], "kind": "points", "value": None, "subject": f"account:{acc['id']}",
                          "what": f"{acc['nickname']} {acc['unit']}", "status": "expiring",
                          "source": e["source"].get("name") or e["source"]["kind"]})
    for cert in led["certificates"]:
        subj = f"certificate:{cert['id']}"
        state = fl.current(led, subj, "state", obs)
        if state and state["value"] in ("used", "expired"):
            items.append({"date": cert.get("expires_on") or today.isoformat(), "kind": "done", "subject": subj,
                          "what": cert["type"], "status": state["value"], "value": None, "source": "ledger"})
            continue
        exp = fl.current(led, subj, "expires_on", obs)
        expires = exp["value"] if exp else cert.get("expires_on")
        if expires and today <= dt.date.fromisoformat(expires) <= end:
            items.append({"date": expires, "kind": "certificate", "value": None, "subject": subj,
                          "what": cert["type"], "status": "unused",
                          "source": (exp["source"].get("name") or exp["source"]["kind"]) if exp else
                          (cert.get("source") or {}).get("kind", "ledger")})
    for so in led["signup_offers"]:
        got = fl.current(led, f"signup:{so['id']}", "received", obs)
        if got and got["value"]:
            items.append({"date": so["deadline"], "kind": "done", "subject": f"signup:{so['id']}",
                          "what": "Sign-up bonus", "status": "received", "value": None, "source": "ledger"})
            continue
        dl = fl.current(led, f"signup:{so['id']}", "deadline", obs)
        so = {**so, "deadline": dl["value"] if dl else so["deadline"]}
        if today <= dt.date.fromisoformat(so["deadline"]) <= end:
            spent = fl.current(led, f"signup:{so['id']}", "spend_so_far", obs)
            items.append({"date": so["deadline"], "kind": "signup", "value": so["spend"],
                          "subject": f"signup:{so['id']}",
                          "what": f"Sign-up bonus on {cards.get(so['card'], {}).get('nickname', so['card'])}",
                          "status": f"spent {spent['value']} of {so['spend']}" if spent else f"spend {so['spend']} needed",
                          "source": (so.get("source") or {}).get("kind", "person")})
    items.sort(key=lambda x: (x["date"], x["what"]))
    return items


def _event_payload(setup, title, date, reminder, description, members=None):
    return {"calendar_id": setup["calendar_id"], "title": title, "date": date, "all_day": True,
            "timezone": setup.get("timezone"), "reminder_minutes": reminder, "visibility": "private",
            "attendees": [], "description": description, "members": members or [], "done": False}


def calendar_plan(led, items, today=None):
    """One private event per deadline date for card credits (listing them), one per points,
    certificate or sign-up deadline. Credits without evidence («unknown») and credits never used
    in the last periods get no event; the report says so."""
    s = led["_meta"]["settings"]
    setup = led["_meta"]["setup"]
    min_value = s.get("calendar_min_value", 25)
    reminder = int(s.get("reminder_days_before", 3)) * 1440
    today_iso = (today or dt.date.today()).isoformat()
    by_subject = {}
    for ev in led["calendar_events"]:
        if ev.get("subject"):
            by_subject.setdefault(ev["subject"], []).append(ev)
    ops = []

    def upsert(subject, title, date, description, summary_extra="", members=None):
        live = [e for e in by_subject.get(subject, []) if not e.get("done")]
        if live:
            ev = live[0]
            changed = (ev.get("date") != date or ev.get("title") != title or ev.get("reminder_minutes") != reminder
                       or (ev.get("description") or "").split("\n[finerd points")[0] != description)
            if changed:
                ops.append({"op": "external", "target": "calendar", "action": "update", "app": "calendar",
                            "subject": subject,
                            "match_key": f"update:{ev['event_id']}:{fl.sha([date, title, reminder, description], 10)}",
                            "summary": f"Update «{ev['title']}» → «{title}» on {date}",
                            "payload": {"event_id": ev["event_id"], "calendar_id": ev.get("calendar_id"),
                                        "title": title, "date": date, "reminder_minutes": reminder,
                                        "description": description + f"\n[finerd points {ev.get('op_id', '')}]",
                                        "members": members or [], "visibility": "private"}})
            return
        gen = sum(1 for e in by_subject.get(subject, []) if e.get("done"))  # a reopened deadline is a new event
        op = {"op": "external", "target": "calendar", "action": "create", "app": "calendar",
              "subject": subject, "match_key": f"create:{subject}:{date}" + (f":g{gen}" if gen else ""),
              "summary": f"Event «{title}» on {date}, private, no guests, reminder {reminder // 1440} days "
                         f"before{summary_extra}",
              "payload": _event_payload(setup, title, date, reminder, description, members)}
        # A marker the skill searches for before creating and after an unknown outcome.
        op["payload"]["description"] += f"\n[finerd points {fl.external_op_id(op)}]"
        ops.append(op)

    def mark_done(subject):
        for ev in by_subject.get(subject, []):
            if not ev.get("done"):
                ops.append({"op": "external", "target": "calendar", "action": "update", "app": "calendar",
                            "subject": subject, "match_key": f"done:{ev['event_id']}",
                            "summary": f"Mark «{ev['title']}» done: add ✓ and turn its reminder off",
                            "payload": {"event_id": ev["event_id"], "calendar_id": ev.get("calendar_id"),
                                        "title": "✓ " + ev["title"].lstrip("✓ "), "reminder_minutes": None,
                                        "done": True, "visibility": "private"}})

    by_date = {}
    for it in items:
        if it["kind"] in ("credit", "credit_used"):
            by_date.setdefault(it["date"], []).append(it)
    open_subjects = {it["subject"] for it in items if it["kind"] == "credit"}
    used_subjects = {it["subject"] for it in items if it["kind"] == "credit_used"}
    tracked = set()  # subjects that will have a live event after this plan
    for date, group in sorted(by_date.items()):
        subject = f"credits:{date}"
        open_items = [it for it in group if it["kind"] == "credit" and it["status"] != "unknown"
                      and not it["never_used"]]
        if not open_items:
            # ✓ only on positive evidence: every credit the event lists is now used.
            for ev in by_subject.get(subject, []):
                members = set(ev.get("members") or [])
                if not ev.get("done") and members and members <= used_subjects:
                    mark_done(subject)
                    break
            continue
        has_event = any(not e.get("done") for e in by_subject.get(subject, []))
        if not has_event and sum(it["value"] or 0 for it in open_items) < min_value:
            continue  # an existing event is still kept up to date below the minimum
        tracked |= {it["subject"] for it in open_items}
        title = f"Card credits ending ({len(open_items)})"
        lines = [f"- {it['what']}: {it['value']:,.2f} left ({it['status']})" for it in open_items]
        upsert(subject, title, date, "Created by finerd points at your request.\n" + "\n".join(lines),
               f" — {', '.join(it['what'] for it in open_items)}", [it["subject"] for it in open_items])
    # A grouped event whose date has no items now: ✓ only when every member is known to be used, or
    # when every member is open under another date (it is tracked there). Missing data changes nothing.
    for subject, evs in by_subject.items():
        if not subject.startswith("credits:") or subject[len("credits:"):] in by_date:
            continue
        for ev in evs:
            members = set(ev.get("members") or [])
            if ev.get("done") or ev.get("date", "") < today_iso or not members:
                continue
            # Moved: only when each member really has its event under the new date.
            if members <= used_subjects or members <= tracked:
                mark_done(subject)
    for it in items:
        if it["kind"] == "done":
            mark_done(it["subject"])
    for it in items:
        if it["kind"] in ("credit", "credit_used", "done"):
            continue
        title = {"points": f"{it['what']} expire", "certificate": f"{it['what']} expires",
                 "signup": f"{it['what']}: spend deadline"}[it["kind"]]
        upsert(it["subject"], title, it["date"], "Created by finerd points at your request. Details are in your ledger.")
    return ops


def to_markdown(items, days, today):
    out = [f"**Deadlines in the next {days} days** (from {today.isoformat()})", ""]
    if not items:
        out.append("Nothing known expires in this window. Unknown deadlines are not shown as safe: "
                   "add expiry dates from your program accounts or emails.")
        return "\n".join(out)
    out += ["| Date | What | Status | Value | Source |", "|---|---|---|---:|---|"]
    items = [it for it in items if it["kind"] != "done"]
    skipped = [it for it in items if it.get("never_used")]
    unknown = [it for it in items if it["kind"] == "credit" and it["status"] == "unknown"]
    for it in items:
        if it["kind"] == "credit_used":
            continue
        val = "" if it["value"] in (None, 0) else (f"${it['value']:,.2f}" if it["kind"] == "credit" else f"{it['value']:,}")
        note = " (never used this year: no reminder)" if it.get("never_used") else ""
        out.append(f"| {it['date']} | {it['what']} | {it['status']}{note} | {val} | {it['source']} |")
    if unknown:
        out.append("")
        out.append(f"{len(unknown)} credits have no evidence either way (card not connected, or not shown by the bank); "
                   f"they get no reminder until you tell me whether you use them.")
    if skipped:
        out.append(f"{len(skipped)} credits were never used in this year's earlier periods, so they get no reminder.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--credits")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--today")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--calendar-plan")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    try:
        led = fl.load(a.ledger)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    credits = json.loads(Path(a.credits).read_text(encoding="utf-8")) if a.credits else None
    if credits and credits.get("as_of") != today.isoformat():
        print(json.dumps({"refused": f"The credits result is from {credits.get('as_of')}, not {today.isoformat()}. "
                                     f"Run credits.py again for today before planning deadlines."}))
        sys.exit(2)
    items = collect(led, credits, today, a.days)
    if a.calendar_plan:
        if not led["_meta"]["setup"].get("calendar_id"):
            print(json.dumps({"refused": "Ask which calendar to use and record its real id first: "
                                         '{"op":"set_setup","key":"calendar_id","value":"<calendar id>"}.'}))
            sys.exit(2)
        ops = calendar_plan(led, items, today)
        Path(a.calendar_plan).write_text(json.dumps(ops, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if a.format == "md":
        print(to_markdown(items, a.days, today))
    else:
        print(json.dumps({"as_of": today.isoformat(), "days": a.days, "items": items}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
