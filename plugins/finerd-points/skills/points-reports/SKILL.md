---
name: points-reports
description: Builds the person's yearly points and miles report by the finerd points-accounting method — the Points & Miles Year in Review (cash avoided at fallback prices and value redeemed at normalized prices, minus purchased points, tools, annual fees and foregone cash back), with card credits as a separate line, a comparison with a spreadsheet the person already keeps, and an HTML page on request. Use when someone asks «did my points game pay off», «year in review», «points report for 2025», or wants their yearly result compared with their own sheet.
---

# Points reports

Method: framework «Accounting for Loyalty Currencies in Personal Finances» v1.2, §5.1; formula and
rules in `references/year-in-review-formula.md`. Scripts: this skill's `scripts/`.
The ledger is `<folder>/ledger.json` (default folder `~/finerd points`); every change goes through
`ledger.py preview --folder <folder>` and `ledger.py apply --folder <folder> --confirm <hash>`.

## The report (shown after every collection and refresh)
`python3 scripts/report.py --ledger <folder>/ledger.json --html <folder>/reports/report-<YYYY-MM-DD>.html`
(add `--transactions *.txns.json` when the person has a finance app; it is optional). Show the markdown it
prints, in its order: balances with date, source and link; credits with allowance, used, left and
deadline; deadlines in the coming weeks and those whose date is unknown; Year in Review with its
completeness; what could not be read and why; the 60-day refresh note. Where the host can show a page,
show the HTML; otherwise tell the person where the file is. An aggregator's value (AwardWallet) is shown
only with its own age and is never counted. Totals marked preliminary wait for the person's decision on
rows that may be the same; ask them.

## Contract
- **Triggers:** yearly result, Year in Review, «did it pay off», comparison with their sheet.
- **Inputs:** the ledger (redemptions with fallback and normalized prices, costs, settings);
  card spend for the year; the `card-credits` JSON for the same year.
- **Outputs:** the report in chat; an HTML file on request; a line-by-line comparison when a sheet
  is given, each difference explained.
- **Side effects:** none, unless the person asks to record missing redemptions or costs (shapes in
  `references/record-shapes.md`, one previewed batch).
- **Stops when:** no ledger. When the script says the report is **incomplete** (missing prices,
  amounts without a currency rate, no cash-back rate or spend), show that warning first, ask for the
  missing data, and never present the numbers as final; never invent a price or a rate.

Not in this version: «keep or cancel this card» and status forecasts — say so plainly.

## Steps
1. Check inputs: redemptions booked in the year (points, fees, fallback, normalized), costs, the
   cash-back rate and exclusions in settings (ask if unset).
2. Card spend needs every transaction of the year per card, not the credits search: a CSV export, or
   all of the card's finerd transactions for the year (`search_transactions` with the card's
   account_ids and the year's dates, page_size 100, every page) normalized with
   `normalize.py finerd … --all-transactions > card.all.json`. Then
   `python3 scripts/spend.py --ledger <folder>/ledger.json --transactions *.all.json --year <YYYY> > spend.json`.
   spend.py refuses to count filtered files and notes cards without data; for those, ask the person
   for totals and put them into spend.json by hand (personal/business `spend` and `excluded`),
   removing the matching note.
3. Credits line
   (the scripts and facts are in this folder): issuer-reported usage read by `collect` is already in the
   ledger; for each card with a `finance_link`, fetch its
   statement credits, annual fees and oldest transaction date per `references/apps/<app>/APP.md` (a CSV: `references/connectors/csv.md`);
   `python3 scripts/normalize.py finerd --account-name "<finance_link.account_name>" --account-id <id>
   --from <YYYY-01-01> --to <today> --covered-from <oldest date> raw*.json > card.txns.json` (or
   `normalize.py csv …`, `references/connectors/csv.md`); then
   `python3 scripts/credits.py --ledger <folder>/ledger.json --transactions *.txns.json --year <YYYY> --format json > credits.json`.
   Apply the annual fees it proposes (`credits.py … --proposals fees.json`, preview, apply) before
   the report: the report counts only fees recorded in the ledger and says which cards have none.
4. `python3 scripts/yir.py --ledger <folder>/ledger.json --year <YYYY> --spend spend.json --credits credits.json
   --format md`. With the person's sheet, write its lines to `sheet.json`
   (`{"cash_avoided":…,"value_redeemed":…,"points_purchased":…,"tools":…,"annual_fees":…,
   "foregone_cashback":…,"net_fallback":…,"net_value":…}`) and add `--compare sheet.json`;
   differences only the person can explain go into `--explain explain.json` ({line: text}).
5. HTML page: run yir.py again with `--format json > yir.json`, then
   `python3 scripts/render_report.py --ledger <folder>/ledger.json --yir yir.json [--credits credits.json]
   [--expirations expirations.json] --out report.html --title "Points & Miles — <name>, <year>"`.
6. Present: net result at fallback and at value; the lines; credits as a separate line (each valued
   at what the person says it is worth, setting `credit_values`); the rules that matter here (a
   cancelled redemption removed, purchased points counted once, unredeemed points excluded).
