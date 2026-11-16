"""Card credits read from the issuer's own benefits page (spec v2, appendices C and D)."""
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import credits  # noqa: E402
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402

TODAY = dt.date(2026, 11, 16)


def ledger(*obs, link=False):
    led = fl.new_ledger("T", storage="folder")
    card = {"op": "add_card", "id": "gold", "person": "me", "nickname": "Gold", "catalog_ref": "amex-gold",
            "opened_on": "2024-03-13"}
    if link:
        card["finance_link"] = {"app": "x", "account_id": "acc1", "account_name": "Gold"}
    b = [card] + list(obs)
    fl.apply_batch(led, b, fl.preview_batch(led, b)[0])
    return led


def issuer(subject, value, caveat=None, as_of="2026-11-16"):
    o = {"op": "observe", "subject": subject, "field": "used_amount", "value": value,
         "source": {"kind": "issuer_page", "name": "Amex benefits tracker"}, "as_of": as_of, "confidence": "confirmed",
         "note": "Resy credit $50.00 of $50.00 received"}
    if caveat:
        o["caveat"] = caveat
    return o


def period(res, bid, key):
    b = next(x for x in res["cards"][0]["benefits"] if x["benefit"] == bid)
    return next(p for p in b["periods"] if p["key"] == key)


class IssuerReported(unittest.TestCase):
    catalog = ff.load_catalog(ROOT / "shared" / "facts")

    def test_without_a_finance_app_the_issuer_page_sets_used(self):
        led = ledger(issuer("benefit:gold/resy-credit/2026-H2", 50))
        res = credits.analyze(led, self.catalog, {}, [], TODAY, 2026)
        p = period(res, "resy-credit", "2026-H2")
        self.assertEqual((p["status"], p["used"], p["remaining"]), ("used", 50.0, 0.0))
        self.assertEqual(p["confidence"], "issuer-reported")
        self.assertEqual(p["used_by_year"], {"2026": 50.0})

    def test_zero_from_a_lagging_tracker_is_unknown_not_unused(self):
        led = ledger(issuer("benefit:gold/dining-credit/2026-11", 0, caveat="may_lag"))
        res = credits.analyze(led, self.catalog, {}, [], TODAY, 2026)
        p = period(res, "dining-credit", "2026-11")
        self.assertEqual(p["status"], "unknown")
        self.assertIsNone(p["remaining"])

    def test_issuer_and_transactions_disagree(self):
        led = ledger(issuer("benefit:gold/resy-credit/2026-H2", 25), link=True)
        acc = {"acc1": {"account_id": "acc1", "name": "Gold", "complete": True,
                        "coverage": {"from": "2026-01-01", "to": "2026-11-16"}}}
        tx = [{"id": "t1", "date": "2026-09-10", "amount": 50, "direction": "credit", "kind": "credit",
               "description": "AMEX RESY CREDIT", "account_id": "acc1", "currency": "USD", "pending": False,
               "posted_date": None, "merchant": None, "category": None, "reversal_of": None, "reversal_hint": False}]
        res = credits.analyze(led, self.catalog, acc, tx, TODAY, 2026)
        p = period(res, "resy-credit", "2026-H2")
        self.assertEqual(p["status"], "conflicting")
        self.assertEqual(p["issuer_reported"], {"used": 25.0, "as_of": "2026-11-16", "transactions_used": 50.0})
        self.assertTrue(any("transactions show 50.00" in n for n in p["notes"]))

    def test_issuer_and_transactions_agree_counted_once(self):
        led = ledger(issuer("benefit:gold/resy-credit/2026-H2", 50), link=True)
        acc = {"acc1": {"account_id": "acc1", "name": "Gold", "complete": True,
                        "coverage": {"from": "2026-01-01", "to": "2026-11-16"}}}
        tx = [{"id": "t1", "date": "2026-09-10", "amount": 50, "direction": "credit", "kind": "credit",
               "description": "AMEX RESY CREDIT", "account_id": "acc1", "currency": "USD", "pending": False,
               "posted_date": None, "merchant": None, "category": None, "reversal_of": None, "reversal_hint": False}]
        res = credits.analyze(led, self.catalog, acc, tx, TODAY, 2026)
        p = period(res, "resy-credit", "2026-H2")
        self.assertEqual((p["status"], p["used"]), ("used", 50.0))  # never 100

    def test_person_word_still_wins(self):
        person = {"op": "observe", "subject": "benefit:gold/resy-credit/2026-H2", "field": "used_amount", "value": 30,
                  "source": {"kind": "person"}, "as_of": "2026-11-16", "confidence": "confirmed"}
        led = ledger(issuer("benefit:gold/resy-credit/2026-H2", 50), person)
        res = credits.analyze(led, self.catalog, {}, [], TODAY, 2026)
        p = period(res, "resy-credit", "2026-H2")
        self.assertEqual((p["confidence"], p["used"]), ("person said", 30.0))


if __name__ == "__main__":
    unittest.main()
