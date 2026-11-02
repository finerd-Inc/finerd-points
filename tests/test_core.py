"""Core tests (stdlib unittest): python3 -m unittest discover -s tests"""
import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import credits  # noqa: E402
import expirations  # noqa: E402
import fpfacts as ff  # noqa: E402
import fpledger as fl  # noqa: E402
import yir  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
S = "test-session"


def ledger_with(*batches):
    led = fl.new_ledger("Test", timezone="America/Los_Angeles")
    led["version"] = 1
    fl.acquire_lease(led, S)
    for b in batches:
        h, _ = fl.preview_batch(led, b)
        fl.apply_batch(led, b, h, S)
    return led


def red(id_, booked, points, fees, fallback, normalized, status="booked", **kw):
    return {"op": "add_redemption", "id": id_, "person": "me", "program": "test", "booked_on": booked,
            "points": points, "fees": fees, "fallback": fallback, "normalized": normalized, "status": status, **kw}


class YearInReviewWorkedCases(unittest.TestCase):
    """The six worked cases of year-in-review-formula.md."""

    def test_1_refund_removes_redemption(self):
        led = ledger_with([red("r1", "2026-05-01", 60000, 50, 900, 1500, status="cancelled")])
        r = yir.compute(led, 2026)
        self.assertEqual(r["income"]["cash_avoided"], 0)
        self.assertEqual(r["costs"]["total"], 0)
        self.assertEqual(r["cancelled_removed"], ["r1"])

    def test_2_refund_with_fee_adds_cost(self):
        led = ledger_with([red("r1", "2026-05-01", 60000, 50, 900, 1500, status="cancelled_with_fee",
                               cancellation_fee=75)])
        r = yir.compute(led, 2026)
        self.assertEqual(r["income"]["value_redeemed"], 0)
        self.assertEqual(r["costs"]["cancellation_fees"], 75)
        self.assertEqual(r["net_value"], -75)

    def test_3_transfer_is_movement(self):
        led = ledger_with([{"op": "observe", "subject": "account:bilt", "field": "transfer_out", "value": 90000,
                            "source": {"kind": "program_page"}, "as_of": "2026-03-01", "confidence": "confirmed",
                            "note": "90,000 Bilt to Avios, 30% bonus adds 27,000"}])
        r = yir.compute(led, 2026)
        self.assertEqual((r["income"]["cash_avoided"], r["income"]["value_redeemed"], r["costs"]["total"]), (0, 0, 0))

    def test_5_points_from_last_year_count_when_booked(self):
        led = ledger_with([red("r1", "2026-01-15", 30000, 20, 400, 600)])
        self.assertEqual(yir.compute(led, 2026)["income"]["cash_avoided"], 380)
        self.assertEqual(yir.compute(led, 2025)["income"]["cash_avoided"], 0)

    def test_6_purchased_points_counted_once(self):
        led = ledger_with([
            {"op": "add_cost", "id": "buy1", "date": "2026-04-02", "kind": "points_purchase", "amount": 2032,
             "currency": "USD"},
            red("r1", "2026-04-03", 120000, 36, 1800, 4876, purchased_points_cost=2032),
        ])
        r = yir.compute(led, 2026)
        self.assertEqual(r["income"]["value_redeemed"], 4840)       # not 4876 − 36 − 2032
        self.assertEqual(r["income"]["cash_avoided"], 1764)
        self.assertEqual(r["costs"]["points_purchased"], 2032)
        self.assertEqual(r["net_value"], 4840 - 2032)

    def test_foregone_cashback_split(self):
        led = ledger_with()
        r = yir.compute(led, 2025, spend={"personal": {"spend": 150000, "excluded": 20000},
                                          "business": {"spend": 250000, "excluded": 0}}, rate=0.02)
        self.assertEqual(r["costs"]["foregone_cashback_split"], {"personal": 2600.0, "business": 5000.0})


