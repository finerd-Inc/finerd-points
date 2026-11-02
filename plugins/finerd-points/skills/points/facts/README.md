# Facts catalog

Card terms and program rules live here as data, never in a model's memory. Every
skill folder ships the subset it needs (copied by `tools/build.py`; CI checks the
copies match).

## Rules for every fact

- The issuer's or program's own page is the primary source. Reviews (One Mile at a
  Time, The Points Guy, NerdWallet, AwardWallet, Frequent Miler…) corroborate.
- What all sources agree on is recorded as the fact. Where they differ, both
  values go into `disagreements` with their sources; the skill shows both.
- Every card file carries `checked_on`. A fact not re-checked for more than 90
  days is shown as **unverified**.
- Terms change. Old versions are never edited in place: a changed benefit gets a
  new entry with `effective_from`, and the old one gets `effective_to`. Every
  calculation stores the `rule_version` it used.
- `null` means «not found», never zero.
- No third-party text is copied: summarize in your own words and link the source.

## Card file (`cards/<id>.json`)

```jsonc
{
  "schema": "finerd-points/card@1",
  "id": "amex-gold",                      // kebab-case, stable forever
  "name": "American Express Gold Card",
  "issuer": "American Express",
  "country": "US",
  "segment": "personal",                  // personal | business
  "currency": "USD",
  "rewards_program": "amex-membership-rewards", // programs/<id>.json
  "rule_version": "2026-11-02",           // bump when anything below changes
  "checked_on": "2026-11-02",
  "terms_from": null,                     // optional: the catalog vouches for terms only from this date;
                                          // earlier periods are shown as «amounts may differ»
  "annual_fee": [
    {"amount": 325, "effective_from": "2024-07-25", "effective_to": null,
     "note": "New applicants from 2024-07-25; existing accounts at renewal from 2024-10-01.",
     "sources": ["G1", "G4"]}
  ],
  "benefits": [
    {
      "id": "dining-credit",              // unique within the card
      "name": "Dining credit",
      "kind": "statement_credit",         // statement_credit | wallet_credit | folio_credit |
                                          // certificate | status | percentage_credit |
                                          // membership_credit | redemption_option | other
                                          // (redemption_option = a way to spend a balance the
                                          //  person already has, e.g. Bilt Cash; never counted
                                          //  as a credit)
      "amount": 10,                       // per period, card currency; null if not money
      "period": "month",                  // month | quarter | half_year | calendar_year |
                                          // card_year | per_stay | per_booking | ongoing | one_time
      "annual_max": 120,
      "carryover": false,
      "enrollment": "required",           // required | not_required | unknown
      "enrollment_how": "Enroll in the Amex account.",
      "qualifying": "Short own-words summary of what qualifies.",
      "evidence": "statement_credit",     // how a person can see it was used:
                                          // statement_credit (visible in bank transactions) |
                                          // wallet (inside a merchant app) | folio (hotel bill) |
                                          // program_account | none
      "match": {                          // only for evidence = statement_credit
        "keywords": ["DINING", "GRUBHUB", "FIVE GUYS"],   // whole words in the bank description
        "posting_lag_days": 56,           // optional: credits may post this long after purchase
        "verified": false                 // true only once a real bank description matched
      },
      "requires": null,                   // or {"kind": "spend_threshold"|"activation"|"membership"|"other",
                                          //     "note": "$5,000 of Dell purchases in the year"}:
                                          //  a credit that opens only after a condition is never shown as
                                          //  money waiting to be used
      "shared_group": null,               // e.g. "amex-venue-concessions": one allowance per person
      "effective_from": "2024-07-25",
      "effective_to": null,
      "note": null,
      "sources": ["G1", "G2", "G3"]
    }
  ],
  "certificates": [                       // free nights, companion vouchers
    {"id": "anniversary-free-night", "name": "Free night award",
     "trigger": "card_anniversary",       // card_anniversary | spend_threshold | welcome_offer
     "spend_threshold": null, "value_cap": "Up to 35,000 points", "valid_months": 12,
     "note": "Use rules in own words.", "sources": ["H1"]}
  ],
  "thresholds": [                         // spend thresholds that unlock something
    {"id": "15k-free-night", "spend": 15000, "period": "calendar_year",
     "unlocks": "Second free night award", "sources": ["H1"]}
  ],
  "disagreements": [
    {"topic": "…", "values": [{"value": "…", "sources": ["G1"]}, {"value": "…", "sources": ["G3"]}]}
  ],
  "upcoming_changes": [
    {"effective_from": "2027-01-01", "summary": "…", "sources": ["G1"]}
  ],
  "sources": {
    "G1": {"title": "Amex benefits and terms", "url": "https://…", "publisher": "American Express",
           "kind": "issuer", "published": null, "checked_on": "2026-11-02"}
  }
}
```

`kind` of a source: `issuer` (bank or card network), `program` (loyalty program),
`review` (independent site), `community` (forum, Reddit).

## Program file (`programs/<id>.json`)

```jsonc
{
  "schema": "finerd-points/program@1",
  "id": "world-of-hyatt",
  "name": "World of Hyatt",
  "unit": "points",                       // points | miles | cash
  "kind": "hotel",                        // hotel | airline | bank | other
  "expiry": {"rule": "activity", "months": 24, "note": "…", "sources": ["P1"]},
  "checked_on": "2026-11-02",
  "sources": {}
}
```
