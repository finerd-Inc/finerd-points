# How finerd points writes (all skills)

1. **Only on request.** Reading never needs permission; writing always does.
2. **One writer.** At the start of a conversation pick a session id (e.g. `chat-` + 8 random
   letters) and run `ledger.py lease acquire`. If another conversation holds the lease, read only
   and ask the person whether to hand write access over here (`--transfer`). `apply` and `op` renew
   the lease (30 minutes) on every write. Copies of a ledger file attached to different
   conversations cannot see each other's lease: always continue from the newest file (its version
   number is printed when it loads) and hand the new file back after every change.
3. **One preview for the whole batch.** Put every change (ledger records, calendar events, finance
   app records) into one batch file, run `ledger.py preview`, show the person the text exactly —
   it lists the real values that will be written — and apply only after they agree:
   `ledger.py apply --confirm <hash>`. `apply` refuses a batch whose preview did not run in the
   last hour; the hash proves the preview was made for exactly this batch, and showing it to the
   person is your job.
4. **Other apps, step by step.** `apply` records external writes as `planned`. For each one:
   - search the destination first (calendar: the event id from the ledger, or the text
     `[finerd points op-…]` that every event description carries; finance app: the op id in the
     note/tag, or the transaction id); if it already exists, do not write again;
   - perform it through the person's connector; run `ledger.py op --state sent`;
   - read it back from the destination and run `ledger.py op --state confirmed
     --destination-id <id> --read-back '<values you read back>'`, using the destination's real
     values mapped to the plan's keys, never the plan itself. A calendar read-back of a new event must
     contain `title`, `date`, `reminder_minutes` (null when the event has no reminder override),
     `visibility`, `attendees` and `description` (with its marker); an update needs the keys it
     changed; a
     finance-app read-back must contain every value the plan wrote. An incomplete or different
     read-back is refused: then mark `unknown`, look again, and resolve it;
   - if the connector errored or timed out, mark `unknown`, then check the destination and mark
     `confirmed` or `failed` before any retry.
5. **Never delete, archive or share** in any app. A changed deadline updates the existing event;
   a used credit gets «✓» in its event title and its reminder removed. The one deletion is a
   household member's privacy withdrawal from the ledger (see the `points` skill).
6. **Where duplicates cannot be checked,** do not write: give the person an import file instead.
7. **Before the first write to a finance app,** tell the person how to block delete, bulk-edit,
   archive and share tools for that connector in their AI app's connector settings.
8. **Scheduled runs only read and report.** Their report lists proposed changes; the next
   conversation recomputes them and asks for confirmation.
9. **Hand back after release.** At the end of a conversation that changed the ledger, run
   `ledger.py lease release`, then hand the person the file and its version number.
10. **Report honestly:** «event created» and «reminder set» are separate facts; say which reminder
   the event really has, as read back. Partial success is partial: list what failed and why.
