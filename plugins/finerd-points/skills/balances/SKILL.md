---
name: balances
description: Shows the person's points and miles balances per loyalty program with the date and source next to every number, flags stale or conflicting numbers, and records new balances in their finerd points ledger. Use when someone asks «how many points do I have», «what are my balances», «update my Hyatt/Amex/United balance», pastes a program statement or balance email, or has balances in finerd to bring in.
---

# Balances

Scripts: this skill's `scripts/`. Read `references/writes.md` before recording anything.
The ledger is `<folder>/ledger.json` (default folder `~/finerd points`); scripts read it with
`--ledger <folder>/ledger.json`, and every change goes through `ledger.py preview --folder <folder> --batch <file>` and
`ledger.py apply --folder <folder> --batch <file> --confirm <hash>` (`references/writes.md`).

## Contract
- **Triggers:** balances, a balance update, a pasted statement or program email.
- **Inputs:** the ledger (balances the `collect` skill read from program pages are already there);
  balances from a connected finance app (finerd verified balances), a program page the person opened, a program email from a sender in
  `references/email-senders.md`, a statement, or the person's words.
- **Outputs:** a table: program, balance, as of, source, notes (stale, sources disagree, expiry).
- **Side effects:** new balance observations, after one preview.
- **Stops when:** no ledger; input carries member numbers, passwords or codes (ask to remove).

## Steps
1. Show what the ledger knows: `python3 scripts/balances.py --ledger <folder>/ledger.json --format md`.
   To read a program's site now, hand over to `collect`.
2. To refresh from finerd: per `references/apps/finerd/APP.md`, read each REWARD account's
   latest verified balance (and the computed balance), write a `finerd-points/balances@1` file:
   `{"contract":"finerd-points/balances@1","source":{"app":"finerd"},"balances":[{"account_id":"…",
   "program":"World of Hyatt","amount":52310,"unit":"points","as_of":"2026-11-16","kind":"verified"}]}`, then
   `balances.py --ledger <folder>/ledger.json --input bal.json --proposals bal-batch.json`. For other sources
   write the same file with `kind` = program_page, statement, email or person.
3. Balances are matched to ledger programs by the finance-app account id (set `finance_link` on the
   program with `amend` if it is missing), else by program or nickname. Show anything `unmatched`
   and ask which program it is. If nothing is proposed, there is nothing new to record.
4. Preview `bal-batch.json` with `ledger.py preview --folder <folder> --batch bal-batch.json`, apply on yes, show the table again.

The latest date wins; on the same date the stronger source wins and the other value is shown as a
disagreement. A value from an aggregator (AwardWallet) is shown only with its own age and never
mixed into current totals. Unknown is never zero. Balances of different programs are never added up, and points
are not money: they never enter net worth.
