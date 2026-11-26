# Record shapes (unknown fields are refused)
```json
{"op":"add_card","id":"amex-gold","person":"me","nickname":"Amex Gold","catalog_ref":"amex-gold",
 "anniversary":"03-13","opened_on":"2023-03-13","last4":"1234",
 "finance_link":{"app":"finerd","account_id":"…","account_name":"AmEx Gold"}}
{"op":"add_account","id":"hyatt","person":"me","program":"world-of-hyatt","nickname":"World of Hyatt",
 "unit":"points","finance_link":{"app":"finerd","account_id":"…"}}
{"op":"observe","subject":"account:hyatt","field":"balance","value":123456,"unit":"points",
 "source":{"kind":"person"},"as_of":"2026-11-02","confidence":"confirmed"}
{"op":"observe","subject":"account:hyatt","field":"expires_on","value":"2027-05-01",
 "source":{"kind":"email","name":"World of Hyatt statement"},"as_of":"2026-11-02","confidence":"confirmed"}
{"op":"add_redemption","id":"red-2025-01","person":"me","program":"world-of-hyatt","booked_on":"2025-05-10",
 "points":25000,"fees":0,"fallback":420,"normalized":610,"status":"booked","description":"2 nights",
 "purchased_points_cost":null,"currency":"USD"}
{"op":"add_cost","id":"fee-2025-gold","date":"2025-03-13","kind":"annual_fee","amount":325,"currency":"USD",
 "card":"amex-gold"}
{"op":"add_certificate","id":"hyatt-fn-2026","account":"hyatt","type":"Hyatt free night (Cat 1-4)",
 "expires_on":"2027-02-01"}
{"op":"add_signup_offer","id":"bilt-sub","card":"bilt-palladium","bonus":"50,000 points","spend":4000,
 "deadline":"2026-05-08"}
{"op":"add_person","id":"p2","name":"Anna","consent":{"given":true,"on":"2026-11-02"}}
{"op":"add_inventory","id":"hyatt","kind":"program","label":"World of Hyatt","person":"me","found_by":"email"}
{"op":"void","target":"obs-1a2b3c4d","reason":"read from the wrong account"}
{"op":"resolve_link","link":"lnk-1a2b3c4d","decision":"same"}
{"op":"resolve_not_shown","record":"rec-0a1b2c3d4e","decision":"gone"}
```
- `add_inventory` `kind`: program | card | bank | app | aggregator | sheet | other; `found_by`: person |
  email | source. A program's inventory item and its `add_account` share one id; a card's and its
  `add_card` share one id.
- Sources, coverage and rows (`add_source`, `add_coverage`, `add_record` and the rest) are produced by
  `ledger.py plan-read` from a read (`read-format.md`). A source's accounts are fixed when it is added: an
  account found later in the same site gets a new source id (for example `amex-2`).
- `status`: booked | cancelled (points and fees returned) | cancelled_with_fee (add
  `cancellation_fee` and `cancelled_on`). Cost `kind`: annual_fee | points_purchase | tool |
  cancellation_fee | other. Amounts in another currency need `fx_rate` (report currency per unit:
  the finance app's rate, else the ECB rate of that date) and `fx_source`.
- `fallback` is what the person would really have paid in cash; `normalized` is the normalized
  price of an equivalent cash option. Leave them null (and say so) rather than guessing.
- Settings: `{"op":"set_setting","key":"foregone_cashback_rate","value":0.02}`, also
  `foregone_cashback_exclusions` (["rent","amazon"]), `calendar_min_value`, `reminder_days_before`,
  `stale_after_days`, `credit_values` ({"amex-gold/uber-cash": 0.5}).

- `purchased_points_cost` on a redemption is for the record only: the purchase itself is an
  `add_cost` with `kind` points_purchase in the year it was bought, so it counts once (rule 4).
- Correct a record with `{"op":"amend","target":"cards|accounts|redemptions|costs|certificates|signup_offers",
  "id":"…","field":"…","value":…,"reason":"…"}`; required fields can never be emptied.
