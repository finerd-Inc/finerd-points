# Ledger format (short)

One JSON document, `format: finerd-points-ledger`, `schema_version: 1`, a `version` that only
grows. Collections: people, cards, accounts, observations, corrections, redemptions, costs,
certificates, signup_offers, calendar_events, oplog. `_meta.setup` is the setup record (storage,
location, calendar, timezone, household mode, report currency, finance app); `_meta.settings`
holds the person's choices (cash-back rate and exclusions, calendar minimum value, reminder days,
stale-after days); `_meta.writer` is the writer lease.

**Subjects** used by observations: `card:<id>`, `account:<id>`,
`benefit:<card id>/<benefit id>` (enrollment), `benefit:<card id>/<benefit id>/<period key>`
(credited, used_amount), `certificate:<id>` (state), `signup:<id>` (spend_so_far, received).

**Observation:** subject, field, value, source {kind, name, ref}, as_of (YYYY-MM-DD),
confidence (confirmed | likely | unsure), method, note. Source kinds: program_page, program_api,
issuer_page, finance_app, statement, awardwallet, email, person, calculation, import.

**Record ids** are lowercase (letters, digits, `. _ : / -`) and never reused. A record changes only
through `amend` (the old value stays in its `amendments` history); a measured value changes by a new
observation; a wrong observation is retracted with `void`. Shapes: `record-shapes.md`.

**Storage.** File: the person keeps the file and attaches it next time; you hand back the new
version at the end of every conversation that changed it, and say its version number.
Folder: the same file in a folder on their computer. A Google Sheet is an export of the ledger
(`ledger.py export`), not its storage, until a platform probe verifies it.
A new conversation that cannot find the ledger asks for the file, the folder or the sheet link,
and never creates a second ledger.
