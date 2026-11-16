#!/usr/bin/env python3
"""Card credits: allowance, what posted, what is left, and by when.

Usage:
  credits.py --ledger L --transactions T.json [T2.json …] [--today YYYY-MM-DD] [--year YYYY]
             [--facts DIR] [--card CARD_ID] [--format json|md] [--proposals batch.json]

Evidence rules (spec «What it does»): a posted statement credit is proven only by a
posted (not pending) transaction or by a credit already recorded in the ledger. Without
one for a covered period the credit is «no credit posted» (likely not used); without
coverage it is «unknown»; credits that never show at the bank (app wallets, hotel folios)
are «ask the person» unless the person told us. Each transaction counts for one benefit
only, a reversal comes off the credit it reverses, and nothing counts above the allowance.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402

EPS = 0.005
VISIBLE = {"statement_credit"}
MONEY_KINDS = {"statement_credit", "wallet_credit", "folio_credit", "percentage_credit", "membership_credit"}
EVENT_PERIODS = {"one_time", "per_stay", "per_booking", "ongoing"}
EVENT_LABELS = {"one_time": "one-time", "per_stay": "per stay", "per_booking": "per booking",
                "ongoing": "ongoing"}
REFUND_RE = re.compile(r"(?<![A-Z])(REFUND|REFUNDED|RETURN|RETURNED|CHARGEBACK)(?![A-Z])")
KNOWN = lambda p: p["status"] not in ("unknown", "ask")  # noqa: E731


def load_txns(paths):
    """Read normalized files; the same transaction in two files counts once; coverage windows merge."""
    accounts, txns, seen = {}, [], {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if d.get("contract") != "finerd-points/transactions@1":
            raise SystemExit(f"{p}: not a normalized transactions file (run normalize.py first)")
        for a in d["accounts"]:
            prev = accounts.get(a["account_id"])
            if prev is None:
                accounts[a["account_id"]] = {**a, "coverage": dict(a["coverage"])}
                continue
            pc, ac = prev["coverage"], a["coverage"]
            if pc.get("from") and pc.get("to") and ac.get("from") and ac.get("to"):
                one = dt.timedelta(days=1)
                p0, p1 = dt.date.fromisoformat(pc["from"]), dt.date.fromisoformat(pc["to"])
                a0, a1 = dt.date.fromisoformat(ac["from"]), dt.date.fromisoformat(ac["to"])
                if a0 > p1 + one or a1 < p0 - one:
                    prev["complete"] = False  # a gap between the files: never pretend it is covered
                    prev["coverage_note"] = "The supplied files leave a gap in dates; periods inside it read unknown."
            froms = [x for x in (pc.get("from"), ac.get("from")) if x]
            tos = [x for x in (pc.get("to"), ac.get("to")) if x]
            pc["from"] = min(froms) if froms else None
            pc["to"] = max(tos) if tos else None
            prev["complete"] = prev.get("complete", True) and a.get("complete", True)
            if prev.get("scope") != a.get("scope"):
                prev["scope"] = "filtered"
        for t in d["transactions"]:
            key = (t["account_id"], t["id"])
            if key not in seen:
                seen[key] = len(txns)
                txns.append(t)
            elif txns[seen[key]].get("pending") and not t.get("pending"):
                txns[seen[key]] = t  # the posted copy replaces the pending one
    return accounts, txns


def coverage_state(acc, start, end):
    if not acc or not acc["coverage"].get("from") or not acc["coverage"].get("to"):
        return "none"
    cf = dt.date.fromisoformat(acc["coverage"]["from"])
    ct = dt.date.fromisoformat(acc["coverage"]["to"])
    if cf <= start and ct >= end and acc.get("complete", True):
        return "full"
    if ct < start or cf > end:
        return "none"
    return "partial"


def _kw_hit(desc, keywords):
    """Longest keyword found as a whole word (so «ZO» never matches «AMAZON»)."""
    d = (desc or "").upper()
    hits = [k for k in keywords if re.search(r"(?<![A-Z0-9])" + re.escape(k) + r"(?![A-Z0-9])", d)]
    return max(hits, key=len) if hits else None


def safe_text(text, n=120):
    """A bank description for a note: long digit runs (reference, ticket or card numbers) are cut."""
    return re.sub(r"\d[\d -]{6,}\d", "…", text or "")[:n]


def is_credit_txn(t):
    """Money back onto the card that looks like a statement credit (never a payment or a merchant refund)."""
    if t["direction"] != "credit" or t["kind"] in ("payment", "transfer"):
        return False
    desc = (t["description"] or "").upper()
    if REFUND_RE.search(desc) or t["kind"] == "refund":
        return False
    return t["kind"] == "credit" or "CREDIT" in desc


def is_reversal(t):
    return t["direction"] == "debit" and bool(t.get("reversal_hint") or t.get("reversal_of"))


def recognize(contribs, cap):
    """What really counts from a set of credits and reversals.

    Each reversal comes off the credit it reverses (unlinked reversals come off the latest credits);
    then the net credits fill the allowance in date order. Returns (total, {posting year: amount},
    matched-above-cap amount). A reversal of a credit that did not fit under the cap removes nothing
    that was counted."""
    credits = sorted((c for c in contribs if c["amount"] > 0), key=lambda c: (c["date"], str(c["id"])))
    net_of = {c["id"]: c["amount"] for c in credits}
    orphan = 0.0
    for r in (c for c in contribs if c["amount"] < 0):
        tgt = r.get("reverses")
        if tgt in net_of:
            net_of[tgt] = max(net_of[tgt] + r["amount"], 0.0)
        else:
            orphan += -r["amount"]
    for c in reversed(credits):
        take = min(net_of[c["id"]], orphan)
        net_of[c["id"]] -= take
        orphan -= take
    room, total, by_year, over = cap, 0.0, {}, 0.0
    for c in credits:
        rec = min(net_of[c["id"]], room)
        over += net_of[c["id"]] - rec
        room -= rec
        total += rec
        y = c["date"][:4]
        by_year[y] = round(by_year.get(y, 0.0) + rec, 2)
    return round(total, 2), by_year, round(over, 2)


def _periods(b, start, horizon_end, anniv, ys, lookback=None):
    if b["period"] in EVENT_PERIODS:
        # Not periodic: the report year is the window for credits that actually posted.
        return [(str(ys.year), ys, dt.date(ys.year, 12, 31))]
    per = ff.periods_between(b["period"], lookback or start, horizon_end, anniv)
    per = [p for p in per if ff._active(b, p[1]) or ff._active(b, p[2])]
    # Keep earlier periods only when they reach into the lookback window for posting.
    return [p for p in per if p[2] >= (lookback or start)]


def analyze(led, catalog, accounts, txns, today, year, only_card=None):
    obs = [o for o in fl.active_observations(led) if o["as_of"] <= today.isoformat()]  # evidence as of today
    ys, ye = dt.date(year, 1, 1), dt.date(year, 12, 31)
    horizon_end = min(ye, today) if year < today.year else today
    report_cur = led["_meta"]["setup"].get("report_currency") or "USD"
    finance_app = led["_meta"]["setup"].get("finance_app") or "finance app"
    result_cards, proposals, questions = [], [], []
    matched_ids = set()
    shared = {}

    for card in led["cards"]:
        if only_card and card["id"] != only_card:
            continue
        cf = catalog["cards"].get(card.get("catalog_ref") or "")
        link = card.get("finance_link") or {}
        acc = accounts.get(link.get("account_id"))
        card_txns = [t for t in txns if link.get("account_id") and t["account_id"] == link["account_id"]]
        recorded_refs = {o["source"].get("ref") for o in obs
                         if o["field"] in ("credited", "reversed") and o["subject"].startswith(f"benefit:{card['id']}/")}
        entry = {"card": card["id"], "nickname": card["nickname"], "catalog_ref": card.get("catalog_ref"),
                 "person": card.get("person"), "benefits": [], "coverage": acc["coverage"] if acc else None,
                 "coverage_note": acc.get("coverage_note") if acc else "No transactions connected for this card."}
        # Annual fees seen on the card (cost lines for the yearly report), catalog or not.
        for t in card_txns:
            if t["kind"] == "fee" and t["date"].startswith(str(year)) and not t.get("pending"):
                cid = f"fee-{card['id']}-{t['date']}-{re.sub(r'[^a-z0-9]', '', str(t['id']).lower())[:8]}"
                if not any(c["id"] == cid for c in led["costs"]):
                    op = {"op": "add_cost", "id": cid, "date": t["date"], "kind": "annual_fee",
                          "amount": t["amount"], "currency": t["currency"], "card": card["id"],
                          "person": card.get("person"), "description": safe_text(t["description"]),
                          "source": {"kind": "finance_app", "name": finance_app, "ref": t["id"]}}
                    if t["currency"] != report_cur:
                        op["note"] = f"in {t['currency']}: add fx_rate and fx_source before recording"
                    proposals.append(op)
        if not acc and cf:
            questions.append(f"For your {card['nickname']}, open the issuer's benefits page so I can read which credits "
                             f"you used, give me its statement or CSV, or tell me which credits you used.")
        if not cf:
            entry["note"] = "This card is not in the facts catalog yet; credits cannot be tracked."
            result_cards.append(entry)
            continue
        if (cf.get("currency") or report_cur) != report_cur:
            entry["note"] = (f"This card's terms are in {cf.get('currency')} and your report is in {report_cur}; "
                             f"card credits across currencies are not supported in this version.")
            result_cards.append(entry)
            continue
        entry["facts_checked_on"] = cf["checked_on"]
        entry["facts_stale"] = ff.is_stale(cf, today)
        entry["rule_version"] = cf["rule_version"]
        terms_from = cf.get("terms_from")
        anniv = ff.card_anniversary(card)
        start = max(ys, dt.date.fromisoformat(card["opened_on"])) if card.get("opened_on") else ys
        # Credits for a period that ended just before the year can post inside it; such periods are
        # visited for money that posted in the year, never shown as current or counted as allowance.
        lookback = start - dt.timedelta(days=90)
        if card.get("opened_on"):
            lookback = max(lookback, dt.date.fromisoformat(card["opened_on"]))
        money_benefits = [b for b in cf["benefits"] if b["kind"] in MONEY_KINDS and b.get("amount") is not None]

        # 1. Each transaction to exactly one benefit: longest whole-word keyword, catalog order on ties,
        #    benefit active on the transaction date, nothing dated after today.
        assign, hits, off_dates, ambiguous = {}, {}, {}, {}
        by_id = {b["id"]: b for b in money_benefits}

        def pick(cands, amount):
            """Longest keyword wins; on a tie, the benefit whose allowance fits the amount best."""
            top = max(len(h) for _, h in cands)
            tied = [(bid, h) for bid, h in cands if len(h) == top]
            if len(tied) == 1:
                return tied[0], False
            fits = sorted((c for c in tied if float(by_id[c[0]]["amount"]) + EPS >= amount),
                          key=lambda c: float(by_id[c[0]]["amount"]))
            return (fits[0] if fits else max(tied, key=lambda c: float(by_id[c[0]]["amount"]))), True

        for t in card_txns:
            d = dt.date.fromisoformat(t["date"])
            posted = dt.date.fromisoformat(t["posted_date"]) if t.get("posted_date") else d
            if posted > today or not (is_credit_txn(t) or is_reversal(t)):
                continue
            active, outside = [], []
            for b in money_benefits:
                kws = (b.get("match") or {}).get("keywords") or []
                if b["evidence"] not in VISIBLE or not kws:
                    continue
                hit = _kw_hit(t["description"], kws)
                if hit:
                    (active if ff._active(b, d) else outside).append((b["id"], hit))
            if active:
                best, amb = pick(active, t["amount"])
            elif outside:
                # A real credit beats a catalog date: count it, and say the catalog date may be wrong.
                best, amb = pick(outside, t["amount"])
                off_dates[t["id"]] = True
            else:
                continue
            assign[t["id"]], hits[t["id"]] = best
            if amb:
                ambiguous[t["id"]] = True
        # A reversal that names its credit goes to that credit's benefit, whatever its wording.
        for t in card_txns:
            posted_r = t.get("posted_date") or t["date"]
            if is_reversal(t) and t.get("reversal_of") in assign and dt.date.fromisoformat(posted_r) <= today:
                assign[t["id"]] = assign[t["reversal_of"]]
                hits[t["id"]] = hits.get(t["reversal_of"], "")
        # 2. A reversal belongs to the period of the credit it reverses. Reversals are matched in date
        #    order to credits that still have a balance (an explicit reversal_of wins), so two reversals
        #    never both come off one credit while another is still standing.
        eff_date = {t["id"]: t["date"] for t in card_txns if t["id"] in assign}
        orphan_reversals, rev_target, void_reversals = set(), {}, {}
        def counted(x):  # the same exclusions the accounting below applies
            return not x.get("pending") and x["currency"] == report_cur
        balance = {t["id"]: t["amount"] for t in card_txns if t["id"] in assign and is_credit_txn(t) and counted(t)}
        for t in sorted((x for x in card_txns if x["id"] in assign and is_reversal(x) and counted(x)),
                        key=lambda x: (x["date"], str(x["id"]))):
            if t.get("reversal_of"):
                # An explicit link is never redirected: a reversal of a credit that is not counted (pending,
                # other currency) or not in these transactions takes nothing off any other credit.
                named = next((x for x in card_txns if x["id"] == t["reversal_of"] and is_credit_txn(x)), None)
                if named is not None and assign.get(named["id"]) == assign[t["id"]] and counted(named):
                    eff_date[t["id"]] = named["date"]
                    rev_target[t["id"]] = named["id"]
                    balance[named["id"]] = max(balance.get(named["id"], 0) - t["amount"], 0.0)
                else:
                    void_reversals[t["id"]] = ("the credit it reverses is not counted" if named is not None
                                               else "the credit it reverses is not in these transactions")
                    if named is not None:
                        eff_date[t["id"]] = named["date"]
                continue
            prior = [x for x in card_txns if assign.get(x["id"]) == assign[t["id"]] and is_credit_txn(x)
                     and counted(x) and x["date"] <= t["date"]]
            explicit = None
            open_ = [x for x in prior if balance.get(x["id"], 0) > EPS]
            same = [x for x in open_ if abs(balance[x["id"]] - t["amount"]) < EPS]
            orig = explicit or (max(same, key=lambda x: (x["date"], str(x["id"]))) if same else None) or \
                (max(open_, key=lambda x: (x["date"], str(x["id"]))) if open_ else None)
            if orig:
                eff_date[t["id"]] = orig["date"]
                rev_target[t["id"]] = orig["id"]
                balance[orig["id"]] = max(balance.get(orig["id"], 0) - t["amount"], 0.0)
            else:
                orphan_reversals.add(t["id"])

        for b in money_benefits:
            per = _periods(b, start, horizon_end, anniv, ys, lookback)
            if not per:
                if b["period"] == "card_year" and not anniv:
                    questions.append(f"When did you open your {card['nickname']}? Its {b['name']} resets on the "
                                     f"card anniversary.")
                continue
            match = b.get("match") or {}
            gated = b.get("requires")
            event_like = b["period"] in EVENT_PERIODS
            enrolled = fl.current(led, f"benefit:{card['id']}/{b['id']}", "enrolled", obs)
            bent = {"benefit": b["id"], "name": b["name"], "kind": b["kind"], "period": b["period"],
                    "retired": bool(b.get("effective_to") and b["effective_to"] < today.isoformat()),
                    "cap_only": b["kind"] == "percentage_credit", "event_like": event_like, "gated": bool(gated),
                    "requires": gated, "descriptor_verified": bool(match.get("verified")),
                    "evidence": b["evidence"], "enrollment": b["enrollment"],
                    "enrolled": enrolled["value"] if enrolled else None, "shared_group": b.get("shared_group"),
                    "fact_checked_on": ff.fact_checked_on(cf, b), "fact_state": ff.fact_state(cf, b, today),
                    "periods": []}
            lag = match.get("posting_lag_days")
            visible = b["evidence"] in VISIBLE
            for key, p_start, p_end in per:
                subj = f"benefit:{card['id']}/{b['id']}/{key}"
                credited = pending_amt = reversed_amt = 0.0
                ids, notes, seen_refs = [], [], set()
                contribs = []  # credits and reversals that count, with posting dates and links
                confidence = "confirmed"
                for t in card_txns:
                    if assign.get(t["id"]) != b["id"]:
                        continue
                    d = dt.date.fromisoformat(eff_date[t["id"]])
                    if not (p_start <= d <= p_end):
                        continue
                    seen_refs.add(t["id"])
                    if t["currency"] != report_cur:
                        notes.append(f"{t['date']} {t['currency']} {t['amount']:.2f} not converted to {report_cur}; "
                                     f"not counted")
                        continue
                    if t.get("pending"):
                        if is_reversal(t):
                            notes.append(f"{t['date']} reversal of {t['amount']:.2f} is still pending; not counted yet")
                        else:
                            pending_amt += t["amount"]
                            notes.append(f"{t['date']} credit of {t['amount']:.2f} is still pending; not counted yet")
                        continue
                    if is_reversal(t) and t["id"] in void_reversals:
                        notes.append(f"{t['date']} reversal of {t['amount']:.2f} not counted: {void_reversals[t['id']]}")
                        continue
                    if is_reversal(t):
                        reversed_amt += t["amount"]
                        ids.append(t["id"])
                        contribs.append({"id": t["id"], "date": t.get("posted_date") or t["date"], "amount": -t["amount"],
                                         "reverses": rev_target.get(t["id"])})
                        notes.append(f"{t['date']} reversal of {t['amount']:.2f}"
                                     + (" (no earlier credit found)" if t["id"] in orphan_reversals else ""))
                        if t["id"] not in recorded_refs:
                            proposals.append({
                                "op": "observe", "subject": subj, "field": "reversed", "value": t["amount"],
                                "unit": t["currency"], "as_of": t.get("posted_date") or t["date"],
                                "source": {"kind": "finance_app", "name": finance_app, "ref": t["id"],
                                           "reverses": rev_target.get(t["id"])},
                                "confidence": "confirmed", "method": "reversal of a matched credit",
                                "note": safe_text(t["description"])})
                        continue
                    credited += t["amount"]
                    ids.append(t["id"])
                    contribs.append({"id": t["id"], "date": t.get("posted_date") or t["date"], "amount": t["amount"]})
                    matched_ids.add(t["id"])
                    if ambiguous.get(t["id"]):
                        confidence = "unsure"
                        notes.append(f"the {t['date']} credit matched more than one benefit; assigned to this one "
                                     f"by its amount")
                        questions.append(f"Which benefit was the {t['date']} credit of ${t['amount']:,.2f} on your "
                                         f"{card['nickname']} («{safe_text(t['description'], 60)}»)? I counted it as "
                                         f"{b['name']}.")
                    if off_dates.get(t["id"]):
                        notes.append(f"the {t['date']} credit posted outside the catalog's dates for this benefit; "
                                     f"the catalog date may be wrong")
                    if lag and (dt.date.fromisoformat(t["date"]) - p_start).days < lag and p_start > start:
                        notes.append(f"the {t['date']} credit may belong to the previous period "
                                     f"(credits can post up to {lag} days late)")
                    if t["id"] not in recorded_refs:
                        proposals.append({
                            "op": "observe", "subject": subj, "field": "credited", "value": t["amount"],
                            "unit": t["currency"], "as_of": t.get("posted_date") or t["date"],
                            "source": {"kind": "finance_app", "name": finance_app, "ref": t["id"]},
                            "confidence": ("unsure" if ambiguous.get(t["id"]) else
                                           "confirmed" if t["kind"] == "credit" else "likely"),
                            "method": f"transaction description matched {hits[t['id']]}"
                                      + ("; more than one benefit matched, assigned by amount" if ambiguous.get(t["id"]) else ""),
                            "note": safe_text(t["description"]),
                        })
                # Credits already recorded in the ledger count even when this run's transactions
                # do not include them (history lives in the ledger, not in the connector).
                for o in obs:
                    if o["subject"] != subj or o["field"] not in ("credited", "reversed") \
                            or o["source"].get("ref") in seen_refs or o["as_of"] > today.isoformat():
                        continue
                    if (o.get("unit") or report_cur) != report_cur:
                        notes.append(f"recorded {o['field']} {o.get('unit')} {o['value']} not converted; not counted")
                        continue
                    if o["field"] == "credited":
                        credited += float(o["value"])
                        contribs.append({"id": o["source"].get("ref") or o["id"], "date": o["as_of"],
                                         "amount": float(o["value"])})
                        if o.get("confidence") == "unsure":
                            confidence = "unsure"
                            notes.append(f"the recorded {o['as_of']} credit's benefit is not certain")
                    else:
                        reversed_amt += float(o["value"])
                        contribs.append({"id": o["source"].get("ref") or o["id"], "date": o["as_of"],
                                         "amount": -float(o["value"]), "reverses": o["source"].get("reverses")})
                    ids.append(o["source"].get("ref") or o["id"])
                # The issuer's own benefits page («$X used this period») is issuer-reported usage: it sets used and
                # remaining for the period and is never added on top of credit transactions (spec v2, appendix C).
                issuer = sorted((o for o in obs if o["subject"] == subj and o["field"] == "used_amount"
                                 and o["source"].get("kind") == "issuer_page"), key=lambda o: o["as_of"])
                issuer = issuer[-1] if issuer else None
                said = fl.current(led, subj, "used_amount",
                                  [o for o in obs if o["source"].get("kind") != "issuer_page"])  # the person's word
                if said is not None:
                    unit = next((o.get("unit") for o in obs if o["id"] == said["observation"]), None)
                    if unit and unit != report_cur:
                        notes.append(f"your answer was in {unit}, not {report_cur}; not counted")
                        said = None
                cov = coverage_state(acc, p_start, min(p_end, today))
                allowance = float(b["amount"])
                cap = allowance if b["period"] not in ("per_stay", "per_booking", "ongoing") else float("inf")
                net, by_year, over = recognize(contribs, cap)
                is_current = p_start <= today <= p_end and not event_like
                prior = p_end < ys
                issuer_used = None
                if issuer is not None and said is None and (issuer.get("unit") or report_cur) == report_cur:
                    iv = min(float(issuer["value"]), cap)
                    if iv <= EPS and issuer.get("caveat") == "may_lag" and net <= EPS:
                        issuer_used = "lagging"  # «$0 received» from a tracker that warns it may lag: unknown
                        notes.append(f"the issuer's tracker showed $0 on {issuer['as_of']} and says it may lag")
                    else:
                        issuer_used = iv
                        if contribs and abs(net - iv) > EPS:
                            notes.append(f"the issuer's page shows {iv:.2f} used on {issuer['as_of']}, the transactions "
                                         f"show {net:.2f}")
                        elif not contribs:
                            notes.append(f"issuer-reported on {issuer['as_of']}")
                        tx_net = net
                        net = iv
                        by_year = {str(p_start.year): iv}  # the benefit period's year, not the read date's
                        contribs = contribs if contribs else [{"id": f"issuer:{issuer['id']}", "date": issuer["as_of"],
                                                               "amount": iv}]
                        confidence = "issuer-reported"
                if said is not None:
                    net = min(float(said["value"]), cap)
                    if float(said["value"]) > cap + EPS:
                        notes.append(f"your answer {float(said['value']):.2f} is above the {allowance:.2f} allowance; "
                                     f"counted as {allowance:.2f}")
                    by_year = {said["as_of"][:4]: net}
                    contribs = [{"id": f"said:{card['id']}", "date": said["as_of"], "amount": net}]
                    confidence = "person said"
                elif over > EPS:
                    notes.append(f"{over:.2f} matched above the {allowance:.2f} allowance and is not counted; "
                                 f"check the matching")
                if issuer_used == "lagging":
                    status, confidence = "unknown", "unknown"
                elif isinstance(issuer_used, float) and ids and abs(tx_net - issuer_used) > EPS:
                    status, confidence = "conflicting", "conflicting"
                elif not visible and said is None and net <= EPS and issuer_used is None:
                    status, confidence = "ask", "unknown"
                elif event_like:
                    status = "used" if net > EPS else "available (not periodic)"
                elif net >= allowance - EPS:
                    status = "used"
                elif net > EPS:
                    status = "partly used"
                elif b["kind"] == "percentage_credit":
                    status, confidence = "available (percentage back, up to the cap)", "likely"
                elif gated:
                    status, confidence = "ask", "unknown"
                    notes.append(f"available only after: {gated.get('note') or gated.get('kind')}")
                elif is_current:
                    if cov == "full":
                        status, confidence = "not used yet", "likely"
                    else:
                        status, confidence = "unknown", "unknown"
                        if cov == "partial":
                            notes.append(f"transactions only reach {acc['coverage'].get('to')}")
                elif cov == "full":
                    status, confidence = "no credit posted", ("likely" if match.get("verified") else "unsure")
                    if not match.get("verified"):
                        notes.append("the bank's description for this credit is not verified yet; it may have "
                                     "posted under other words")
                else:
                    status, confidence = "unknown", "unknown"
                realized = None
                if terms_from and p_start.isoformat() < terms_from:
                    # The catalog does not vouch for this period's terms: no allowance, only what really posted.
                    notes.append(f"the catalog has this card's terms only from {terms_from}; the allowance for "
                                 f"this period is unknown")
                    realized = net if net > EPS else None
                    status, confidence = "unknown", "unsure"
                if status in ("ask", "unknown") or event_like:
                    remaining = None
                elif status == "conflicting":
                    remaining = round(max(allowance - net, 0.0), 2)
                else:
                    remaining = round(max(allowance - net, 0.0), 2)
                if status == "ask":
                    by_year = {}
                if reversed_amt > EPS and status != "ask":
                    notes.append("a credit was reversed")
                bent["periods"].append({
                    "key": key, "start": p_start.isoformat(), "end": p_end.isoformat(), "current": is_current,
                    "in_year": p_start.year == year and not prior, "prior": prior, "allowance": allowance,
                    "credited": round(credited, 2),
                    "pending": round(pending_amt, 2), "reversed": round(reversed_amt, 2),
                    "used": (net if status not in ("ask", "unknown") else realized), "remaining": remaining,
                    "used_by_year": by_year, "contribs": contribs if status != "ask" else [],
                    "status": status, "confidence": confidence, "coverage": cov, "transactions": ids,
                    "notes": notes,
                    "issuer_reported": (None if not isinstance(issuer_used, float) else
                                        {"used": issuer_used, "as_of": issuer["as_of"],
                                         "transactions_used": round(tx_net, 2) if ids else None}),
                })
                if status == "ask" and is_current and not gated:
                    questions.append(f"Have you used this period's {b['name']} on your {card['nickname']} "
                                     f"(${allowance:,.2f} until {p_end.isoformat()})? It does not show at the bank.")
            if b["enrollment"] == "required" and bent["enrolled"] is None:
                posted = any(p["credited"] > EPS for p in bent["periods"])
                bent["enrollment_note"] = ("a credit posted, so enrollment is likely" if posted else
                                           "enrollment not confirmed — the issuer requires it")
            bent["report_year"] = year
            _year_to_date(bent)
            if b.get("shared_group"):
                shared.setdefault((card.get("person"), b["shared_group"]), []).append((card["id"], bent))
            entry["benefits"].append(bent)
        result_cards.append(entry)

    # One allowance per person for shared benefits (e.g. Amex venue concessions): usage on every
    # card is pooled into the first card's line; the others show «counted on …».
    shared_notes = []
    for (person, group), items in shared.items():
        if len(items) < 2:
            continue
        shared_notes.append({"person": person, "group": group, "cards": [c for c, _ in items],
                             "note": "One allowance per person across these cards; usage is pooled and counted once."})
        first_card, first = items[0]
        first["pooled_used"] = {c: other["year_to_date"]["used"] for c, other in items}
        for p in first["periods"]:
            combined = [dict(c_, id=f"{card_id}:{c_['id']}",
                             reverses=(f"{card_id}:{c_['reverses']}" if c_.get("reverses") else None))
                        for card_id, other in items for op_ in other["periods"] if op_["key"] == p["key"]
                        for c_ in (op_.get("contribs") or [])]
            pooled, pby, _ = recognize(combined, p["allowance"])  # one cap for the whole shared period
            p["used_by_year"] = pby
            if pooled > EPS:
                p["used"] = pooled
                p["remaining"] = round(max(p["allowance"] - p["used"], 0.0), 2)
                if not first["cap_only"]:
                    p["status"] = "used" if p["used"] >= p["allowance"] - EPS else "partly used"
                p["notes"].append(f"pooled across {', '.join(c for c, _ in items)}")
        _year_to_date(first)
        for _, bent in items[1:]:
            bent["counted_on_card"] = first_card
            for p in bent["periods"]:
                p["used"], p["remaining"] = None, None
            bent["year_to_date"] = {k: 0 if isinstance(v, (int, float)) else v
                                    for k, v in bent["year_to_date"].items()}

    assigned_all = set(matched_ids)
    unmatched = [t for t in txns if is_credit_txn(t) and t["id"] not in assigned_all and not t.get("pending")
                 and "CREDIT" in (t["description"] or "").upper() and t["date"].startswith(str(year))
                 and dt.date.fromisoformat(t["date"]) <= today
                 and any((c.get("finance_link") or {}).get("account_id") == t["account_id"] for c in led["cards"])]
    return {
        "as_of": today.isoformat(), "year": year, "currency": report_cur,
        "cards": result_cards, "shared_benefits": shared_notes,
        "unmatched_credits": [{"id": t["id"], "date": t["date"], "amount": t["amount"], "currency": t["currency"],
                               "description": t["description"], "account_id": t["account_id"],
                               "pending": bool(t.get("pending"))} for t in unmatched],
        "questions": questions, "proposed_batch": proposals,
    }


def _year_to_date(bent, year=None):
    """Allowances count in the year their period starts; money that posted counts in the calendar
    year of its date (an anniversary period can span two years)."""
    year = year or bent.get("report_year")
    inyr = [p for p in bent["periods"] if p["in_year"]]
    done = [p for p in inyr if not p["current"]]
    bent["current"] = next((p for p in bent["periods"] if p["current"]), None)
    bent["year_to_date"] = {
        "allowance": round(sum(p["allowance"] for p in inyr), 2),
        "used": round(sum((p.get("used_by_year") or {}).get(str(year), 0.0) for p in bent["periods"]), 2),
        "not_used_in_ended_periods": round(sum(p["remaining"] or 0 for p in done
                                              if p["status"] in ("no credit posted", "partly used")), 2),
        "unknown_periods": sum(1 for p in inyr if p["status"] in ("unknown", "ask")),
    }


def totals(res):
    """Used counts every credit that really posted (including percentage-back and one-time credits).
    «Available» counts only periodic money credits: percentage caps, one-time credits, credits that
    open only after a condition, and shared duplicates are left out of it."""
    bens = [b for c in res["cards"] for b in c["benefits"] if not b.get("counted_on_card")]
    periodic = [b for b in bens if not (b.get("cap_only") or b.get("event_like") or b.get("gated"))]
    used = sum(b["year_to_date"]["used"] for b in bens)
    allowance = sum(p["allowance"] for b in periodic for p in b["periods"] if p["in_year"] and KNOWN(p))
    unknown = sum(p["allowance"] for b in periodic for p in b["periods"] if p["in_year"] and not KNOWN(p))
    open_now = sum((b["current"] or {}).get("remaining") or 0 for b in periodic)
    missed = sum(b["year_to_date"]["not_used_in_ended_periods"] for b in periodic)
    pending = sum(p.get("pending") or 0 for b in bens for p in b["periods"] if p["in_year"])
    return {"used": round(used, 2), "allowance_so_far": round(allowance, 2), "open_this_period": round(open_now, 2),
            "not_used_in_ended_periods": round(missed, 2), "without_evidence": round(unknown, 2),
            "pending": round(pending, 2)}


def to_markdown(res):
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(res.get("currency", "USD"), res.get("currency", "") + " ")
    out = [f"**Card credits, {res['year']}** (as of {res['as_of']}, amounts in {res.get('currency', 'USD')})", ""]
    t = totals(res)
    out.append(f"Credits that posted this year: {sym}{t['used']:,.2f} (including one-time and percentage-back credits). "
               f"Periodic credits available to date: {sym}{t['allowance_so_far']:,.2f}. "
               f"Still open this period: {sym}{t['open_this_period']:,.2f}. "
               f"Not used in periods that already ended: {sym}{t['not_used_in_ended_periods']:,.2f}. "
               f"Credits without evidence either way (no transactions, or not shown by the bank): "
               f"{sym}{t['without_evidence']:,.2f}." + (f" Pending, not counted yet: {sym}{t['pending']:,.2f}."
                                                     if t["pending"] else ""))
    for c in res["cards"]:
        checked = f" — card terms checked {c['facts_checked_on']}" if c.get("facts_checked_on") else ""
        out += ["", f"**{c['nickname']}**" + checked + (", older than 90 days: unverified" if c.get("facts_stale") else "")]
        if c.get("note"):
            out.append(c["note"])
            continue
        if c.get("coverage_note"):
            out.append(f"_{c['coverage_note']}_")
        if not any(b["current"] or b["periods"] for b in c["benefits"]):
            out.append("No money credits to track on this card this year (certificates, status and other "
                       "benefits are covered by the deadlines report).")
            continue
        out.append("| Credit | This period | Used | Left | Ends | Status |")
        out.append("|---|---|---:|---:|---|---|")
        for b in c["benefits"]:
            if b.get("retired") and not b["current"]:
                continue  # an older version of a benefit; its periods still count in the year
            p = b["current"] or (b["periods"][-1] if b["periods"] else None)
            if not p:
                continue
            used = "—" if p["used"] is None else f"{sym}{p['used']:,.2f}"
            left = "—" if p["remaining"] is None else f"{sym}{p['remaining']:,.2f}"
            status = p["status"]
            if b.get("fact_state") == "unverified":
                status += f"; catalog fact unverified (checked {b.get('fact_checked_on')})"
            if b.get("enrollment_note") and "not confirmed" in b["enrollment_note"]:
                status += "; enrollment not confirmed"
            if b.get("gated"):
                status += f"; opens only after {b['requires'].get('note')}"
            if b.get("counted_on_card"):
                status += f"; shared allowance, counted on {b['counted_on_card']}"
            # a per-stay or one-time credit has no period of its own, so no year-end deadline
            period = EVENT_LABELS.get(b["period"], b["period"]) if b.get("event_like") else p["key"]
            ends = "—" if b.get("event_like") else p["end"]
            out.append(f"| {b['name']} | {period} ({sym}{p['allowance']:,.0f}) | {used} | {left} | {ends} | {status} |")
    notes = [(c["nickname"], b["name"], n) for c in res["cards"] for b in c["benefits"]
             for p in ([b["current"]] if b["current"] else b["periods"][-1:]) for n in p["notes"][:2]]
    if notes:
        out += ["", "**Notes**"] + [f"- {card}, {name}: {n}" for card, name, n in notes]
    if res["unmatched_credits"]:
        out += ["", "**Credits I could not match to a benefit**"]
        out += [f"- {u['date']} {u['currency']} {u['amount']:,.2f} «{safe_text(u['description'], 200)}»"
                for u in res["unmatched_credits"]]
    if res["questions"]:
        out += ["", "**Please tell me**"] + [f"- {q}" for q in res["questions"]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--transactions", nargs="*", default=[])
    ap.add_argument("--facts")
    ap.add_argument("--today")
    ap.add_argument("--year", type=int)
    ap.add_argument("--card")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--proposals", help="write the proposed ledger batch to this file")
    a = ap.parse_args()
    try:
        today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
        led = fl.load(a.ledger)
        catalog = ff.load_catalog(a.facts)
        accounts, txns = load_txns(a.transactions)
        res = analyze(led, catalog, accounts, txns, today, a.year or today.year, a.card)
    except fl.LedgerError as e:
        print(json.dumps({"refused": str(e)}))
        sys.exit(2)
    except (ValueError, KeyError, TypeError, FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"refused": f"The input could not be used ({type(e).__name__}: {e})."}))
        sys.exit(2)
    res["totals"] = totals(res)
    if a.proposals:
        Path(a.proposals).write_text(json.dumps(res["proposed_batch"], indent=1, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    if a.format == "md":
        print(to_markdown(res))
    else:
        print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
