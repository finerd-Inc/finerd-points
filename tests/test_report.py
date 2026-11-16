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