class CreditsCases(unittest.TestCase):
    def setUp(self):
        self.catalog = ff.load_catalog(FIX / "facts")
        self.led = ledger_with([{"op": "add_card", "id": "t1", "person": "me", "nickname": "Test Card",
                                 "catalog_ref": "test-card",
                                 "finance_link": {"app": "x", "account_id": "acc1", "account_name": "Test Card"}}])

    def txns(self, rows, cov_from="2026-01-01", cov_to="2026-11-02"):
        accounts = {"acc1": {"account_id": "acc1", "name": "Test Card", "complete": True,
                             "coverage": {"from": cov_from, "to": cov_to}}}
        base = {"account_id": "acc1", "currency": "USD", "pending": False, "posted_date": None, "merchant": None,
                "category": None, "reversal_of": None, "reversal_hint": False}
        return accounts, [{**base, **r} for r in rows]

    def benefit(self, res, bid):
        return next(b for b in res["cards"][0]["benefits"] if b["benefit"] == bid)

    def test_4_reversed_credit_is_unused(self):
        acc, tx = self.txns([
            {"id": "a", "date": "2026-03-10", "amount": 200, "direction": "credit", "kind": "credit",
             "description": "AIRLINE FEE CREDIT"},
            {"id": "b", "date": "2026-04-02", "amount": 200, "direction": "debit", "kind": "other",
             "description": "AIRLINE FEE CREDIT REVERSAL", "reversal_hint": True},
        ])
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        p = self.benefit(res, "airline-credit")["current"]
        self.assertEqual(p["used"], 0)
        self.assertIn("a credit was reversed", p["notes"])
        self.assertEqual(p["status"], "not used yet")

    def test_monthly_credit_found_and_proposed_once(self):
        acc, tx = self.txns([{"id": "c", "date": "2026-10-05", "amount": 10, "direction": "credit",
                              "kind": "credit", "description": "DINING CREDIT GRUBHUB"}])
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        oct_ = next(p for p in self.benefit(res, "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["status"], "used")
        sep = next(p for p in self.benefit(res, "dining")["periods"] if p["key"] == "2026-09")
        self.assertEqual(sep["status"], "no credit posted")
        self.assertEqual(len([o for o in res["proposed_batch"] if o["op"] == "observe"]), 1)
        h, _ = fl.preview_batch(self.led, res["proposed_batch"])
        fl.apply_batch(self.led, res["proposed_batch"], h, S)
        res2 = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        self.assertEqual([o for o in res2["proposed_batch"] if o["op"] == "observe"], [])

    def test_no_coverage_is_unknown_not_zero(self):
        acc, tx = self.txns([], cov_from="2026-08-01")
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        jan = next(p for p in self.benefit(res, "dining")["periods"] if p["key"] == "2026-01")
        self.assertEqual(jan["status"], "unknown")
        self.assertIsNone(jan["remaining"])

    def test_wallet_credit_asks_the_person(self):
        acc, tx = self.txns([])
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        self.assertEqual(self.benefit(res, "app-cash")["current"]["status"], "ask")
        self.assertTrue(any("does not show at the bank" in q for q in res["questions"]))

    def test_keyword_is_a_whole_word(self):
        self.assertIsNone(credits._kw_hit("AMAZON MKTPL CREDIT", ["ZO"]))
        self.assertEqual(credits._kw_hit("ZO SPENDING CREDIT", ["ZO"]), "ZO")

    def test_never_used_credit_gets_no_reminder(self):
        acc, tx = self.txns([])
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        items = expirations.collect(self.led, res, dt.date(2026, 11, 2), 45)
        dining = next(i for i in items if i["what"].startswith("Dining"))
        self.assertTrue(dining["never_used"])
        ops = expirations.calendar_plan(self.led, items)
        self.assertFalse(any("Dining" in o["payload"].get("description", "") for o in ops))

    def test_merchant_refund_is_not_a_credit(self):
        acc, tx = self.txns([{"id": "r", "date": "2026-10-05", "amount": 10, "direction": "credit",
                              "kind": "refund", "description": "GRUBHUB ORDER REFUND"}])
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 11, 2), 2026)
        oct_ = next(p for p in self.benefit(res, "dining")["periods"] if p["key"] == "2026-10")
        self.assertEqual(oct_["used"], 0)

    def test_calendar_plan_create_update_done(self):
        acc, tx = self.txns([], cov_to="2026-12-01")
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 12, 1), 2026)
        items = expirations.collect(self.led, res, dt.date(2026, 12, 1), 45)
        ops = expirations.calendar_plan(self.led, items)
        self.assertEqual(len(ops), 1)  # one event for the date; dining (never used) is left out
        ev = ops[0]
        self.assertEqual(ev["payload"]["title"], "Card credits ending (2)")
        self.assertEqual(ev["payload"]["visibility"], "private")
        h, _ = fl.preview_batch(self.led, ops)
        op_id = fl.apply_batch(self.led, ops, h, S)[0]["op_id"]
        fl.set_op_state(self.led, op_id, "sent", S)
        rb = {k: ev["payload"][k] for k in ("title", "date", "reminder_minutes", "visibility", "attendees", "description")}
        fl.set_op_state(self.led, op_id, "confirmed", S, destination_id="evt123", read_back=rb)
        # the airline credit posts → the same event is updated, not duplicated
        acc, tx = self.txns([{"id": "a", "date": "2026-12-05", "amount": 200, "direction": "credit", "kind": "credit",
                              "description": "AIRLINE FEE CREDIT"}], cov_to="2026-12-06")
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 12, 6), 2026)
        ops = expirations.calendar_plan(self.led, expirations.collect(self.led, res, dt.date(2026, 12, 6), 45))
        self.assertEqual([o["action"] for o in ops], ["update"])
        self.assertEqual(ops[0]["payload"]["title"], "Card credits ending (1)")
        h, _ = fl.preview_batch(self.led, ops)
        op2 = fl.apply_batch(self.led, ops, h, S)[0]["op_id"]
        fl.set_op_state(self.led, op2, "sent", S)
        fl.set_op_state(self.led, op2, "confirmed", S, read_back={"title": "Card credits ending (1)",
                                                                  "date": "2026-12-31", "reminder_minutes": 4320,
                                                                  "visibility": "private", "attendees": [],
                                                                  "description": ops[0]["payload"]["description"]})
        # the person says the app cash was used → event gets ✓ and loses its reminder
        b = [{"op": "observe", "subject": "benefit:t1/app-cash/2026-12", "field": "used_amount", "value": 15,
              "source": {"kind": "person"}, "as_of": "2026-12-06", "confidence": "confirmed"}]
        h, _ = fl.preview_batch(self.led, b)
        fl.apply_batch(self.led, b, h, S)
        res = credits.analyze(self.led, self.catalog, acc, tx, dt.date(2026, 12, 6), 2026)
        ops = expirations.calendar_plan(self.led, expirations.collect(self.led, res, dt.date(2026, 12, 6), 45))
        self.assertEqual(len(ops), 1)
        self.assertTrue(ops[0]["payload"]["title"].startswith("✓ "))
        self.assertIsNone(ops[0]["payload"]["reminder_minutes"])


