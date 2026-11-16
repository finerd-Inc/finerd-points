"""The report built from the ledger alone (spec v2, «The report»)."""
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import fpcollect as fc  # noqa: E402
import fpledger as fl  # noqa: E402
import render_report as rr  # noqa: E402
import report  # noqa: E402

TODAY = dt.date(2026, 11, 16)


def sample():
    led = fl.new_ledger("Rad", storage="folder")
    b = [{"op": "add_inventory", "id": "inv-hyatt", "kind": "program", "label": "World of Hyatt", "person": "me"},
         {"op": "add_account", "id": "inv-hyatt", "person": "me", "program": "world-of-hyatt",
          "nickname": "World of Hyatt", "unit": "points"},
         {"op": "add_source", "id": "hyatt", "kind": "program", "name": "World of Hyatt", "hosts": ["www.hyatt.com"],
          "accounts": [{"id": "woh", "label": "World of Hyatt", "person": "me", "unit": "points",
                        "inventory": "inv-hyatt"}]},
         {"op": "observe", "subject": "account:inv-hyatt", "field": "balance", "value": 52310,
          "source": {"kind": "program_page", "name": "hyatt.com", "ref": "hyatt"}, "as_of": "2026-11-10",
          "confidence": "confirmed"},
         {"op": "observe", "subject": "account:inv-hyatt", "field": "balance", "value": 38000,
          "source": {"kind": "awardwallet", "name": "AwardWallet"}, "as_of": "2026-11-16", "confidence": "likely",
          "note": "updated 5 months ago"}]
    fl.apply_batch(led, b, fl.preview_batch(led, b)[0])
    rd = {"source": "hyatt", "account": "woh", "section": "activity", "read_id": "r1",
          "requested": ["2025-01-01", "2026-11-16"], "covered": ["2026-01-01", "2026-11-16"], "state": "partial",
          "stop_reason": "Load more stopped adding rows at 26 Nov 2024", "read_at": "2026-11-16T12:00:00Z",
          "unit": "points", "rows": [{"date": "2026-10-05", "amount": 5000,
                                      "description": "<script>alert(1)</script> Stay", "status": "posted"}]}
    bb, _ = fc.plan_read(led, rd)
    fl.apply_batch(led, bb, fl.preview_batch(led, bb)[0])
    return led


