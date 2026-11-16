# finerd points

Skills for AI assistants (Claude, ChatGPT and any client that reads Agent Skills) that collect all your
points, miles, card credits, certificates and deadlines from whatever you open — a bank or loyalty
program site in any country, AwardWallet, a spreadsheet, a statement — keep them in a ledger on your
own computer, and show you a report. Built on the finerd points-accounting method («Points Are Not
Just Points», paper in preparation).

Install in Claude Code:

```
/plugin marketplace add finerd-Inc/finerd-points
/plugin install finerd-points@finerd
```

Start with «Set up finerd points». You need no history and no account anywhere. The skill asks for
one folder for your ledger (default `~/finerd points`), whose accounts belong in it and what programs
and cards you have — and, if your email is connected and you agree, suggests programs from the senders
of program emails. Then you open your first site and sign in yourself; your AI reads it, shows you
what it found, and after your yes keeps it in the ledger. When you are done, you see the first report.
Later, «refresh my points» repeats it for the sites you open again.

Then ask in plain words:
- «Which credits haven't I used this month?»
- «What expires in the next 45 days? Put it in my calendar.»
- «How many points do I have?»
- «Did my points game pay off in 2025?»

A finance app (finerd or another) can be connected but is not needed.

## Skills

| Skill | Does | Reads | Writes (only after you approve one preview) |
|---|---|---|---|
| `points` | Sets up the ledger folder and your list of programs and cards; corrections; export | What you say; your email's program senders, with your consent | Your ledger |
| `collect` | Reads whatever you open and turns it into ledger records with evidence; shows the report | Pages you open and sign in to; statements, CSV, sheets, program emails you give it | Your ledger |
| `card-credits` | Credits used, open, left, by when | Your ledger (the issuer's benefits page as read by `collect`); a finance app or CSV if you have one | Your ledger |
| `expirations` | Deadlines for credits, points, certificates, sign-up bonuses | Your ledger; the credits result | Your calendar (private events) and your ledger |
| `balances` | Balances with date and source | Your ledger; a finance app, statements or program emails | Your ledger |
| `points-reports` | The report; Year in Review; comparison with your own sheet | Your ledger | A report file in the ledger folder |
| `facts-check` | Checks the card and program catalog against current sources (maintainers) | The catalog; pages your AI's web search returns on request | Nothing (a diff for a pull request) |

## What it runs, reads, sends and stores

- **Runs:** small Python scripts in each skill's `scripts/` folder (standard library only, Python
  3.9+), and one POSIX shell script, `bin/commit`, installed in your ledger folder: the only thing
  that replaces your ledger file, under a lock, after checking nothing else changed it meanwhile. The
  scripts read and write only your ledger folder and files you point them to, and **never open network
  connections**. Nothing is downloaded or installed.
- **Reads:** pages you open and sign in to yourself — account summaries, activity, benefits and
  credits, certificates, statements; never profile, payment, security or message pages. Your AI
  necessarily sees the whole page, including numbers the skills do not keep. Files, sheets and program
  emails you give it. With your consent, the sender addresses and dates of program emails (no message
  is opened). A finance app only if you connect one.
- **Never does on a site:** pay, redeem, transfer, book, buy, cancel, enroll, activate an offer, change
  a setting or send a message. It stops at sign-in, codes and CAPTCHAs and lets you act.
- **Never takes:** passwords, one-time codes, API keys, full card numbers, member or account numbers or
  ID numbers. Recognizable ones are removed from page text before anything is stored.
- **Stores:** your ledger folder — `ledger.json` (balances, activity rows, credits, deadlines, each with
  the short on-page text it came from and when it was read), backups of earlier versions, a journal of
  changes, short-lived working files and report pages — and, if you ask, private calendar events
  without guests and without balances in their titles.
- **Sends:** nothing to finerd or anyone else. Your data is seen by your AI provider (it runs the
  conversation and processes the pages it reads), by your browser and the sites you open, and by the
  apps you connected (including the finerd app, if you connected it — its privacy policy applies).
- **Writes:** into your apps only when you ask, after one preview of the whole batch, only where
  duplicates can be checked; never delete, archive, hide or share anything. An external write counts
  as done only after it is read back.
- **Deletes:** nothing — except, when a household member asks, their own data in the shared ledger
  and its older copies in the folder (previewed first).

## Trust in the numbers

Every value keeps the on-page text it came from. A history counts as complete only when the site
showed its end and the rows are continuous; otherwise the report says what is missing and why. Rows
already in the ledger are recognized on a refresh; a row that may be the same as an earlier one is
never counted twice — the earlier one stays counted until you decide. Pending rows are never counted.
An aggregator's balance (AwardWallet) is shown only with its own age and never mixed into current
totals. Card terms come from the open facts catalog, each fact with the issuer's own page, its check
date, and «unverified» after 90 days.

## Limits

- A refresh re-reads the last 60 days of each history; a site's correction to older rows is found only
  by a full re-read.
- Credits that never show anywhere you can open (app wallets such as Uber Cash, hotel folio credits)
  need your answer.
- Some banks restrict AI tools signing in on your behalf (Chase's agreement does). You can always
  download a statement or CSV yourself and give it to your AI instead.
- The ledger folder works on macOS and Linux; Windows is not supported yet.
- The ledger folder is on your computer: in Claude chat your computer must be connected and awake.
  Without it, the skills only show the last report or read a ledger you attach, and save nothing.
- Status forecasts and «keep or cancel this card» come in a later version.
- Pages, emails and files can contain instructions aimed at AI assistants. The skills treat such text
  as data only, but no filter is perfect: check every preview.

## Websites and program terms

Following each site's terms is between you, your AI platform and the site. finerd points keeps no
list of allowed or forbidden sites. See TERMS.md.

## Delete your data

Delete the ledger folder and any calendar events it created. Conversation history is deleted in your
AI app's settings.

## Support and security

Questions and bugs: GitHub issues at github.com/finerd-Inc/finerd-points (public — never post balances
or statements). Vulnerabilities: see SECURITY.md. Terms of use: TERMS.md. Privacy: PRIVACY.md.
