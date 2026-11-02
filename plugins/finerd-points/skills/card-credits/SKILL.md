---
name: card-credits
description: Finds which credit-card credits and benefits the person has used, which are still open this period, how much is left and the deadline — Amex, Chase, Bank of America, Bilt, Hilton and other cards in the finerd points catalog — from their finance app transactions (finerd, any other connected finance app, or a CSV) and what they tell you. Use when someone asks «which credits haven't I used», «did my Resy/Uber/airline/dining credit post», «how much of my card benefits did I use this year», or wants credits recorded in their ledger.
---

# Card credits

Scripts: this skill's `scripts/` (`${CLAUDE_SKILL_DIR}/scripts` in Claude Code/Cowork). Card terms:
this skill's `facts/` — never your memory. Read `references/writes.md` before writing.

## Contract
- **Triggers:** unused/used credits, «did it post», year-to-date benefit use, recording credits.
- **Inputs:** the ledger (cards with `catalog_ref` and `finance_link`); transactions from the
  person's finance connector or a CSV; the person's answers for credits banks never show.
- **Outputs:** a table per card: credit, this period, used, left, deadline, status; questions for
  what cannot be seen; a proposed ledger batch recording posted credits and annual fees.
- **Side effects:** only the ledger batch, after one preview and the person's yes.
- **Stops when:** no ledger (send to `points` setup); a card is not in the catalog (say so); a script
  refuses (show its message); amounts are in another currency without a rate (say they are left out);
  a card's terms are in another currency than the report (credits for it are not supported yet).

## Steps
1. Load the ledger (`scripts/ledger.py show`). For each card with a `finance_link`, fetch from the
   connector per `references/connectors/<app>.md`: the year's statement credits, annual fees, and
   the oldest transaction date (coverage). Save every tool result to a file exactly as returned.
2. Normalize: `python3 scripts/normalize.py finerd --account-name "<name>" --account-id <id>
   --from <YYYY-01-01> --to <today> --covered-from <oldest date> raw1.json raw2.json > card.txns.json`,
   or `normalize.py csv --account-name <the card's finance_link.account_id> --from … --to … …` for a
   CSV export (`references/connectors/csv.md`; without --from/--to every period reads «unknown»).
3. Compute: `python3 scripts/credits.py --ledger <file> --transactions *.txns.json --format md
   --proposals credits-batch.json` (add `--year` for a past year), and keep the JSON output
   (`--format json > credits.json`) for `expirations` and `points-reports`.
4. Show the table as it is. Explain statuses in plain words:
   - **used / partly used** — a posted matching credit (pending ones are listed, not counted);
   - **not used yet** — this period is open, the app's data reaches today, and nothing posted;
   - **no credit posted** — the period ended, the app covered it, no credit appeared (likely unused;
     when the bank's description for that credit is not verified yet, say it may have posted under
     other words);
   - **unknown** — the app does not cover that period; never treat it as zero;
   - **ask** — the credit never shows at the bank (app wallets like Uber Cash, hotel folio credits,
     prepaid-booking discounts) or opens only after a condition: ask the person;
   - **enrollment not confirmed** — the issuer requires enrollment; ask, and record the answer.
   Show «credits I could not match» and ask what they are. Facts older than 90 days are unverified.
5. Record answers: the person's word on a credit → `{"op":"observe","subject":"benefit:<card>/<benefit>/<period key>",
   "field":"used_amount","value":10,"source":{"kind":"person"},"as_of":"<today>","confidence":"confirmed"}`;
   enrollment → `{"op":"observe","subject":"benefit:<card>/<benefit>","field":"enrolled","value":true,
   "source":{"kind":"person"},…}`. Add these to the same batch file as `credits-batch.json`, preview it
   once, and apply on yes.

Each bank transaction counts for one benefit only, a reversal comes off the credit it reverses,
and nothing counts above the allowance. Percentage-back offers and one-time credits count when
they post but are not «money waiting to be used». A shared allowance (one per person across several
cards) is pooled and counted once.
