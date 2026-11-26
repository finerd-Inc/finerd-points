# Ledger format (short)

One JSON document, `format: finerd-points-ledger`, `schema_version: 2`, a `version` that only
grows, in `<folder>/ledger.json`. A schema-1 ledger is migrated in memory when it is opened and
published as schema 2 by the next write (the version it replaces stays in `backups/`).

**Collections.** people, cards, accounts, observations, corrections, redemptions, costs,
certificates, signup_offers, calendar_events, oplog (external writes), and since schema 2:
- `inventory` — what the person has: programs, cards, banks, apps, sheets, with their owner;
- `sources` — each site, app, sheet, file or email a value was read from: kind, name, hosts,
  market, unit, the accounts inside it (each with its owner), and `coverage`, one entry per read:
  requested and covered interval, state (complete, ends_unreconciled, partial, unavailable),
  terminal evidence, continuity, stop reason, the site's own «as of» text, read time;
- `records` — one row as a source showed it: date, signed amount, unit, description, status
  (posted or pending), the site's own id when trustworthy, evidence (on-page text, where, method),
  the reads that showed it, revisions, and its state (active, dropped, no_longer_shown);
- `events` — links between records («possibly the same», «probably the same») and the person's
  decisions on them;
- `commits` — one entry per publication through `bin/commit` (operation id, base version, writer).

`_meta.setup` is the setup record (storage `folder`, location, calendar, timezone, household mode,
report currency, finance app, history_from); `_meta.settings` holds the person's choices.

**Subjects** used by observations: `card:<id>`, `account:<id>`,
`benefit:<card id>/<benefit id>` (enrollment), `benefit:<card id>/<benefit id>/<period key>`
(credited, used_amount), `certificate:<id>` (state), `signup:<id>` (spend_so_far, received).

**Observation:** subject, field, value, source {kind, name, ref}, as_of (YYYY-MM-DD),
confidence (confirmed | likely | unsure), method, note.

**Record ids** are lowercase (letters, digits, `. _ : / -`) and never reused. Cards, accounts,
redemptions and costs change only through `amend` (the old value stays in `amendments`); a measured
value changes by a new observation; a wrong observation is retracted with `void`; a source record
changes only by a revision (pending→posted, or a stable site id). Shapes: `record-shapes.md`.

**The folder.** `ledger.json`, `bin/commit`, `work/` (candidates and working files),
`journal/` (one entry per commit), `backups/` (the last 20 versions and one per month), `locks/`,
`reports/`. Writes: `writes.md`.
