---
name: expirations
description: Lists the person's upcoming deadlines — open card credits by their period end, points and miles expiry dates, free-night certificates, companion vouchers and sign-up bonus spend deadlines — with the source of each date, and on request puts them into their calendar as private events with a reminder, updating them when dates change and marking them done when used. Use when someone asks «what expires soon», «what deadlines do I have», «remind me before my credits reset», or wants these dates in Google Calendar.
---

# Expirations and reminders

Scripts: this skill's `scripts/`. Read `references/writes.md` and
`references/connectors/google-calendar.md` before creating any event.
The ledger is `<folder>/ledger.json` (default folder `~/finerd points`); scripts read it with
`--ledger <folder>/ledger.json`, and every change goes through `ledger.py preview --folder <folder> --batch <file>` and
`ledger.py apply --folder <folder> --batch <file> --confirm <hash>` (`references/writes.md`).

## Contract
- **Triggers:** upcoming deadlines; reminders; calendar entries for them.
- **Inputs:** the ledger; the `card-credits` JSON for the same day (credit deadlines); expiry
  dates the person or their program accounts/emails supplied.
- **Outputs:** a dated list with the source of each date; on request a calendar batch.
- **Side effects:** calendar events only after one preview: private, no guests, no balances or
  account numbers in titles; update instead of duplicate; never delete.
- **Stops when:** no ledger; no calendar connector (give the list only); a script refuses.

Every date comes from a source: a program account, an email, a statement, the bank's page, the
card's terms in the catalog (credit periods) or the person. Never derive a points expiry date from
a rule you remember; ask for it instead.

## Steps
1. Credit deadlines need today's credits result
   (the scripts and facts are in this folder): for each card with a `finance_link`, fetch its
   statement credits, annual fees and oldest transaction date per `references/apps/<app>/APP.md` (a CSV: `references/connectors/csv.md`);
   `python3 scripts/normalize.py finerd --account-name "<finance_link.account_name>" --account-id <id>
   --from <YYYY-01-01> --to <today> --covered-from <oldest date> raw*.json > card.txns.json` (or
   `normalize.py csv …`, `references/connectors/csv.md`); then
   `python3 scripts/credits.py --ledger <folder>/ledger.json --transactions *.txns.json --format json > credits.json`
   (without a finance app: `--transactions` may be left out; issuer-reported usage from the ledger is used).
   expirations.py refuses a credits result from another day.
2. `python3 scripts/expirations.py --ledger <folder>/ledger.json --credits credits.json --days 45 --format md`.
   Say plainly that a deadline not in the ledger is unknown, not safe.
3. For reminders, first ask which calendar, look up its real id with the calendar connector (list
   calendars; for the main calendar this is usually the account's email address, not «primary») and
   record it: `{"op":"set_setup","key":"calendar_id","value":"<calendar id>"}` (apply it), then
   `expirations.py … --calendar-plan cal-batch.json` and `ledger.py preview --folder <folder> --batch cal-batch.json`.
   Credit deadlines are grouped into one event per date when the date's open credits add up to at
   least `calendar_min_value` (default 25); credits with no evidence (card not connected) and credits
   never used this year get no event; credits the bank cannot show do get one. Points, certificates
   and sign-up deadlines always get their own event. If the plan is empty, there is nothing to add.
4. On yes: `ledger.py apply --folder <folder> --batch cal-batch.json --confirm <hash>`. For each planned event: check whether
   it exists (the event id from the ledger, or list the events of the deadline date itself with an
   explicit day range and look for its `[finerd points op-…]` marker); create or update it through
   the connector; run `ledger.py op --folder <folder> --op-id <op> --state sent`; read the event back and run `ledger.py op --folder <folder> --op-id <op> --state
   confirmed --destination-id <event id> --read-back '{"event_id":…,"title":…,"date":…,
   "reminder_minutes":…,"visibility":"private","attendees":[],"description":…,"calendar_id":…}'` with the values the
   calendar returned (see `references/connectors/google-calendar.md`). Tell the
   person separately: event created, and which reminder the event actually has. If the reminder
   could not be set or removed, say so.
5. When credits are used, the next run proposes «✓» in the title and turning the reminder off.
6. To record an expiry date, a certificate or a sign-up offer the person gives you, use the shapes
   in `references/record-shapes.md` and one previewed batch.
