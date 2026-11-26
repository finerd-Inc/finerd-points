# Directory listings (English base listing)

Limits checked by `tools/check_listing.py`. The Claude directory gets the `claude-directory` build
(the same skills, browser reading included — option A, Rad 16 November 2026; app skills limited to
finerd, the publisher's own connector; no short paths). The ChatGPT build and its scope are decided
when that submission is prepared.

## Fields

- **Package name:** finerd-points
- **Display name:** finerd points
- **Subtitle:** Card credits, points and miles
- **Developer:** finerd
- **Category:** Finance (Claude: productivity if Finance is not offered)
- **Support:** github.com/finerd-Inc/finerd-points/issues · support address [finerd team to confirm]
- **Security contact:** https://github.com/finerd-Inc/finerd-points/security/advisories/new (security@finerd.ai once the finerd team confirms it)
- **Privacy policy URL:** https://github.com/finerd-Inc/finerd-points/blob/<release tag>/PRIVACY.md
- **Terms URL:** https://github.com/finerd-Inc/finerd-points/blob/<release tag>/TERMS.md
- **Icon:** plugins/finerd-points/assets/icon.png (1024 × 1024). The Claude portal keeps the icon
  from the first save; replace it before then if finerd's designer makes a final one.

## Description

Collect all your points, miles and card credits in your AI assistant and see where you stand. Open any
bank, card or loyalty program site — in any country — or AwardWallet or your own spreadsheet, sign in
yourself, and finerd points reads what matters: balances with their dates, activity, card credits and
how much of each you have used, certificates and deadlines. It keeps everything in a ledger on your own
computer and shows you a report: every balance with its date and source, the credits still open and
their deadlines, what expires soon, and a Year in Review of your points game by a published accounting
method.

It is a set of skills, not a service. There is no server and no sign-up: your ledger stays in a folder
you own, and nothing is sent to us. Your AI only reads: it never pays, redeems, transfers, enrolls or
changes anything on a site, and it never handles passwords or codes. Every value keeps the on-page text
it came from; a history counts as complete only when the site showed its end; nothing is counted twice
when you refresh. It writes into your ledger, calendar or finance app only after you see the whole list
of changes, and never deletes anything in your apps. Card terms come from an open catalog with the
issuer's own page and a check date behind every fact. A finance app is optional.

## Capabilities (each ≤ 120 characters)

1. Reads balances, activity, credits and deadlines from any site you open and sign in to yourself.
2. Keeps every value with the on-page text it came from, and says plainly what it could not read.
3. Shows which card credits you used, which are open this period, how much is left and the deadline.
4. Lists credits, points, certificates and sign-up deadlines that expire soon, with the source of each date.
5. Puts deadlines into your calendar as private events and marks them done when a credit is used.
6. Builds a Year in Review of your points game and compares it line by line with your own spreadsheet.
7. Keeps a ledger you own in a folder on your computer; no server, nothing sent anywhere.
8. Writes only after one preview of the whole batch, never deletes, never duplicates.

## Three working examples (synthetic data in tests/fixtures and docs/examples)

1. «Collect my points» with a loyalty program site open → the rows found, one preview, the first report.
2. «Which card credits haven't I used this year?» with the issuer's benefits page open → per-card table
   with what is used, left and by when.
3. «What expires in the next 60 days? Put it in my calendar.» → dated list, one private event per date
   after a preview.

## Reviewer access (Claude directory)

A finerd-owned Google test account with a sample ledger file and calendar [finerd team to create
before submission]. ChatGPT needs no reviewer account for a skills-only plugin.
