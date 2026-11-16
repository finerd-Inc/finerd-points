# How finerd points writes (all skills)

1. **Only on request.** Reading never needs permission; writing always does.
2. **One ledger, one folder.** The ledger is `ledger.json` in the person's ledger folder (default
   `~/finerd points`). Nothing replaces it except `bin/commit` in that folder. Never write
   `ledger.json` any other way — not with a file tool, not with a connector's overwrite, never with
   `force`.
3. **Open first.** At the start of every conversation run `ledger.py open --folder <folder>`
   (Claude Code and Cowork add `--cleanup`). It finishes or abandons any write a crashed
   conversation left half done and checks the journal. Tell the person the version and date it
   prints. If it reports a problem with the journal, show it as it is and write nothing until the
   person has seen it.
4. **One preview for the whole batch.** Put every change (ledger records, calendar events, finance
   app records) into one batch file, run `ledger.py preview --folder <folder> --batch <file>`, show
   the person the text exactly — it lists the real values that will be written — and apply only
   after they agree: `ledger.py apply --folder <folder> --batch <file> --confirm <hash>`. `apply`
   refuses a batch whose preview was not made in the last hour.
5. **If another conversation wrote first,** `apply` reloads the ledger and publishes your batch
   only if it still reads exactly as the person saw it. Otherwise it returns `needs_preview` with
   the new text: show it and ask again. Nothing you prepared is lost.
6. **In a chat with the person's computer connected,** the folder is on their computer:
   - ask for access to the ledger folder only, never a wider one;
   - check `bin/commit` on the computer: `shasum -a 256 "<folder>/bin/commit"` must equal
     `ledger.py script-hash`; if it does not, deliver `scripts/fp_commit.sh` as `bin/commit` again;
   - bring `ledger.json` into the conversation and note its hash as the computer reports it
     (`shasum -a 256 "<folder>/ledger.json"`);
   - `ledger.py preview --ledger ledger.json --batch <file> --save seen.json`, show the text, and
     after the person's yes `ledger.py chat-prepare --ledger ledger.json --base-hash <hash>
     --batch <file> --confirm <batch hash> --seen seen.json --out outbox`;
   - deliver the three outbox files into `<folder>/work/` under their own names (never overwrite a
     file), then run on the computer the command `chat-prepare` printed and read its `RESULT` line;
   - `RESULT=refused CODE=10` means another conversation wrote first: bring `ledger.json` in again
     and repeat `chat-prepare` with the same batch; if it answers `needs_preview`, show the new text.
   A chat cannot delete files; old work files are cleaned up next time Claude Code or Cowork opens
   the ledger.
7. **Other apps, step by step.** `apply` records external writes as `planned`. For each one:
   - search the destination first (calendar: the event id from the ledger, or the text
     `[finerd points op-…]` that every event description carries; finance app: the op id in the
     note or tag, or the transaction id); if it already exists, do not write again;
   - perform it through the person's connector; run `ledger.py op --folder <folder> --op-id … --state sent`;
   - read it back from the destination and run `ledger.py op … --state confirmed --destination-id <id>
     --read-back '<values you read back>'`, using the destination's real values mapped to the plan's
     keys, never the plan itself. An incomplete or different read-back is refused: mark `unknown`,
     look again, and resolve it;
   - if the connector errored or timed out, mark `unknown`, then check the destination and mark
     `confirmed` or `failed` before any retry.
8. **Never delete, archive, hide or share** in any app. A changed deadline updates the existing
   event; a used credit gets «✓» in its event title and its reminder removed. The one deletion is a
   household member's privacy withdrawal from the ledger (see the `points` skill).
9. **Where duplicates cannot be checked,** do not write: give the person an import file instead.
10. **Before the first write to a finance app,** tell the person how to switch off delete,
   bulk-edit, archive, hide and share tools for that connector in their AI app's connector settings.
11. **Limited mode writes nothing.** When the folder cannot be reached (computer asleep, desktop app
   closed, phone only), say so first; you may show the last report or read a ledger the person
   attaches, marked with its version and date. Never start a collection you cannot save, and never
   keep a second copy anywhere else.
12. **Report honestly:** «event created» and «reminder set» are separate facts; say which reminder
   the event really has, as read back. Partial success is partial: list what failed and why.