class LedgerRules(unittest.TestCase):
    def test_preview_hash_required(self):
        led = ledger_with()
        b = [{"op": "set_setting", "key": "calendar_min_value", "value": 50}]
        with self.assertRaises(fl.LedgerError):
            fl.apply_batch(led, b, "wrong", S)

    def test_lease_blocks_second_conversation(self):
        led = ledger_with()
        with self.assertRaises(fl.LedgerError):
            fl.acquire_lease(led, "other-session")
        fl.acquire_lease(led, "other-session", transfer=True)
        with self.assertRaises(fl.LedgerError):
            fl.require_lease(led, S)

    def test_forbidden_data_refused(self):
        led = ledger_with()
        for bad in ("4111 1111 1111 1111", "password: hunter2", "SSN 123-45-6789"):
            b = [{"op": "observe", "subject": "card:x", "field": "note", "value": bad, "source": {"kind": "person"},
                  "as_of": "2026-01-01", "confidence": "confirmed"}]
            with self.assertRaises(fl.LedgerError):
                fl.preview_batch(led, b)

    def test_date_based_ids_are_not_card_numbers(self):
        self.assertEqual(fl.scan_forbidden({"id": "fee-amex-gold-2025-03-13-40589259"}), [])
        self.assertEqual(fl.scan_forbidden({"note": "4111-1111-1111-1111"}), ["a full card number"])
        self.assertEqual(fl.scan_forbidden({"ref": "1234567890123456"}), [])  # fails Luhn

    def test_records_never_overwritten_and_never_deleted(self):
        led = ledger_with([{"op": "add_cost", "id": "c1", "date": "2026-01-01", "kind": "tool", "amount": 10,
                            "currency": "USD"}])
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, [{"op": "add_cost", "id": "c1", "date": "2026-01-01", "kind": "tool", "amount": 99,
                                    "currency": "USD"}])
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, [{"op": "external", "target": "finance_app", "action": "delete", "payload": {},
                                    "summary": "x"}])

    def test_amend_keeps_history_and_needs_consent(self):
        led = ledger_with([{"op": "add_card", "id": "csp", "person": "me", "nickname": "Sapphire"}])
        b = [{"op": "amend", "target": "cards", "id": "csp", "field": "anniversary", "value": "07-15",
              "reason": "the person said they opened it in July 2023"}]
        h, text = fl.preview_batch(led, b)
        self.assertIn("Change anniversary of csp", text)
        fl.apply_batch(led, b, h, S)
        card = led["cards"][0]
        self.assertEqual(card["anniversary"], "07-15")
        self.assertEqual(card["amendments"][0]["old"], None)
        with self.assertRaises(fl.LedgerError):  # no partner with consent yet
            fl.preview_batch(led, [{"op": "amend", "target": "cards", "id": "csp", "field": "person", "value": "p2",
                                    "reason": "partner's card"}])
        b = [{"op": "add_person", "id": "p2", "name": "Partner", "consent": {"given": True, "on": "2026-11-02"}},
             {"op": "amend", "target": "cards", "id": "csp", "field": "person", "value": "p2", "reason": "partner's card"}]
        h, _ = fl.preview_batch(led, b)
        fl.apply_batch(led, b, h, S)
        self.assertEqual(led["cards"][0]["person"], "p2")

    def test_void_hides_value_keeps_history(self):
        led = ledger_with([{"op": "observe", "subject": "account:a", "field": "balance", "value": 100,
                            "source": {"kind": "person"}, "as_of": "2026-01-01", "confidence": "confirmed"}])
        oid = led["observations"][0]["id"]
        ledger_b = [{"op": "void", "target": oid, "reason": "typo"}]
        h, _ = fl.preview_batch(led, ledger_b)
        fl.apply_batch(led, ledger_b, h, S)
        self.assertIsNone(fl.current(led, "account:a", "balance"))
        self.assertEqual(len(led["observations"]), 1)

    def test_same_day_conflict_shown(self):
        led = ledger_with([
            {"op": "observe", "subject": "account:a", "field": "balance", "value": 100, "source": {"kind": "email"},
             "as_of": "2026-01-01", "confidence": "confirmed"},
            {"op": "observe", "subject": "account:a", "field": "balance", "value": 120,
             "source": {"kind": "program_page"}, "as_of": "2026-01-01", "confidence": "confirmed"}])
        cur = fl.current(led, "account:a", "balance")
        self.assertEqual(cur["value"], 120)
        self.assertEqual(cur["conflicts"][0]["value"], 100)

    def test_external_op_states_and_readback(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "e",
              "payload": {"title": "Resy credit ends", "date": "2026-12-31", "reminder_minutes": 4320,
                          "visibility": "private"}}]
        h, _ = fl.preview_batch(led, b)
        op_id = fl.apply_batch(led, b, h, S)[0]["op_id"]
        with self.assertRaises(fl.LedgerError):  # planned → confirmed skips «sent»
            fl.set_op_state(led, op_id, "confirmed", S, "e1", {"title": "Resy credit ends"})
        fl.set_op_state(led, op_id, "sent", S)
        with self.assertRaises(fl.LedgerError):  # read-back mismatch
            fl.set_op_state(led, op_id, "confirmed", S, "e1", {"title": "Resy credit ends", "reminder_minutes": 10})
        fl.set_op_state(led, op_id, "unknown", S)
        with self.assertRaises(fl.LedgerError):  # an empty read-back never confirms
            fl.set_op_state(led, op_id, "confirmed", S, "e1", {})
        fl.set_op_state(led, op_id, "confirmed", S, "e1", {"title": "Resy credit ends", "date": "2026-12-31",
                                                             "reminder_minutes": 4320, "visibility": "private", "attendees": []})
        self.assertEqual(led["calendar_events"][0]["event_id"], "e1")
        # planning the same write again is recognized, not repeated
        h2, text = fl.preview_batch(led, b)
        self.assertIn("already confirmed", text)
        self.assertTrue(fl.apply_batch(led, b, h2, S)[0]["skipped"])

    def test_failed_write_retry_keeps_history(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "e",
              "payload": {"title": "Credits ending (1)", "date": "2026-12-31", "reminder_minutes": 4320,
                          "visibility": "private"}}]
        h, _ = fl.preview_batch(led, b)
        first = fl.apply_batch(led, b, h, S)[0]["op_id"]
        fl.set_op_state(led, first, "failed", S, error="connector timeout")
        h, text = fl.preview_batch(led, b)
        self.assertIn("retry", text)
        second = fl.apply_batch(led, b, h, S)[0]["op_id"]
        self.assertNotEqual(first, second)
        self.assertEqual([x["state"] for x in led["oplog"]], ["failed", "planned"])
        self.assertEqual(led["oplog"][0]["error"], "connector timeout")

    def test_changed_payload_under_same_key_is_refused(self):
        led = ledger_with()
        mk = lambda d: [{"op": "external", "target": "calendar", "action": "create", "summary": "e", "match_key": "k1",
                         "payload": {"title": "Credits ending (1)", "date": d, "reminder_minutes": 4320}}]
        h, _ = fl.preview_batch(led, mk("2026-12-31"))
        op_id = fl.apply_batch(led, mk("2026-12-31"), h, S)[0]["op_id"]
        fl.set_op_state(led, op_id, "sent", S)
        fl.set_op_state(led, op_id, "confirmed", S, "e9", {"title": "Credits ending (1)", "date": "2026-12-31",
                                                             "reminder_minutes": 4320, "visibility": "private", "attendees": []})
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, mk("2027-01-05"))

    def test_preview_shows_real_payload(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "Harmless summary",
              "payload": {"title": "Bilt hotel credit ends", "date": "2026-12-31", "reminder_minutes": 4320}}]
        _, text = fl.preview_batch(led, b)
        self.assertIn("title=Bilt hotel credit ends", text)
        self.assertIn("date=2026-12-31", text)

    def test_unknown_record_fields_are_refused(self):
        led = ledger_with()
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, [red("r1", "2025-05-01", 1000, 0, None, None, fallback_price=100)])

    def test_amended_redemption_feeds_the_report(self):
        led = ledger_with([red("r1", "2025-05-01", 10000, 10, 100, 200)])
        b = [{"op": "amend", "target": "redemptions", "id": "r1", "field": "status", "value": "cancelled",
              "reason": "trip cancelled, points returned"}]
        h, _ = fl.preview_batch(led, b)
        fl.apply_batch(led, b, h, S)
        self.assertEqual(yir.compute(led, 2025)["income"]["cash_avoided"], 0)
        self.assertEqual(led["redemptions"][0]["amendments"][0]["old"], "booked")

    def test_foreign_currency_needs_a_rate(self):
        led = ledger_with()
        cost = {"op": "add_cost", "id": "c1", "date": "2025-04-01", "kind": "points_purchase", "amount": 100,
                "currency": "EUR"}
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, [cost])
        cost.update(fx_rate=1.2, fx_source="ECB 2025-04-01")
        h, _ = fl.preview_batch(led, [cost])
        fl.apply_batch(led, [cost], h, S)
        self.assertEqual(yir.compute(led, 2025)["costs"]["points_purchased"], 120)

    def test_secret_fields_and_text_refused(self):
        led = ledger_with()
        for bad in ({"password": "hunter2"}, {"api_key": "abc-secret"}, "passport AB1234567", "4111.1111.1111.1111",
                    "OTP 123456", "Hilton Honors number 123456789"):
            b = [{"op": "observe", "subject": "card:x", "field": "note", "value": bad, "source": {"kind": "person"},
                  "as_of": "2026-01-01", "confidence": "confirmed"}]
            with self.assertRaises(fl.LedgerError, msg=str(bad)):
                fl.preview_batch(led, b)

    def test_event_titles_without_balances(self):
        led = ledger_with()
        b = [{"op": "external", "target": "calendar", "action": "create", "summary": "e",
              "payload": {"title": "Use 120,000 points", "date": "2026-12-31", "visibility": "private"}}]
        with self.assertRaises(fl.LedgerError):
            fl.preview_batch(led, b)

    def test_save_refuses_stale_version(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.json"
            led = fl.new_ledger("T")
            led["version"] = 1
            p.write_text(json.dumps(led))
            a = fl.load(p)
            b = fl.load(p)
            fl.save(p, a, 1)
            with self.assertRaises(fl.LedgerError):
                fl.save(p, b, 1)
            self.assertEqual(fl.load(p)["version"], 2)

    def test_redaction_removes_member_rows_only(self):
        led = ledger_with([
            {"op": "add_person", "id": "p2", "name": "Partner", "consent": {"given": True, "on": "2026-01-01"}},
            {"op": "add_card", "id": "c2", "person": "p2", "nickname": "Partner card"},
            {"op": "add_card", "id": "c1", "person": "me", "nickname": "My card"},
            {"op": "observe", "subject": "benefit:c2/x/2026", "field": "credited", "value": 5,
             "source": {"kind": "person"}, "as_of": "2026-01-01", "confidence": "confirmed"},
        ])
        h, plan, text = fl.redaction_plan(led, "p2")
        self.assertIn("Not changed", text)
        fl.redact_person(led, "p2", h, S)
        self.assertEqual([c["id"] for c in led["cards"]], ["c1"])
        self.assertEqual(led["observations"], [])
        with self.assertRaises(fl.LedgerError):
            fl.redaction_plan(led, "me")

    def test_csv_export_neutralizes_formulas(self):
        self.assertEqual(fl._cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(fl._cell("-12.5"), "-12.5")


class Periods(unittest.TestCase):
    def test_period_keys(self):
        d = dt.date(2026, 8, 15)
        self.assertEqual(ff.period_of("half_year", d)[0], "2026-H2")
        self.assertEqual(ff.period_of("quarter", d)[0], "2026-Q3")
        self.assertIsNone(ff.period_of("card_year", d))
        k, s, e = ff.period_of("card_year", d, "03-13")
        self.assertEqual((s, e), (dt.date(2026, 3, 13), dt.date(2027, 3, 12)))


class Catalog(unittest.TestCase):
    def test_catalog_valid(self):
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_facts.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
