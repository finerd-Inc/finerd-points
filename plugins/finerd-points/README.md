# finerd points

Skills for AI assistants (Claude, ChatGPT and any client that reads Agent Skills) that keep track
of your credit-card credits, points and miles balances, expiring benefits and your yearly points
result — in a ledger you own. Built on the finerd points-accounting method
(«Points Are Not Just Points», paper in preparation).

Install in Claude Code:

```
/plugin marketplace add finerd-Inc/finerd-points
/plugin install finerd-points@finerd
```

Start with «Set up finerd points». You need no history and no account anywhere: name your cards
and programs, or hand over a points spreadsheet you already keep, and the skill creates your
ledger. In a chat it gives you the ledger file to download; attach it to your next conversation.
In the Claude app, Cowork or Claude Code it can keep the file in a folder on your computer instead.

Then ask in plain words:
- «Which credits haven't I used this month?»
- «What expires in the next 45 days? Put it in my calendar.»
- «How many points do I have?»
- «Did my points game pay off in 2025?»

## Skills

| Skill | Does | Reads | Writes (only after you approve one preview) |
|---|---|---|---|
| `points` | Sets up and keeps your ledger; routes questions | What you say or paste; your ledger | Your ledger |
| `card-credits` | Credits used, open, left, by when | Your ledger; card transactions from your finance connector or a CSV | Your ledger (posted credits, annual fees) |
| `expirations` | Deadlines for credits, points, certificates, sign-up bonuses | Your ledger; the credits result | Your calendar (private events) and your ledger |
| `balances` | Balances with date and source | Your ledger; balances from your finance app, statements, program emails or your words | Your ledger |
| `points-reports` | Year in Review; comparison with your own sheet | Your ledger; card spend; the credits result | An HTML report file on request; ledger records only if you ask to add missing redemptions or costs |
| `facts-check` | Checks the card facts catalog against current sources (maintainers) | The catalog; pages your AI's web search returns on request | Nothing (a diff for a pull request) |

## What it runs, reads, sends and stores

- **Runs:** small Python scripts in each skill's `scripts/` folder (standard library only, Python
  3.9+): ledger, transaction normalizer, credits, deadlines, balances and report calculators.
  They read and write only local files you point them to and **never open network connections**.
  Nothing is downloaded or installed. Next to the ledger they create short-lived helper files: a
  `.lock` file while writing, temporary files during an atomic save, and a `.preview-<hash>` marker
  between a preview and its approval.
- **Reads:** only what you connect or paste. From your finance app (finerd or any other
  one you connected, or a CSV): date, merchant/description, amount, currency, card nickname or last four
  digits, category. From loyalty programs: balances, expiry dates, certificates, status,
  redemptions — never member numbers. Email only from the loyalty-program senders listed in
  `references/email-senders.md`, and only if you ask. The skills themselves visit no websites.
- **Never takes:** full card numbers, passwords, one-time codes, API keys, member numbers or ID
  numbers. The ledger refuses the recognizable ones (Luhn-checked card numbers, labelled passwords,
  codes, keys, member or account numbers, SSNs and passports); remove anything else before pasting.
- **Stores:** your ledger — a JSON file you keep or the same file in a folder on your computer
  (a Google Sheet works as an export of it until it is verified as storage) — and, if you ask,
  private calendar events without guests and without balances in their titles; their descriptions
  list the credits and amounts left. Every write and every change of write access raises the
  ledger's version number.
- **Sends:** nothing to finerd or anyone else. Your data is seen by your AI provider (it runs the
  conversation), by Google if you use a Sheet or Calendar, and by the apps you connected
  (including the finerd app, if you connected it — its privacy policy applies).
- **Writes:** the skills direct writes into your apps only when you ask, after one preview of the
  whole batch (it shows the real values to be written), and only where duplicates can be checked;
  otherwise they give you the records to add yourself. They never delete, archive or share anything.
  An external write counts as done only after it is read back from the app: for calendar events
  the title, date, reminder, privacy (private, no guests) and the finerd points marker.
  Scheduled runs only read and report.
- **Deletes:** nothing — except, when a household member asks, their own rows in the shared
  ledger and the details of their entries in its write log (previewed first; older copies of the
  file and old conversations are not touched, and you are told so).

## Trust in the numbers

Every number is an observation with its source, date and confidence; new observations never erase
old ones. «Unknown», «stale» and «zero» are different things. Card terms come from the facts
catalog (`facts/`), each with the issuer's page plus independent reviews and a check date; facts
older than 90 days are shown as unverified. A posted credit is proven only by a transaction.

## Limits

- Credits that never show at the bank (app wallets such as Uber Cash, hotel folio credits) need
  your answer.
- Deadlines come from sources (program accounts, emails, statements, bank pages, you); the first
  version does not derive points expiry from rules.
- Status forecasts and «keep or cancel this card» come in a later version.
- Card credits are computed only when the card's terms and your report use the same currency (the
  catalog's cards are in US dollars). Other amounts need a rate you supply (`fx_rate`), or they are
  left out and the report says so.
- Text from emails, statements and web pages can contain instructions aimed at AI assistants. The
  skills treat such text as data only, but no filter is perfect: check every preview.

## Websites and program terms

finerd points does not log in anywhere. If you ask your AI to open a loyalty program's or bank's
site, you, your AI platform and that site's terms govern it; some programs restrict third-party AI
tools. See TERMS.md.

## Delete your data

Delete the ledger file, folder or sheet and any calendar events it created. Conversation history
is deleted in your AI app's settings.

## Support and security

Questions and bugs: GitHub issues at github.com/finerd-Inc/finerd-points (public — never post balances
or statements). Vulnerabilities: see SECURITY.md. Terms of use: TERMS.md. Privacy: PRIVACY.md.