class Report(unittest.TestCase):

    def test_direct_read_wins_over_a_newer_aggregator_value(self):
        r = report.build(sample(), TODAY)
        row = r["balances"]["accounts"][0]
        self.assertEqual((row["balance"], row["link"]), (52310, "https://www.hyatt.com"))
        self.assertEqual(row["aggregator"]["freshness"], "updated 5 months ago")

    def test_order_problems_and_note(self):
        r = report.build(sample(), TODAY)
        md = report.to_markdown(r)
        order = [md.index(x) for x in ("## Balances", "Card credits", "Deadlines in the next", "Year in Review",
                                       "## What was read")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Load more stopped adding rows", md)
        self.assertIn("re-reads the last 60 days", md)
        self.assertIn("World of Hyatt: points expiry date not known", md)

    def test_html_escapes_page_text(self):
        led = sample()
        r = report.build(led, TODAY)
        page = rr.render(led, TODAY, "Points & Miles", r["year_in_review"], r["credits"],
                         {"items": r["deadlines"]["items"], "days": 45}, collection=r["collection"],
                         unknown_deadlines=r["deadlines"]["unknown"], balances_table=r["balances"],
                         refresh_note=r["refresh_note"])
        self.assertNotIn("<script>", page)
        self.assertLess(page.index("id='balances'"), page.index("id='collected'"))


if __name__ == "__main__":
    unittest.main()


class Acceptance(unittest.TestCase):

    def test_compare_finds_missing_extra_and_partial(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import acceptance_compare as ac
        led = sample()
        ref = {"accounts": [{"source": "hyatt", "account": "woh", "section": "activity",
                             "interval": ["2026-01-01", "2026-11-16"],
                             "rows": [["2026-10-05", 5000, "alert(1) Stay"], ["2026-03-01", 900, "Old stay"]],
                             "balance": {"subject": "account:inv-hyatt", "value": 52310}}]}
        ok, out = ac.compare(led, ref)
        self.assertFalse(ok)
        kinds = {list(p)[0] for p in out[0]["problems"]}
        self.assertEqual(kinds, {"missing_rows", "coverage"})  # the sample read is partial
        ref["accounts"][0]["excluded"] = {"reason": "frozen before the run"}
        self.assertTrue(ac.compare(led, ref)[0])


class Bridge(unittest.TestCase):

    def test_card_site_rows_reach_the_credit_calculator(self):
        led = fl.new_ledger("Rad", storage="folder")
        b = [{"op": "add_card", "id": "gold", "person": "me", "nickname": "Gold", "catalog_ref": "amex-gold",
              "opened_on": "2024-03-13"},
             {"op": "add_inventory", "id": "gold", "kind": "card", "label": "Amex Gold", "person": "me"},
             {"op": "add_source", "id": "amex", "kind": "bank_card", "name": "American Express",
              "hosts": ["global.americanexpress.com"], "unit": "USD",
              "accounts": [{"id": "gold-card", "label": "Gold Card", "person": "me", "unit": "USD",
                            "inventory": "gold"}]}]
        fl.apply_batch(led, b, fl.preview_batch(led, b)[0])
        rd = {"source": "amex", "account": "gold-card", "section": "activity", "read_id": "r1",
              "requested": ["2026-01-01", "2026-11-16"], "covered": ["2026-01-01", "2026-11-16"],
              "state": "complete", "terminal": "statement period start reached",
              "continuity": "statement balances chain", "read_at": "2026-11-16T12:00:00Z", "unit": "USD",
              "rows": [{"date": "2026-09-10", "amount": 50, "description": "AMEX RESY CREDIT", "status": "posted"},
                       {"date": "2026-09-05", "amount": -120, "description": "RESY RESTAURANT", "status": "posted"}]}
        bb, _ = fc.plan_read(led, rd)
        fl.apply_batch(led, bb, fl.preview_batch(led, bb)[0])
        r = report.build(led, TODAY)
        resy = next(x for x in r["credits"]["cards"][0]["benefits"] if x["benefit"] == "resy-credit")
        p = next(p for p in resy["periods"] if p["key"] == "2026-H2")
        self.assertEqual((p["status"], p["used"]), ("used", 50.0))
        self.assertEqual(led["cards"][0].get("finance_link"), None)  # the ledger itself is not changed


class ReviewRound2Report(unittest.TestCase):

    def _gold(self, extra_sources=()):
        led = fl.new_ledger("Rad", storage="folder")
        b = [{"op": "add_card", "id": "gold", "person": "me", "nickname": "Gold", "catalog_ref": "amex-gold",
              "opened_on": "2024-03-13"},
             {"op": "add_inventory", "id": "gold", "kind": "card", "label": "Amex Gold", "person": "me"}] + \
            list(extra_sources) + \
            [{"op": "add_source", "id": "amex", "kind": "bank_card", "name": "American Express", "unit": "USD",
              "accounts": [{"id": "gold-card", "label": "Gold Card", "person": "me", "unit": "USD",
                            "inventory": "gold"}]}]
        fl.apply_batch(led, b, fl.preview_batch(led, b)[0])
        rd = {"source": "amex", "account": "gold-card", "section": "activity", "read_id": "r1",
              "requested": ["2026-01-01", "2026-11-16"], "covered": ["2026-01-01", "2026-11-16"],
              "state": "complete", "terminal": "t", "continuity": "c", "read_at": "2026-11-16T12:00:00Z",
              "unit": "USD", "rows": [{"date": "2026-09-10", "amount": 25, "description": "AMEX RESY CREDIT",
                                       "status": "posted"}]}
        bb, _ = fc.plan_read(led, rd)
        fl.apply_batch(led, bb, fl.preview_batch(led, bb)[0])
        return led

    def _resy(self, led):
        r = report.build(led, TODAY)
        b = next(x for x in r["credits"]["cards"][0]["benefits"] if x["benefit"] == "resy-credit")
        return next(p for p in b["periods"] if p["key"] == "2026-H2")

    def test_an_aggregator_account_never_takes_the_cards_transactions(self):
        aw = {"op": "add_source", "id": "aw", "kind": "aggregator", "name": "AwardWallet", "unit": "USD",
              "accounts": [{"id": "aw-gold", "label": "Gold in AwardWallet", "person": "me", "unit": "USD",
                            "inventory": "gold"}]}
        self.assertEqual(self._resy(self._gold([aw]))["used"], 25.0)

    def test_damaged_ledger_report_comes_from_the_backup_marked(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "backups").mkdir()
            good = sample()
            (root / "backups" / "ledger.v3-abcdef12.json").write_text(__import__("json").dumps(good))
            (root / "ledger.json").write_text("{ damaged")
            p = subprocess.run([sys.executable, str(ROOT / "shared" / "lib" / "report.py"), "--ledger",
                                str(root / "ledger.json"), "--today", "2026-11-16"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("shown read-only from the backup ledger.v3-abcdef12.json", p.stdout)


class ReviewRound2Credits(unittest.TestCase):

    def test_uncatalogued_card_periods_count_in_their_own_year(self):
        import credits
        import fpfacts as ff
        led = fl.new_ledger("T", storage="folder")
        b = [{"op": "add_card", "id": "local", "person": "me", "nickname": "Local"}]
        for key in ("2025", "2026"):
            b.append({"op": "observe", "subject": f"benefit:local/travel/{key}", "field": "used_amount", "value": 100,
                      "source": {"kind": "issuer_page"}, "as_of": "2026-11-16", "confidence": "confirmed"})
        fl.apply_batch(led, b, fl.preview_batch(led, b)[0])
        res = credits.analyze(led, ff.load_catalog(ROOT / "shared" / "facts"), {}, [], TODAY, 2026)
        self.assertEqual(credits.totals(res)["used"], 100)


class ReviewRound3Bridge(unittest.TestCase):

    def test_all_of_a_cards_own_sources_count(self):
        led = ReviewRound2Report()._gold([{"op": "add_source", "id": "stmt", "kind": "statement", "name": "Statement",
                                           "unit": "USD", "accounts": [{"id": "st", "label": "Gold statement",
                                                                        "person": "me", "unit": "USD",
                                                                        "inventory": "gold"}]}])
        rd = {"source": "stmt", "account": "st", "section": "activity", "read_id": "s1",
              "requested": ["2026-01-01", "2026-11-16"], "covered": ["2026-01-01", "2026-11-16"], "state": "complete",
              "terminal": "t", "continuity": "c", "read_at": "2026-11-16T12:00:00Z", "unit": "USD",
              "rows": [{"date": "2026-08-01", "amount": -40, "description": "Purchase A", "status": "posted"},
                       {"date": "2026-08-02", "amount": -30, "description": "Purchase B", "status": "posted"}]}
        bb, _ = fc.plan_read(led, rd)
        fl.apply_batch(led, bb, fl.preview_batch(led, bb)[0])
        self.assertEqual(ReviewRound2Report()._resy(led)["used"], 25.0)


class ReviewRound4Bridge(unittest.TestCase):

    def test_statements_with_a_gap_claim_only_the_latest_contiguous_span(self):
        import report as rp
        self.assertEqual(rp._latest_contiguous([["2026-01-01", "2026-01-31"], ["2026-11-01", "2026-11-16"]]),
                         ["2026-11-01", "2026-11-16"])
        self.assertEqual(rp._latest_contiguous([["2026-01-01", "2026-06-30"], ["2026-07-01", "2026-11-16"]]),
                         ["2026-01-01", "2026-11-16"])
