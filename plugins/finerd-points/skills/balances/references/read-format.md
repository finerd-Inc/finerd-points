# What a read looks like (input to `ledger.py plan-read`)

One JSON object per account section read, or a list of them. Write it to the working file
`<folder>/work/read-<source>-<date>.json` page by page as you read; `plan-read` turns it into the
batch the person previews.

```json
{
  "source_op": {"op": "add_source", "id": "hyatt", "kind": "program", "name": "World of Hyatt",
                "hosts": ["www.hyatt.com"], "market": "US", "unit": "points",
                "accounts": [{"id": "woh", "label": "World of Hyatt", "person": "me", "unit": "points",
                              "inventory": "inv-hyatt"}]},
  "source": "hyatt",
  "account": "woh",
  "section": "activity",
  "read_id": "hyatt-2026-11-16-1",
  "requested": ["2025-01-01", "2026-11-16"],
  "covered": ["2025-01-01", "2026-11-16"],
  "state": "complete",
  "terminal": "earliest row 26 Nov 2024 is before the requested start",
  "continuity": "running balance chains from 0 to 52,310",
  "stop_reason": null,
  "incomplete_days": [],
  "opening_balance": null,
  "as_of_text": null,
  "read_at": "2026-11-16T12:30:00Z",
  "unit": "points",
  "rows": [
    {"date": "2026-10-05", "amount": 5000, "description": "Stay at Park Hyatt Tokyo",
     "status": "posted", "site_id": null,
     "evidence": {"text": "Oct 5, 2026 Park Hyatt Tokyo +5,000", "where": "My Account > Activity",
                  "method": "text"}}
  ]
}
```

- `source_op` only the first time a source is seen (`kind`: program, bank_card, aggregator, sheet,
  email, statement, other). Each account names its owner (`person`, who must be in the ledger with
  consent) and, when known, the inventory item it belongs to. For a card's own site use the card's id as
  `inventory` and the currency as `unit` (for example `USD`): its activity rows then count as the card's
  transactions for credits.
- `section`: `activity` (every dated row, including statement credits on a card's activity) or
  `certificates`; nothing else is accepted. What an issuer's benefits tracker shows («$50 of $50 used») is not a row: record it
  as an observation (`used_amount` from `issuer_page`, with `allowance` and `period_end` when shown).
- `covered`: the interval this read covers **completely**, or `null` if none. `state`:
  `complete` (needs `terminal`, `continuity` and `covered`), `ends_unreconciled`, `partial`,
  `unavailable`.
- `amount`: signed; points earned positive, redeemed or expired negative; money in the account's
  currency, credits positive.
- `site_id`: the site's own row id when the page shows one; leave it out otherwise.
- Text fields are cleaned by `plan-read` (markup, control characters and identifiers removed,
  length capped). Never put a full card, account or member number anywhere.

Balances, credit trackers and deadlines are not rows: record them as observations in the same batch
(`observe`, with the on-page text in `note`), as in `record-shapes.md`.
