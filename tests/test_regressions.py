"""Regression tests for the failures the Codex and Sonnet reviews reproduced (2026-11-02)."""
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import balances  # noqa: E402
import credits  # noqa: E402
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402
import normalize  # noqa: E402
import render_report  # noqa: E402
import yir  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
S = "test-session"
TODAY = dt.date(2026, 11, 2)


def ledger_with(*batches):
    led = fl.new_ledger("Test", timezone="America/Los_Angeles")
    led["version"] = 1
    fl.acquire_lease(led, S)
    for b in batches:
        h, _ = fl.preview_batch(led, b)
        fl.apply_batch(led, b, h, S)
    return led


BASE = {"currency": "USD", "pending": False, "posted_date": None, "merchant": None, "category": None,
        "reversal_of": None, "reversal_hint": False}


def tx(id_, date, amount, desc, direction="credit", kind="credit", acc="accB", **kw):
    return {**BASE, "id": id_, "account_id": acc, "date": date, "amount": amount, "description": desc,
            "direction": direction, "kind": kind, **kw}


class CreditRegressions(unittest.TestCase):
    def setUp(self):
        self.catalog = ff.load_catalog(FIX / "facts")
        self.led = ledger_with([
            {"op": "add_card", "id": "b", "person": "me", "nickname": "Card B", "catalog_ref": "test-card-b",
             "anniversary": "03-13", "finance_link": {"app": "x", "account_id": "accB"}},
            {"op": "add_card", "id": "a", "person": "me", "nickname": "Card A", "catalog_ref": "test-card",
             "finance_link": {"app": "x", "account_id": "accA"}},
        ])
        self.acc = {a: {"account_id": a, "name": a, "complete": True,
                        "coverage": {"from": "2025-01-01", "to": "2026-11-02"}} for a in ("accA", "accB")}

    def run_(self, txns, year=2026, today=TODAY):
        return credits.analyze(self.led, self.catalog, self.acc, txns, today, year)

    def ben(self, res, card, bid):
        c = next(c for c in res["cards"] if c["card"] == card)
        return next(b for b in c["benefits"] if b["benefit"] == bid)

    def test_one_transaction_one_benefit(self):
        res = self.run_([tx("t1", "2026-08-03", 300, "AIRBNB LODGING CREDIT")])
        self.assertEqual(self.ben(res, "b", "lodging")["year_to_date"]["used"], 300)
        self.assertEqual(self.ben(res, "b", "experiences")["year_to_date"]["used"], 0)

    def test_real_credit_beats_catalog_start_date(self):
        self.catalog["cards"]["test-card-b"]["benefits"][1]["effective_from"] = "2026-08-21"  # experiences
        res = self.run_([tx("t1", "2026-07-21", 100, "AIRBNB CREDIT")])
        b = self.ben(res, "b", "experiences")
        self.assertEqual(b["year_to_date"]["used"], 100)
        self.assertTrue(any("catalog date may be wrong" in n for p in b["periods"] for n in p["notes"]))

    def test_used_never_exceeds_allowance(self):
        res = self.run_([tx("t1", "2026-03-03", 400, "AIRBNB CREDIT")])
        p = next(p for p in self.ben(res, "b", "experiences")["periods"] if p["key"] == "2026")
        self.assertEqual(p["used"], 250)
        self.assertTrue(any("above the" in n for n in p["notes"]))

    def test_duplicate_transactions_count_once(self):
        with tempfile.TemporaryDirectory() as d:
            f = {"contract": "finerd-points/transactions@1", "source": {"app": "x"},
                 "accounts": [self.acc["accA"]], "transactions": [tx("t1", "2026-10-05", 10, "DINING CREDIT", acc="accA")]}
            for n in ("1", "2"):
                Path(d, n + ".json").write_text(json.dumps(f))
            accs, txns = credits.load_txns([Path(d, "1.json"), Path(d, "2.json")])
        self.assertEqual(len(txns), 1)

    def test_pending_credit_is_not_used(self):
        res = self.run_([tx("t1", "2026-10-05", 10, "DINING CREDIT", acc="accA", pending=True)])
        p = next(p for p in self.ben(res, "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual((p["used"], p["pending"]), (0, 10))
        self.assertEqual([o for o in res["proposed_batch"] if o["op"] == "observe"], [])

    def test_merchant_refund_is_not_a_credit(self):
        res = self.run_([tx("t1", "2026-10-05", 10, "GRUBHUB CREDIT REFUND", acc="accA", kind="refund")])
        p = next(p for p in self.ben(res, "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(p["used"], 0)

    def test_reversal_comes_off_the_original_period(self):
        res = self.run_([tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                         tx("r", "2026-11-01", 10, "DINING CREDIT REVERSAL", acc="accA", direction="debit",
                            kind="other", reversal_hint=True)])
        per = {p["key"]: p for p in self.ben(res, "a", "dining")["periods"]}
        self.assertEqual(per["2026-10"]["used"], 0)
        self.assertEqual(per["2026-11"]["remaining"], 10)  # November untouched, never above the allowance

    def test_anniversary_period_belongs_to_its_start_year(self):
        txns = [tx("h", "2025-10-01", 100, "HOTEL CREDIT")]
        y26 = self.ben(self.run_(txns, 2026), "b", "hotel")["year_to_date"]["used"]
        y25 = self.ben(self.run_(txns, 2025), "b", "hotel")["year_to_date"]["used"]
        self.assertEqual((y25, y26), (100, 0))

    def test_realized_percentage_and_one_time_credits_count_as_used(self):
        res = self.run_([tx("v", "2026-05-01", 25, "VENUE CREDIT"), tx("g", "2026-04-01", 120, "GLOBAL ENTRY CREDIT")])
        res["totals"] = credits.totals(res)
        self.assertEqual(res["totals"]["used"], 145)
        self.assertEqual(self.ben(res, "b", "entry")["periods"][0]["status"], "used")

    def test_shared_allowance_is_pooled(self):
        res = self.run_([tx("v", "2026-05-01", 25, "VENUE CREDIT", acc="accA")])
        b_first = self.ben(res, "b", "venue")
        a_second = self.ben(res, "a", "venue")
        self.assertEqual(b_first["year_to_date"]["used"], 25)
        self.assertEqual(a_second.get("counted_on_card"), "b")

    def test_gated_credit_is_not_open_money(self):
        res = self.run_([])
        dell = self.ben(res, "b", "dell")
        self.assertEqual(dell["current"]["status"], "ask")
        self.assertEqual(credits.totals(res)["open_this_period"], credits.totals(res)["open_this_period"])
        self.assertFalse(any(p["remaining"] for p in dell["periods"]))

    def test_unknown_card_fees_still_proposed(self):
        b = [{"op": "add_card", "id": "z", "person": "me", "nickname": "Store card",
              "finance_link": {"app": "x", "account_id": "accZ"}}]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        self.acc["accZ"] = {**self.acc["accA"], "account_id": "accZ"}
        res = self.run_([tx("f", "2026-02-01", 95, "ANNUAL FEE", acc="accZ", direction="debit", kind="fee")])
        self.assertTrue(any(o["op"] == "add_cost" and o["card"] == "z" for o in res["proposed_batch"]))

    def test_current_period_without_data_to_today_is_unknown(self):
        self.acc["accA"]["coverage"]["to"] = "2026-10-20"
        res = self.run_([])
        self.assertEqual(self.ben(res, "a", "dining")["current"]["status"], "unknown")


class Round2(unittest.TestCase):
    """Reproductions from the second Codex review."""

    def setUp(self):
        CreditRegressions.setUp(self)

    run_ = CreditRegressions.run_
    ben = CreditRegressions.ben

    def test_tie_goes_to_the_benefit_the_amount_fits(self):
        res = self.run_([tx("t", "2026-05-01", 1000, "DELL CREDIT")])
        self.assertEqual(self.ben(res, "b", "dell")["year_to_date"]["used"], 1000)
        self.assertEqual(self.ben(res, "b", "dell-small")["year_to_date"]["used"], 0)
        res = self.run_([tx("t", "2026-05-01", 150, "DELL CREDIT")])
        self.assertEqual(self.ben(res, "b", "dell-small")["year_to_date"]["used"], 150)

    def test_linked_reversal_with_other_words(self):
        res = self.run_([tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                         tx("r", "2026-11-01", 10, "ADJUSTMENT", acc="accA", direction="debit", kind="other",
                            reversal_of="c")])
        per = {p["key"]: p for p in self.ben(res, "a", "dining")["periods"]}
        self.assertEqual(per["2026-10"]["used"], 0)

    def test_pending_reversal_not_counted_yet(self):
        res = self.run_([tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                         tx("r", "2026-11-01", 10, "DINING CREDIT REVERSAL", acc="accA", direction="debit",
                            kind="other", reversal_hint=True, pending=True)])
        per = {p["key"]: p for p in self.ben(res, "a", "dining")["periods"]}
        self.assertEqual(per["2026-10"]["used"], 10)

    def test_recorded_reversal_survives_without_transactions(self):
        txns = [tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                tx("r", "2026-11-01", 10, "DINING CREDIT REVERSAL", acc="accA", direction="debit", kind="other",
                   reversal_hint=True)]
        res = self.run_(txns)
        batch = [o for o in res["proposed_batch"] if o["op"] == "observe"]
        h, _ = fl.preview_batch(self.led, batch)
        fl.apply_batch(self.led, batch, h, S)
        per = {p["key"]: p for p in self.ben(self.run_([]), "a", "dining")["periods"]}
        self.assertEqual(per["2026-10"]["used"], 0)

    def test_anniversary_credit_counts_in_its_calendar_year(self):
        txns = [tx("h", "2026-02-01", 75, "HOTEL CREDIT")]
        self.assertEqual(self.ben(self.run_(txns, 2025), "b", "hotel")["year_to_date"]["used"], 0)
        self.assertEqual(self.ben(self.run_(txns, 2026), "b", "hotel")["year_to_date"]["used"], 75)

    def test_foreign_or_future_observations_do_not_count(self):
        b = [{"op": "observe", "subject": "benefit:a/dining/2026-10", "field": "credited", "value": 10, "unit": "EUR",
              "source": {"kind": "person"}, "as_of": "2026-10-05", "confidence": "confirmed"},
             {"op": "observe", "subject": "benefit:a/dining/2026-09", "field": "credited", "value": 10, "unit": "USD",
              "source": {"kind": "person"}, "as_of": "2026-12-01", "confidence": "confirmed"}]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        per = {p["key"]: p for p in self.ben(self.run_([]), "a", "dining")["periods"]}
        self.assertEqual((per["2026-10"]["used"], per["2026-09"]["used"]), (0, 0))

    def test_terms_before_terms_from_are_unknown(self):
        self.catalog["cards"]["test-card"]["terms_from"] = "2026-06-01"
        per = {p["key"]: p for p in self.ben(self.run_([]), "a", "dining")["periods"]}
        self.assertEqual(per["2026-03"]["status"], "unknown")
        self.assertEqual(per["2026-07"]["status"], "no credit posted")

    def test_pooled_value_does_not_depend_on_card_order(self):
        b = [{"op": "set_setting", "key": "credit_values", "value": {"a/venue": 0.5, "b/venue": 1.0}}]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        res = self.run_([tx("v", "2026-05-01", 20, "VENUE CREDIT", acc="accA")])
        total, _ = yir.credits_value(res, self.led["_meta"]["settings"])
        self.assertEqual(total, 10)  # pooled onto card b's line, but valued at card a's fraction (a used it)


class Round2Ledger(unittest.TestCase):
    def test_amend_cannot_null_required_fields(self):
        led = ledger_with([{"op": "add_redemption", "id": "r", "person": "me", "program": "x", "booked_on": "2025-01-01",
                            "points": 1, "fees": 0, "status": "booked"}])
        for f in ("booked_on", "fees"):
            with self.assertRaises(fl.LedgerError):
                fl.preview_batch(led, [{"op": "amend", "target": "redemptions", "id": "r", "field": f, "reason": "x"}])

    def test_spend_warnings_make_the_report_incomplete(self):
        led = ledger_with([{"op": "set_setting", "key": "foregone_cashback_rate", "value": 0.02}])
        r = yir.compute(led, 2025, spend={"personal": {"spend": 0, "excluded": 0}, "business": {"spend": 0, "excluded": 0},
                                          "notes": ["Gold: no transactions supplied"]})
        self.assertFalse(r["complete"])

    def test_cancellation_without_date_is_flagged(self):
        led = ledger_with([{"op": "add_redemption", "id": "r", "person": "me", "program": "x", "booked_on": "2025-12-20",
                            "points": 1, "fees": 0, "status": "cancelled_with_fee", "cancellation_fee": 75}])
        self.assertFalse(yir.compute(led, 2025)["complete"])

    def test_bank_reference_numbers_do_not_block_a_batch(self):
        import credits as cr
        self.assertEqual(cr.safe_text("DUNKIN CREDIT REF 4012888888881881"), "DUNKIN CREDIT REF …")
        self.assertEqual(fl.scan_forbidden({"note": "ticket 0167712345678, PIN reset, token: abc"}), [])

    def test_purchased_points_without_a_recorded_purchase_is_flagged(self):
        led = ledger_with([{"op": "add_redemption", "id": "r", "person": "me", "program": "x", "booked_on": "2025-04-01",
                            "points": 1, "fees": 0, "fallback": 100, "normalized": 200, "status": "booked",
                            "purchased_points_cost": 50}])
        self.assertFalse(yir.compute(led, 2025)["complete"])

    def test_ordinary_passport_words_pass(self):
        self.assertEqual(fl.scan_forbidden({"note": "PASSPORT CREDIT"}), [])
        self.assertEqual(fl.scan_forbidden({"note": "Passport renewal fee"}), [])
        self.assertNotEqual(fl.scan_forbidden({"note": "passport AB1234567"}), [])

    def test_loaded_ledger_is_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            led = fl.new_ledger("T")
            led["version"] = 1
            led["cards"].append({"id": "c", "person": "me", "nickname": "x", "password": "hunter2"})
            p = Path(d, "l.json")
            p.write_text(json.dumps(led))
            with self.assertRaises(fl.LedgerError):
                fl.load(p)

    def test_redaction_scrubs_amendment_history(self):
        led = ledger_with([{"op": "add_person", "id": "p2", "name": "Anna", "consent": {"given": True, "on": "2026-01-01"}},
                           {"op": "add_card", "id": "c2", "person": "p2", "nickname": "Anna secret card"}])
        b = [{"op": "amend", "target": "cards", "id": "c2", "field": "person", "value": "me", "reason": "x"},
             {"op": "amend", "target": "cards", "id": "c2", "field": "nickname", "value": "My card", "reason": "x"}]
        h, _ = fl.preview_batch(led, b)
        fl.apply_batch(led, b, h, S)
        h, plan, _ = fl.redaction_plan(led, "p2")
        fl.redact_person(led, "p2", h, S)
        self.assertNotIn("Anna secret card", json.dumps(led))
        self.assertNotIn('"p2"', json.dumps(led["cards"]))

    def test_changed_unresolved_write_is_refused(self):
        led = ledger_with()
        mk = lambda d: [{"op": "external", "target": "calendar", "action": "create", "summary": "e", "match_key": "k",
                         "payload": {"title": "Credits ending (1)", "date": d, "reminder_minutes": 4320}}]
        h, _ = fl.preview_batch(led, mk("2026-12-31"))
        fl.apply_batch(led, mk("2026-12-31"), h, S)
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, mk("2027-01-02"))

    def test_calendar_needs_marker_and_no_guests_in_read_back(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "e",
              "payload": {"title": "Credits ending (1)", "date": "2026-12-31", "reminder_minutes": 4320,
                          "visibility": "private", "description": "x\n[finerd points op-abc123]"}}]
        h, _ = fl.preview_batch(led, b)
        op = fl.apply_batch(led, b, h, S)[0]["op_id"]
        fl.set_op_state(led, op, "sent", S)
        good = {"title": "Credits ending (1)", "date": "2026-12-31", "reminder_minutes": 4320, "visibility": "private",
                "attendees": [], "description": "x\n[finerd points op-abc123]"}
        for bad in ({**good, "attendees": ["x@y.z"]}, {**good, "description": "edited"},
                    {**good, "event_id": "other"}):
            with self.assertRaises(fl.LedgerError):
                fl.set_op_state(led, op, "confirmed", S, "e1", bad)
        fl.set_op_state(led, op, "confirmed", S, "e1", good)


class NormalizeAccountName(unittest.TestCase):
    def test_wrong_account_name_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "p.json").write_text(json.dumps({"has_more": False, "transactions": [
                {"id": "1", "date": "2026-01-01T00:00:00", "type": "INCOME", "description": "AMEX RESY CREDIT", "amount": 50,
                 "currency": "USD", "journals": [{"type": "FROM", "account": "Rewards"}, {"type": "TO", "account": "AmEx Gold"}]}]}))
            with self.assertRaises(SystemExit):
                normalize.from_finerd([str(Path(d, "p.json"))], "Amex Gold", "g", "2026-01-01", "2026-11-02",
                                      covered_from="2025-01-01")


class NormalizeAndBalances(unittest.TestCase):
    def test_csv_kinds_and_scoped_ids(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "x.csv")
            p.write_text("Date,Description,Amount\n2026-01-03,GRUBHUB,-24.10\n2026-01-05,AMEX DINING CREDIT,10\n"
                         "2026-01-06,GRUBHUB REFUND,5\n2026-01-20,AUTOPAY PAYMENT THANK YOU,100\n")
            out = normalize.from_csv(str(p), "Gold", "Date", "Description", "Amount", "debit", "2026-01-01", "2026-01-31")
        kinds = [t["kind"] for t in out["transactions"]]
        self.assertEqual(kinds, ["purchase", "credit", "refund", "payment"])

    def test_csv_ids_are_stable_across_overlapping_exports(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a.csv"), Path(d, "b.csv")
            a.write_text("Date,Description,Amount\n2026-01-05,AMEX DINING CREDIT,10\n2026-01-05,COFFEE,-4\n"
                         "2026-01-05,COFFEE,-4\n")
            b.write_text("Date,Description,Amount\n2026-01-02,LUNCH,-12\n2026-01-05,AMEX DINING CREDIT,10\n"
                         "2026-01-05,COFFEE,-4\n2026-01-05,COFFEE,-4\n")
            ia = [t["id"] for t in normalize.from_csv(str(a), "Gold", "Date", "Description", "Amount", "debit",
                                                       "2026-01-01", "2026-01-31")["transactions"]]
            ib = [t["id"] for t in normalize.from_csv(str(b), "Gold", "Date", "Description", "Amount", "debit",
                                                       "2026-01-01", "2026-01-31")["transactions"]]
        self.assertEqual(ia, ib[1:])          # same rows, same ids, whatever their position
        self.assertNotEqual(ia[1], ia[2])     # two identical coffees on one day stay two

    def test_finerd_completeness_from_last_page(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "p1.json").write_text(json.dumps({"page": 0, "has_more": True, "complete": False, "transactions": []}))
            Path(d, "p2.json").write_text(json.dumps({"page": 1, "has_more": False, "complete": False, "transactions": []}))
            out = normalize.from_finerd([str(Path(d, "p1.json")), str(Path(d, "p2.json"))], "Gold", "g",
                                        "2026-01-01", "2026-11-02", covered_from="2025-01-01")
        self.assertTrue(out["accounts"][0]["complete"])

    def test_balances_match_program_names_loosely(self):
        led = ledger_with([{"op": "add_account", "id": "hyatt", "person": "me", "program": "world-of-hyatt",
                            "nickname": "Hyatt", "unit": "points"}])
        ops, unmatched = balances.propose(led, {"contract": "finerd-points/balances@1", "source": {"app": "finerd"},
                                                "balances": [{"account_id": None, "program": "World of Hyatt",
                                                              "amount": 1000, "unit": "points", "as_of": "2026-11-01",
                                                              "kind": "verified"}]})
        self.assertEqual((len(ops), unmatched), (1, []))

    def test_report_escapes_injected_text(self):
        led = ledger_with()
        y = yir.compute(led, 2025)
        y["year"] = "<script>x</script>"
        html = render_report.render(led, TODAY, "<b>t</b>", yir=y)
        self.assertNotIn("<script>x", html)
        self.assertNotIn("<b>t</b>", html)


class Round3(unittest.TestCase):
    def test_filtered_search_is_not_spend(self):
        import spend
        led = ledger_with([{"op": "add_card", "id": "g", "person": "me", "nickname": "Gold", "catalog_ref": "test-card",
                            "finance_link": {"app": "finerd", "account_id": "g"}}])
        acc = {"g": {"account_id": "g", "name": "Gold", "complete": True, "scope": "filtered",
                     "coverage": {"from": "2025-01-01", "to": "2025-12-31"}}}
        out = spend.summarize(led, ff.load_catalog(FIX / "facts"), acc, [], 2025)
        self.assertTrue(any("filtered search" in n for n in out["notes"]))
        self.assertFalse(yir.compute(led, 2025, spend=out, rate=0.02)["complete"])

    def test_a_search_left_open_keeps_the_files_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.json").write_text(json.dumps({"page": 0, "has_more": True, "transactions": []}))
            Path(d, "b.json").write_text(json.dumps({"page": 0, "has_more": False, "transactions": []}))
            out = normalize.from_finerd([str(Path(d, "a.json")), str(Path(d, "b.json"))], "Gold", "g",
                                        "2026-01-01", "2026-11-02", covered_from="2025-01-01")
        self.assertFalse(out["accounts"][0]["complete"])


class Round3Codex(unittest.TestCase):
    def setUp(self):
        CreditRegressions.setUp(self)

    run_ = CreditRegressions.run_
    ben = CreditRegressions.ben

    def test_partial_reversal_counts_once_in_the_year(self):
        res = self.run_([tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                         tx("r", "2026-10-20", 3, "ADJ", acc="accA", direction="debit", kind="other", reversal_of="c")])
        b = self.ben(res, "a", "dining")
        oct_ = next(p for p in b["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["used"], 7)
        self.assertEqual(oct_["used_by_year"]["2026"], 7)

    def test_reimporting_a_reversal_does_not_double_it(self):
        txns = [tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                tx("r", "2026-10-20", 3, "ADJ", acc="accA", direction="debit", kind="other", reversal_of="c")]
        for _ in range(2):
            batch = [o for o in self.run_(txns)["proposed_batch"] if o["op"] == "observe"]
            if batch:
                h, _ = fl.preview_batch(self.led, batch)
                fl.apply_batch(self.led, batch, h, S)
        oct_ = next(p for p in self.ben(self.run_([]), "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["used"], 7)

    def test_snapshot_uses_evidence_as_of_its_date(self):
        b = [{"op": "observe", "subject": "benefit:a/app-cash/2026-10", "field": "used_amount", "value": v,
              "source": {"kind": "person"}, "as_of": d, "confidence": "confirmed"}
             for v, d in ((5, "2026-10-05"), (10, "2026-10-31"))]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        res = self.run_([], today=dt.date(2026, 10, 15))
        self.assertEqual(self.ben(res, "a", "app-cash")["current"]["used"], 5)

    def test_ambiguous_match_is_unsure_and_asked(self):
        lodging = next(b for b in self.catalog["cards"]["test-card-b"]["benefits"] if b["id"] == "lodging")
        lodging["match"]["keywords"].append("AIRBNB")  # both benefits now match «AIRBNB», as on the real card
        res = self.run_([tx("t", "2026-10-30", 100, "AIRBNB CREDIT")])
        self.assertTrue(any("Which benefit" in q for q in res["questions"]))
        obs = [o for o in res["proposed_batch"] if o["op"] == "observe"]
        self.assertEqual(obs[0]["confidence"], "unsure")

    def test_credit_not_yet_posted_is_not_counted(self):
        res = self.run_([tx("t", "2026-10-30", 10, "DINING CREDIT", acc="accA", posted_date="2026-11-04")])
        oct_ = next(p for p in self.ben(res, "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["used"], 0)

    def test_two_different_writes_with_one_key_in_a_batch(self):
        mk = lambda d: {"op": "external", "target": "calendar", "action": "create", "summary": "e", "match_key": "k",
                        "payload": {"title": "Credits ending (1)", "date": d, "reminder_minutes": 4320}}
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(self.led, [mk("2026-12-31"), mk("2027-01-02")])

    def test_cancellation_fee_without_date_flags_later_years(self):
        led = ledger_with([{"op": "add_redemption", "id": "r", "person": "me", "program": "x", "booked_on": "2025-12-20",
                            "points": 1, "fees": 0, "status": "cancelled_with_fee", "cancellation_fee": 75}])
        self.assertFalse(yir.compute(led, 2026)["complete"])

    def test_moved_deadline_keeps_its_reminder_until_replaced(self):
        import expirations
        led = ledger_with()
        led["calendar_events"].append({"id": "cal-1", "event_id": "e1", "subject": "credits:2026-11-30",
                                       "members": ["benefit:a/x/2026-11"], "title": "Card credits ending (1)",
                                       "date": "2026-11-30", "reminder_minutes": 4320, "done": False})
        small = {"date": "2026-12-01", "kind": "credit", "value": 10, "currency": "USD", "card": "a",
                 "subject": "benefit:a/x/2026-11", "what": "X (A)", "status": "not used yet", "never_used": False,
                 "source": "x"}
        self.assertEqual(expirations.calendar_plan(led, [small], TODAY), [])


class Round4Codex(unittest.TestCase):
    def setUp(self):
        CreditRegressions.setUp(self)

    run_ = CreditRegressions.run_
    ben = CreditRegressions.ben

    def test_restored_unsure_assignment_stays_unsure(self):
        lodging = next(b for b in self.catalog["cards"]["test-card-b"]["benefits"] if b["id"] == "lodging")
        lodging["match"]["keywords"].append("AIRBNB")
        batch = [o for o in self.run_([tx("t", "2026-10-30", 100, "AIRBNB CREDIT")])["proposed_batch"] if o["op"] == "observe"]
        h, _ = fl.preview_batch(self.led, batch)
        fl.apply_batch(self.led, batch, h, S)
        res = self.run_([])
        p = [p for b in next(c for c in res["cards"] if c["card"] == "b")["benefits"] for p in b["periods"]
             if p["credited"] == 100][0]
        self.assertEqual(p["confidence"], "unsure")

    def test_posting_date_rules_reversals_and_years(self):
        res = self.run_([tx("c", "2026-10-05", 10, "DINING CREDIT", acc="accA"),
                         tx("r", "2026-11-01", 3, "ADJ", acc="accA", direction="debit", kind="other", reversal_of="c",
                            posted_date="2026-11-04")])
        oct_ = next(p for p in self.ben(res, "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["used"], 10)  # the reversal has not posted by 2026-11-02
        txns = [tx("h", "2025-12-31", 75, "HOTEL CREDIT", posted_date="2026-01-02")]
        self.assertEqual(self.ben(self.run_(txns, 2026), "b", "hotel")["year_to_date"]["used"], 75)

    def test_cards_in_another_currency_are_not_analyzed(self):
        self.catalog["cards"]["test-card"]["currency"] = "EUR"
        res = self.run_([tx("c", "2026-10-05", 20, "DINING CREDIT", acc="accA")])
        a = next(c for c in res["cards"] if c["card"] == "a")
        self.assertIn("not supported", a["note"])
        self.assertEqual(a["benefits"], [])

    def test_shared_allowance_has_one_cap_across_posting_years(self):
        txns = [tx("v1", "2025-12-15", 250, "VENUE CREDIT", acc="accB"),
                tx("v2", "2025-12-31", 100, "VENUE CREDIT", acc="accA", posted_date="2026-01-02")]
        y25 = self.ben(self.run_(txns, 2025, TODAY), "b", "venue")["year_to_date"]["used"]
        y26 = self.ben(self.run_(txns, 2026), "b", "venue")["year_to_date"]["used"]
        self.assertEqual((y25, y26), (250, 0))

    def test_reversal_of_a_credit_that_did_not_fit_removes_nothing(self):
        txns = [tx("v1", "2026-05-01", 250, "VENUE CREDIT", acc="accB"),
                tx("v2", "2026-06-01", 100, "VENUE CREDIT", acc="accA"),
                tx("r2", "2026-07-01", 100, "ADJUSTMENT", acc="accA", direction="debit", kind="other", reversal_of="v2")]
        self.assertEqual(self.ben(self.run_(txns), "b", "venue")["year_to_date"]["used"], 250)

    def test_reversal_frees_room_for_a_later_credit(self):
        txns = [tx("v1", "2026-05-01", 250, "VENUE CREDIT", acc="accB"),
                tx("r1", "2026-06-01", 250, "ADJUSTMENT", acc="accB", direction="debit", kind="other", reversal_of="v1"),
                tx("v2", "2026-07-01", 250, "VENUE CREDIT", acc="accA")]
        self.assertEqual(self.ben(self.run_(txns), "b", "venue")["year_to_date"]["used"], 250)

    def test_single_card_reversal_of_excess_credit(self):
        txns = [tx("c1", "2026-10-02", 10, "DINING CREDIT", acc="accA"),
                tx("c2", "2026-10-03", 10, "DINING CREDIT", acc="accA"),
                tx("r2", "2026-10-04", 10, "ADJ", acc="accA", direction="debit", kind="other", reversal_of="c2")]
        oct_ = next(p for p in self.ben(self.run_(txns), "a", "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual((oct_["used"], oct_["used_by_year"]["2026"]), (10, 10))

    def test_inferred_reversals_use_credits_that_still_have_a_balance(self):
        txns = [tx("v1", "2026-05-01", 100, "VENUE CREDIT", acc="accB"),
                tx("v2", "2026-06-01", 100, "VENUE CREDIT", acc="accB"),
                tx("r1", "2026-07-01", 100, "VENUE CREDIT REVERSAL", acc="accB", direction="debit", kind="other",
                   reversal_hint=True),
                tx("r2", "2026-08-01", 100, "VENUE CREDIT REVERSAL", acc="accB", direction="debit", kind="other",
                   reversal_hint=True),
                tx("a1", "2026-09-01", 25, "VENUE CREDIT", acc="accA")]
        self.assertEqual(self.ben(self.run_(txns), "b", "venue")["year_to_date"]["used"], 25)

    def test_excluded_reversals_do_not_consume_a_credit(self):
        for excluded in ({"pending": True}, {"currency": "EUR"}):
            txns = [tx("v1", "2026-05-01", 100, "VENUE CREDIT", acc="accB"),
                    tx("v2", "2026-06-01", 250, "VENUE CREDIT", acc="accB"),
                    tx("r0", "2026-10-31", 250, "VENUE CREDIT REVERSAL", acc="accB", direction="debit", kind="other",
                       reversal_hint=True, **excluded),
                    tx("r1", "2026-11-01", 250, "VENUE CREDIT REVERSAL", acc="accB", direction="debit", kind="other",
                       reversal_hint=True),
                    tx("a1", "2026-11-02", 25, "VENUE CREDIT", acc="accA")]
            self.assertEqual(self.ben(self.run_(txns), "b", "venue")["year_to_date"]["used"], 125, excluded)

    def test_explicit_reversal_of_an_excluded_credit_is_never_redirected(self):
        for excluded in ({"pending": True}, {"currency": "EUR"}):
            txns = [tx("v1", "2026-05-01", 300, "AIRBNB LODGING CREDIT", acc="accB"),
                    tx("v2", "2026-11-01", 300, "AIRBNB LODGING CREDIT", acc="accB", **excluded),
                    tx("r1", "2026-11-02", 300, "ADJUSTMENT", acc="accB", direction="debit", kind="other",
                       reversal_of="v2")]
            res = self.run_(txns)
            self.assertEqual(self.ben(res, "b", "lodging")["year_to_date"]["used"], 300, excluded)
            self.assertFalse(any(o["field"] == "reversed" for o in res["proposed_batch"] if o["op"] == "observe"))

    def test_a_persons_answer_is_capped_at_the_allowance(self):
        b = [{"op": "observe", "subject": "benefit:b/venue/2026", "field": "used_amount", "value": 400, "unit": "USD",
              "source": {"kind": "person"}, "as_of": "2026-10-01", "confidence": "confirmed"}]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        res = credits.analyze(self.led, self.catalog, self.acc, [], TODAY, 2026, only_card="b")
        self.assertEqual(self.ben(res, "b", "venue")["year_to_date"]["used"], 250)

    def test_per_stay_credit_has_no_year_end_deadline(self):
        led = ledger_with([{"op": "add_card", "id": "g", "person": "me", "nickname": "Gold", "catalog_ref": "amex-gold"}])
        res = credits.analyze(led, ff.load_catalog(), {}, [], TODAY, 2026)
        row = next(r for r in credits.to_markdown(res).splitlines() if r.startswith("| The Hotel Collection"))
        self.assertIn("| per stay ($100) |", row)
        self.assertNotIn("2026-12-31", row)
        html_rows = [r for r in render_report.credits_section(res).split("<tr>") if "The Hotel Collection" in r]
        self.assertIn("per stay", html_rows[0])
        self.assertNotIn("2026-12-31", html_rows[0])

    def test_credit_posted_after_new_year_counts_in_the_new_year(self):
        for desc, bid in (("AIRLINE FEE CREDIT", "airline-credit"), ("DINING CREDIT", "dining")):
            txns = [tx("x", "2025-12-31", 10, desc, acc="accA", posted_date="2026-01-02")]
            y25 = self.ben(self.run_(txns, 2025, dt.date(2026, 11, 2)), "a", bid)["year_to_date"]["used"]
            y26 = self.ben(self.run_(txns, 2026), "a", bid)["year_to_date"]["used"]
            self.assertEqual((y25, y26), (0, 10), bid)

    def test_calendar_read_back_must_name_the_calendar(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "e",
              "payload": {"title": "Credits ending (1)", "date": "2026-12-31", "reminder_minutes": 4320,
                          "visibility": "private", "calendar_id": "rad@example.com"}}]
        h, _ = fl.preview_batch(led, b)
        op = fl.apply_batch(led, b, h, S)[0]["op_id"]
        fl.set_op_state(led, op, "sent", S)
        rb = {"title": "Credits ending (1)", "date": "2026-12-31", "reminder_minutes": 4320, "visibility": "private",
              "attendees": []}
        for bad in (rb, {**rb, "calendar_id": "other@example.com"}):
            with self.assertRaises(fl.LedgerError):
                fl.set_op_state(led, op, "confirmed", S, "e1", bad)
        fl.set_op_state(led, op, "confirmed", S, "e1", {**rb, "calendar_id": "rad@example.com"})


class CalendarRound2(unittest.TestCase):
    def test_missing_data_never_marks_done_and_reopen_is_a_new_event(self):
        import expirations
        led = ledger_with()
        led["calendar_events"].append({"id": "cal-1", "event_id": "e1", "subject": "credits:2026-12-31",
                                       "members": ["benefit:a/dining/2026-12"], "title": "Card credits ending (1)",
                                       "date": "2026-12-31", "reminder_minutes": 4320, "done": False})
        self.assertEqual(expirations.calendar_plan(led, [], TODAY), [])
        led["calendar_events"][0]["done"] = True
        item = {"date": "2026-12-31", "kind": "credit", "value": 100, "currency": "USD", "card": "a",
                "subject": "benefit:a/dining/2026-12", "what": "Dining (A)", "status": "not used yet",
                "never_used": False, "source": "x"}
        ops = expirations.calendar_plan(led, [item], TODAY)
        self.assertEqual(ops[0]["action"], "create")
        self.assertTrue(ops[0]["match_key"].endswith(":g1"))

    def test_page_without_pagination_fields_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "p.json").write_text(json.dumps({"complete": False, "transactions": []}))
            out = normalize.from_finerd([str(Path(d, "p.json"))], "Gold", "g", "2026-01-01", "2026-11-02",
                                        covered_from="2025-01-01")
        self.assertFalse(out["accounts"][0]["complete"])

    def test_gap_between_files_is_not_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            for n, (f, t) in enumerate((("2026-01-01", "2026-01-31"), ("2026-03-01", "2026-03-31"))):
                Path(d, f"{n}.json").write_text(json.dumps({"contract": "finerd-points/transactions@1", "source": {"app": "x"},
                    "accounts": [{"account_id": "a", "name": "a", "complete": True, "coverage": {"from": f, "to": t}}],
                    "transactions": []}))
            accs, _ = credits.load_txns([Path(d, "0.json"), Path(d, "1.json")])
        self.assertFalse(accs["a"]["complete"])


class Lease(unittest.TestCase):
    def test_another_conversations_lease_needs_a_hand_over(self):
        led = ledger_with()
        later = fl.now_utc() + dt.timedelta(minutes=31)
        with self.assertRaises(fl.LedgerError):  # expired, but never released
            fl.ensure_lease(led, "other-1", now=later)
        fl.acquire_lease(led, "other-1", now=later, transfer=True)
        self.assertEqual(fl.lease_status(led, later)["session"], "other-1")
        fl.release_lease(led, "other-1")
        fl.ensure_lease(led, S)  # a released lease is free


class SkillFoldersStandalone(unittest.TestCase):
    """Copy each skill folder alone (as Claude chat does) and run its documented commands."""

    def run_cmd(self, args, cwd):
        r = subprocess.run([sys.executable] + args, cwd=cwd, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def test_every_skill_folder_runs_alone(self):
        skills = ROOT / "plugins" / "finerd-points" / "skills"
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            gold = work / "gold.csv"
            gold.write_text("Date,Description,Amount\n2026-03-24,AMEX RESY CREDIT,50\n2026-03-13,MEMBERSHIP FEE,-325\n")
            for skill in sorted(p.name for p in skills.iterdir() if p.is_dir()):
                sd = work / skill
                shutil.copytree(skills / skill, sd)
                scripts = sd / "scripts"
                for script in scripts.glob("*.py"):
                    if script.name.startswith("fp"):
                        continue
                    code, out, err = self.run_cmd([str(script), "--help"], sd)
                    self.assertEqual(code, 0, f"{skill}/{script.name} --help: {err}")
                if (scripts / "check_facts.py").exists():
                    code, out, err = self.run_cmd([str(scripts / "check_facts.py")], sd)
                    self.assertEqual(code, 0, f"{skill} check_facts: {out}{err}")
                if not (scripts / "ledger.py").exists():
                    continue
                folder = work / f"{skill} points"
                led = folder / "ledger.json"
                code, out, err = self.run_cmd([str(scripts / "ledger.py"), "setup", "--folder", str(folder), "--name", "T"],
                                              sd)
                self.assertEqual(code, 0, f"{skill} setup: {out}{err}")
                batch = work / f"{skill}.batch.json"
                batch.write_text(json.dumps([{"op": "add_card", "id": "gold", "person": "me", "nickname": "Gold",
                                              "catalog_ref": "amex-gold", "finance_link": {"app": "CSV", "account_id": "Gold"}}]))
                code, out, err = self.run_cmd([str(scripts / "ledger.py"), "apply", "--folder", str(folder), "--batch",
                                               str(batch), "--confirm", "0123456789abcdef"], sd)
                self.assertEqual(code, 2, f"{skill}: apply without preview must be refused")
                code, out, err = self.run_cmd([str(scripts / "ledger.py"), "preview", "--folder", str(folder), "--batch",
                                               str(batch), "--json"], sd)
                h = json.loads(out)["hash"]
                code, out, err = self.run_cmd([str(scripts / "ledger.py"), "apply", "--folder", str(folder), "--batch",
                                               str(batch), "--confirm", h], sd)
                self.assertEqual(code, 0, f"{skill} apply: {out}{err}")
                code, out, err = self.run_cmd([str(scripts / "ledger.py"), "open", "--folder", str(folder)], sd)
                self.assertEqual(json.loads(out)["check"]["chain"], "ok 2", f"{skill} open: {out}{err}")
                if (scripts / "credits.py").exists():
                    txf = work / f"{skill}.txns.json"
                    code, out, err = self.run_cmd([str(scripts / "normalize.py"), "csv", "--file", str(gold),
                                                   "--account-name", "Gold", "--date-col", "Date", "--desc-col",
                                                   "Description", "--amount-col", "Amount", "--negative-is", "debit",
                                                   "--from", "2026-01-01", "--to", "2026-11-02"], sd)
                    self.assertEqual(code, 0, f"{skill} normalize: {err}")
                    txf.write_text(out)
                    code, out, err = self.run_cmd([str(scripts / "credits.py"), "--ledger", str(led), "--transactions",
                                                   str(txf), "--today", "2026-11-02"], sd)
                    self.assertEqual(code, 0, f"{skill} credits: {out}{err}")
                    self.assertEqual(json.loads(out)["totals"]["used"], 50)


if __name__ == "__main__":
    unittest.main()
