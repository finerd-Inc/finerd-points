---
name: points
description: Sets up finerd points and maintains the person's ledger — first-time setup with the ledger folder and the list of their programs and cards (optionally found in their connected email), adding or correcting cards, programs, redemptions, costs and household members, importing a points spreadsheet, exporting, or removing a household member's data. Use when someone says «set up finerd points», «start tracking my points/cards», «add my new card», «correct my ledger», «import my points spreadsheet», «export my ledger», right after installing the plugin, or when a partner asks to be removed.
---

# finerd points — setup and ledger

finerd points is a set of skills, not a service: no server, no sign-up. Everything lives in the
person's **ledger**, one file in a folder on their computer (default `~/finerd points`), written only
through `bin/commit` in that folder. Scripts are in this skill's `scripts/` folder
(`${CLAUDE_SKILL_DIR}/scripts` in Claude Code and Cowork); they need only Python 3.9+.

Read `references/writes.md` before any change and `references/ledger-format.md` for the format.

## Contract
- **Triggers:** setup; add or correct a card, program, redemption or cost; import a spreadsheet;
  export; a household member's removal request.
- **Inputs:** what the person says or pastes; their ledger; read-only connectors they connected
  (mail for program discovery, a finance app, Sheets).
- **Outputs:** the ledger folder and ledger; the inventory; plain-language answers.
- **Side effects:** creating the ledger folder the person chose; ledger writes they approved in one
  preview.
- **Stops when:** the person declines; the ledger folder cannot be reached (limited mode); input holds
  card numbers, passwords, codes, keys, member or ID numbers (ask the person to remove them); a script
  refuses (show its message as it is).

| Question | Skill |
|---|---|
| Collect or refresh my points, miles and credits; read this page | `collect` |
| Which credits haven't I used? | `card-credits` |
| What expires soon? Put deadlines in my calendar | `expirations` |
| How many points do I have? | `balances` |
| The report; Year in Review | `points-reports` |

Not in this version: status forecasts, «keep or cancel this card», unattended scheduled refreshes.

## Starting a conversation
- Claude Code or Cowork: `ledger.py open --folder <folder> --cleanup`.
- Claude chat: check that the person's computer is connected and ask for access to the ledger folder
  only; then follow `writes.md` step 6. No computer connected → **limited mode**: say so first; show
  the last report or read a ledger file the person attaches (`--ledger`, read-only), marked with its
  version and date; write nothing and keep no copy anywhere else.

## Setup (the first thing after installing)
1. Check where you run and whether you can reach a folder on the person's computer. In a few
   sentences give the first-run notice (`references/first-run.md`).
2. Ask for one dedicated folder (default `~/finerd points`, outside iCloud, Google Drive, Dropbox or
   OneDrive) and never a wider one. Choosing it approves creating it and an empty ledger there:
   `ledger.py setup --folder <folder> --name <first name> --timezone <tz> --currency <cur>`.
   In a chat: ask for access to that folder, deliver `scripts/fp_commit.sh` as `bin/commit`, check its
   hash, and publish the first ledger with `chat-prepare` (base hash `none`).
3. **Inventory first.** Ask whose accounts belong in this ledger (a partner's only with their consent,
   recorded with `add_person`) and how far back to collect history (default 1 January of last year;
   record it with `{"op":"set_setup","key":"history_from","value":"YYYY-MM-DD"}`).
4. **Programs from email (optional).** If the person's mail is connected to their AI and they confirm
   the mailbox is their own and not shared with anyone outside this ledger, offer to look for which
   programs they have, by the rules in `references/email-senders.md`: search by those sender domains
   and a date range only, never open a message, and show what you found as «possible programs». If
   the connector returns subjects or snippets for such a search, do not run it; ask the person to list
   their programs instead. Record a program only when the person confirms it and that it is theirs
   (`add_inventory` with `found_by: "email"`).
5. Ask what else they have: programs, cards, apps (AwardWallet, a finance app), spreadsheets. Each
   becomes an `add_inventory` item with its owner; cards also get `add_card` (match the catalog,
   `facts/cards/*.json`; a card outside the catalog is still added; for anniversary-based credits ask
   the open date or the anniversary MM-DD; never card numbers, last four digits optional).
6. One batch, `ledger.py preview --folder …`, show it, `ledger.py apply --folder … --confirm <hash>`.
7. Hand over to `collect`: «Open your first site and sign in; tell me when you are in.»

### Record shapes
All shapes are in `references/record-shapes.md` (unknown fields are refused).

## Corrections and export
- A wrong observation → `{"op":"void","target":"obs-…","reason":"…"}` plus the right one.
- A record field → `{"op":"amend","target":"cards|accounts|redemptions|costs|certificates|signup_offers",
  "id":"…","field":"…","value":…,"reason":"…"}`; the old value stays in the record's history.
- Two rows the report shows as «possibly the same»: ask the person, then
  `{"op":"resolve_link","link":"lnk-…","decision":"same|different"}`; a row «no longer shown»:
  `{"op":"resolve_not_shown","record":"rec-…","decision":"gone|keep"}`.
- Export: `ledger.py export --folder <folder> --archive <folder>/reports/ledger-<date>.zip` writes one
  portable archive (the ledger, its backups list and journal); `--out <path>` instead writes one CSV per
  collection (formula-safe) for a spreadsheet.
- A ledger file from finerd points 0.1: `ledger.py setup --folder <folder> --import-file <file>` moves it
  into the folder (schema 2; the old file is left as it was).

## Importing a spreadsheet the person already keeps
Read their copy (pasted, uploaded or through their Sheets connector), map cards, programs, balances,
redemptions and costs to the shapes, preview, apply. Template content is never copied into finerd
points; only the person's own data goes into their ledger.

## A household member asks to be removed
`ledger.py redact --folder <folder> --person <id>` prints what goes; show it, and after the person
agrees run it again with `--confirm <hash>`. Their calendar events are cleared through a previewed
batch (details and reminders removed), not deleted. The older copies in the ledger folder (backups,
saved batches, working files) are cleaned the next time Claude Code or Cowork opens the folder
(`open --cleanup`); until then say so. Tell them plainly what stays: old conversations, exports the
person made, and anything in finance apps.
