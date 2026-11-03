---
name: points
description: Sets up and maintains the person's finerd points ledger — adding or correcting credit cards, loyalty programs, redemptions, costs and household members, importing a points spreadsheet they already keep (r/churning Churning Tracker, finerd sheets), exporting the ledger, or removing a household member's data. Use when someone says «set up finerd points», «start tracking my points/cards», «add my new card», «correct my ledger», «import my points spreadsheet», «export my ledger», or a partner asks to be removed.
---

# finerd points — ledger and setup

finerd points is a set of skills, not a service: no server, no database of its own. Everything
lives in the person's **ledger**: a JSON file they keep and attach to the next conversation, or
the same file in a folder on their computer. A Google Sheet is only an export until the platform
probe passes. Scripts are in this skill's `scripts/` folder (`${CLAUDE_SKILL_DIR}/scripts` in
Claude Code and Cowork; otherwise the folder this file is in). They need only Python 3.9+.

Read `references/writes.md` before any change and `references/ledger-format.md` for the format.

## Contract
- **Triggers:** setup; add or correct a card, program, redemption or cost; import a spreadsheet;
  export; a household member's removal request. Other questions go to the skill named below.
- **Inputs:** what the person says or pastes; their ledger; read-only connectors they connected.
- **Outputs:** the ledger (new version), a setup record, plain-language answers.
- **Side effects:** only ledger writes the person approved in one preview.
- **Stops when:** the person declines; the ledger is missing (ask for it, never create a second);
  input contains card numbers, passwords, codes, keys, member numbers or ID numbers (ask the person
  to remove them); a script refuses (show its message as it is).

| Question | Skill |
|---|---|
| Which credits haven't I used? | `card-credits` |
| What expires soon? Put deadlines in my calendar | `expirations` |
| How many points do I have? | `balances` |
| Did my game pay off? Year in Review | `points-reports` |

Not in this version: status forecasts and «keep or cancel this card» — say so plainly.

## Starting a conversation
1. Ask for the ledger file (or folder path) if it is not attached. Load it:
   `python3 scripts/ledger.py show --ledger <file>`; tell the person its version and date so an
   older copy is noticed.
2. Make a session id (`chat-` + 8 random letters) and run `ledger.py lease acquire --ledger <file>
   --session <id>` before writing. If another conversation holds it, read only.
3. Resolve pending external writes first (`ledger.py pending`): check each in its app.

## Setup (no history needed)
1. Give the first-run notice (`references/first-run.md`) once. After `init` (step 3), record it in the
   first batch with `{"op":"set_setup","key":"first_run_notice_shown","value":true}`.
2. Ask where to keep the ledger: a file they keep (works everywhere) or a folder (Claude app,
   Cowork, Claude Code). Ask the timezone, report currency, and whether anyone else's cards belong
   in it (household: one shared ledger or separate ledgers; a partner's cards only with that
   partner's consent, recorded with `add_person`).
3. `ledger.py init --ledger <path> --name <first name> --timezone <tz> --currency <cur>
   --storage file|folder --session <id>`.
4. Cards: ask which cards they hold. Match each to the catalog (`facts/cards/*.json`); a card not
   in the catalog is still added (`catalog_ref` omitted) and its credits are not tracked. When a
   benefit resets on the card anniversary, ask for the open date (`opened_on`) or the anniversary
   day and month (`anniversary`, MM-DD); a month alone is not enough. Never ask for card numbers;
   last four digits are optional.
5. Programs: one `add_account` per loyalty program, with `finance_link` when the finance app has a
   points account for it, and today's balance as an observation with its source.
6. Link each card to its finance-app account (`finance_link`: app, account_id, account_name) and set
   `finance_app`. For a CSV export use `{"app": "CSV", "account_id": "<the --account-name you will
   pass to normalize.py>"}`.
7. Build one batch, `ledger.py preview`, show it, `ledger.py apply --confirm <hash> --session <id>`.
   Return the setup record (`ledger.py show --section setup`) and, for file storage, the file.

### Record shapes
All shapes are in `references/record-shapes.md` (unknown fields are refused).

## Corrections and export
- A wrong observation → `{"op":"void","target":"obs-…","reason":"…"}` plus the right one.
- A record field → `{"op":"amend","target":"cards|accounts|redemptions|costs|certificates|signup_offers",
  "id":"…","field":"…","value":…,"reason":"…"}`; the old value stays in the record's history.
  Moving a card to a partner needs that partner in the ledger with consent.
- Export: `ledger.py export --ledger <file> --out <folder>` writes one CSV per collection
  (formula-safe); the person can import those into a spreadsheet.

## Importing a spreadsheet the person already keeps
Read their copy (pasted, uploaded or through their Sheets connector), map cards, programs,
balances, redemptions and costs to the shapes above, preview, apply. Template content is never
copied into finerd points; only the person's own data goes into their ledger.

## A household member asks to be removed
`ledger.py redact --ledger <file> --person <id>` prints what goes; show it, and after the person
agrees run it again with `--confirm <hash> --session <id>`. Their calendar events are cleared
through a previewed batch (details and reminders removed), not deleted. Tell them plainly what
stays: older copies of the file, old conversations, and anything in finance apps.

## Ending a conversation that changed the ledger
`ledger.py lease release --ledger <file> --session <id>`, then hand back the ledger file and say
its new version number.
