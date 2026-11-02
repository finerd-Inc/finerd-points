---
name: balances
description: Shows the person's points and miles balances per loyalty program with the date and source next to every number, flags stale or conflicting numbers, and records new balances in their finerd points ledger. Use when someone asks «how many points do I have», «what are my balances», «update my Hyatt/Amex/United balance», pastes a program statement or balance email, or has balances in finerd to bring in.
---

# Balances

Scripts: this skill's `scripts/`. Read `references/writes.md` before recording anything.

## Contract
- **Triggers:** balances, a balance update, a pasted statement or program email.
- **Inputs:** the ledger; balances from a connected finance app (finerd verified balances), a
  program page the person's AI read on their command, a program email from a sender in
  `references/email-senders.md`, a statement, or the person's words.
- **Outputs:** a table: program, balance, as of, source, notes (stale, sources disagree, expiry).
- **Side effects:** new balance observations, after one preview.
- **Stops when:** no ledger; input carries member numbers, passwords or codes (ask to remove).

## Steps
1. Show what the ledger knows: `python3 scripts/balances.py --ledger <file> --format md`.
2. To refresh from finerd: per `references/connectors/finerd.md`, read each REWARD account's
   latest verified balance (and the computed balance), write a `finerd-points/balances@1` file
   (one entry per program: `account_id`, `program`, `amount`, `unit`, `as_of`, `kind`), then
   `balances.py --ledger <file> --input bal.json --proposals bal-batch.json`. For other sources
   write the same file with `kind` = program_page, statement, email or person.
3. Balances are matched to ledger programs by the finance-app account id (set `finance_link` on the
   program with `amend` if it is missing), else by program or nickname. Show anything `unmatched`
   and ask which program it is. If nothing is proposed, there is nothing new to record.
4. Preview `bal-batch.json` with `ledger.py preview`, apply on yes, show the table again.

The latest date wins; on the same date the stronger source wins and the other value is shown as a
disagreement. Unknown is never zero. Balances of different programs are never added up, and points
are not money: they never enter net worth.
