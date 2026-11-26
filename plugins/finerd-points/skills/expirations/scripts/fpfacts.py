"""Facts catalog access and benefit periods (Python 3.9+, standard library only)."""
import datetime as dt
import json
from pathlib import Path

STALE_DAYS = 90


def default_facts_dir():
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "facts", here / "facts", here.parent.parent / "facts"):
        if (cand / "cards").is_dir():
            return cand
    raise FileNotFoundError("facts catalog not found next to the scripts")


def load_catalog(facts_dir=None):
    root = Path(facts_dir) if facts_dir else default_facts_dir()
    cards = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "cards").glob("*.json"))}
    programs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "programs").glob("*.json"))}
    return {"cards": cards, "programs": programs}


def is_stale(card, today):
    checked = dt.date.fromisoformat(card["checked_on"])
    return (today - checked).days > STALE_DAYS


def fact_checked_on(card, benefit=None):
    """A benefit's own check date, or its file's (spec v2: checked_on belongs to each fact)."""
    return (benefit or {}).get("checked_on") or card["checked_on"]


def fact_state(card, benefit, today):
    """verified | unverified (older than 90 days, or no primary page confirms it yet)."""
    if (benefit or {}).get("unverified"):
        return "unverified"
    checked = dt.date.fromisoformat(fact_checked_on(card, benefit))
    return "unverified" if (today - checked).days > STALE_DAYS else "verified"


def stale_facts(catalog, today):
    """Every fact older than 90 days or unverified: [(file, item, checked_on, reason)]."""
    out = []
    for cid, c in sorted(catalog["cards"].items()):
        for b in c.get("benefits", []):
            if b.get("effective_to") and b["effective_to"] < today.isoformat():
                continue
            st = fact_state(c, b, today)
            if st != "verified":
                why = "no issuer or program page confirms it yet" if b.get("unverified") else "older than 90 days"
                out.append((f"cards/{cid}.json", b["id"], fact_checked_on(c, b), why))
        if (today - dt.date.fromisoformat(c["checked_on"])).days > STALE_DAYS:
            out.append((f"cards/{cid}.json", "annual fee and card details", c["checked_on"], "older than 90 days"))
    for pid, p in sorted(catalog["programs"].items()):
        if (today - dt.date.fromisoformat(p["checked_on"])).days > STALE_DAYS:
            out.append((f"programs/{pid}.json", "expiry rule and hosts", p["checked_on"], "older than 90 days"))
    return out


def _active(item, on):
    f, t = item.get("effective_from"), item.get("effective_to")
    if f and on < dt.date.fromisoformat(f):
        return False
    if t and on > dt.date.fromisoformat(t):
        return False
    return True


def active_benefits(card, on):
    return [b for b in card.get("benefits", []) if _active(b, on)]


def annual_fee_on(card, on):
    fees = [f for f in card.get("annual_fee", []) if _active(f, on)]
    return fees[-1]["amount"] if fees else None


# ---------------------------------------------------------------- periods

def _month_end(y, m):
    nxt = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - dt.timedelta(days=1)


def period_of(period, day, anniversary=None):
    """Return (key, start, end) of the benefit period containing `day`, or None when the
    period cannot be known (card_year without an anniversary; per-stay; ongoing)."""
    y, m = day.year, day.month
    if period == "month":
        return f"{y}-{m:02d}", dt.date(y, m, 1), _month_end(y, m)
    if period == "quarter":
        q = (m - 1) // 3 + 1
        sm = 3 * (q - 1) + 1
        return f"{y}-Q{q}", dt.date(y, sm, 1), _month_end(y, sm + 2)
    if period == "half_year":
        h = 1 if m <= 6 else 2
        return f"{y}-H{h}", dt.date(y, 1 if h == 1 else 7, 1), dt.date(y, 6, 30) if h == 1 else dt.date(y, 12, 31)
    if period == "calendar_year":
        return f"{y}", dt.date(y, 1, 1), dt.date(y, 12, 31)
    if period == "card_year":
        if not anniversary:
            return None
        am, ad = int(anniversary[:2]), int(anniversary[3:5])
        start = dt.date(y, am, min(ad, _month_end(y, am).day))
        if day < start:
            start = dt.date(y - 1, am, min(ad, _month_end(y - 1, am).day))
        nxt = dt.date(start.year + 1, am, min(ad, _month_end(start.year + 1, am).day))
        return f"CY{start.isoformat()}", start, nxt - dt.timedelta(days=1)
    return None


def periods_between(period, start, end, anniversary=None):
    """All periods that overlap [start, end], in order."""
    out, day = [], start
    seen = set()
    while day <= end:
        p = period_of(period, day, anniversary)
        if p is None:
            return []
        if p[0] not in seen:
            out.append(p)
            seen.add(p[0])
        day = p[2] + dt.timedelta(days=1)
    return out


def card_anniversary(card_rec):
    """MM-DD from the ledger card record: explicit `anniversary`, else `opened_on`."""
    if card_rec.get("anniversary"):
        return card_rec["anniversary"]
    if card_rec.get("opened_on"):
        return card_rec["opened_on"][5:10]
    return None
