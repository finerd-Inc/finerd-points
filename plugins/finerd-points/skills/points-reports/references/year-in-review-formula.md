# Year in Review — formula

Source of the method: the framework «Accounting for Loyalty Currencies in Personal Finances»
(v1.2, 9 September 2026), §5.1 «Realized Game Result», from the paper in preparation «Points Are
Not Just Points: Accounting for Loyalty Currencies in Personal Financial Statements». Under its
principle P1, buying points is an expense at the moment of purchase. Points are an analytical
layer: they never enter net worth.

The year is the calendar year. Amounts are in the person's report currency; amounts in another
currency are converted at the transaction-date rate (finance app rate, otherwise the European
Central Bank daily rate, using the last published rate before weekends and holidays), keeping the
original amount and rate.

## Formula

**Game income** (two variants, because a redemption's value depends on what it is compared with):
- **Cash avoided** = Σ over the year's redemptions (`fallback − fees`). `fallback` is what the
  person would really have paid in cash without points (economy instead of business, a cheaper
  hotel); `fees` are taxes and fees paid in cash at redemption.
- **Value redeemed** = Σ over the year's redemptions (`normalized − fees`). `normalized` is the
  normalized price of an equivalent cash option. The retail price of that exact ticket is never used.

**Game costs:**
- purchased points (cash paid for points, in the year of purchase);
- services and tools (award-search subscriptions, trackers);
- card annual fees paid in the year, including a partner's cards in a shared ledger;
- cancellation fees that were not refunded;
- **foregone cash back** = rate × card purchases for the year minus exclusions, personal and
  business counted separately. The rate and exclusions are the person's settings (for example 2%,
  rent and Amazon excluded).

**Result:** net (fallback) = cash avoided − costs; net (value) = value redeemed − costs.

**Card credits** used are a separate line; the result is shown with and without them, valued at
the credit's face amount unless the person sets a lower «would really pay» value.

## Rules
1. A redemption counts in the year it was booked, at the points actually taken, regardless of
   when the points were earned.
2. A transfer between programs is movement, not income. A transfer bonus is not income either
   until the points are redeemed.
3. A cancelled redemption with points and fees returned is removed from the year. An unrefunded
   cancellation fee goes into costs.
4. Purchased points are counted once — in the costs of the year of purchase. Their cash is never
   subtracted from a redemption's value, otherwise it is counted twice.
5. Unredeemed points are not part of the year's result. They may be shown in a separate
   «unrealized position» block at an average of published valuations, with a caveat.

## Worked cases (tests in `tests/test_core.py`)

| Case | What happens | How it counts |
|---|---|---|
| Refund | A redemption for 60,000 points and $50 in fees is cancelled; points and fees returned | Removed from the year; nothing added |
| Refund with a fee | The same, but a $75 cancellation fee is not refunded | +$75 to costs |
| Transfer | 90,000 bank points → 90,000 airline miles, a 30% bonus adds 27,000 | No income, no cost; only the later redemption counts |
| Reversed credit | A $200 airline-fee credit posted in March and reversed in April | Used $0; the credits report shows «reversed» |
| Points from last year | In January points earned the year before are redeemed | Counts in January's year; the foregone cash back on the spend that earned them was counted the year before |
| Purchased points | In April points are bought for $1,500 and a ticket is redeemed (normalized $3,600, fees $40) | Costs +$1,500; value redeemed +$3,560; cash avoided +(fallback − $40) |
