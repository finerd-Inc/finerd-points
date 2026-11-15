# Directory listings (English base listing)

Limits checked by `tools/check_listing.py`. Both directories get the same plugin folder; the
Claude directory gets the `claude-directory` build (connector guides limited to Google, finerd and
CSV, rule 3.F), ChatGPT gets the `chatgpt` build.

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

Keep your credit-card credits, points and miles under control inside your AI assistant. finerd
points finds which card credits you have used and which are still open this month, lists what
expires soon and can put those deadlines into your calendar, shows every balance with its date
and source, and builds a Year in Review of your points game by a published accounting method:
cash avoided at the price you would really have paid, minus purchased points, annual fees, tools
and the cash back you gave up.

It is a set of skills, not a service. There is no server: your ledger stays in a file or a folder you
own. It reads only what you connect or paste — transactions from your
finance app (finerd or a CSV export), balances, program emails — and never takes card numbers,
passwords or codes. It changes something in your apps or calendar only when you ask, after you see
the whole list of changes, and it never deletes anything in your apps. Card terms come from an open catalog
with the issuer's page and independent reviews behind every fact.

## Capabilities (each ≤ 120 characters)

1. Shows which card credits you used, which are open this period, how much is left and the deadline.
2. Lists credits, points, certificates and sign-up deadlines that expire soon, with the source of each date.
3. Puts deadlines into your calendar as private events and marks them done when a credit is used.
4. Shows points and miles balances with the date and source of every number and flags stale ones.
5. Builds a Year in Review of your points game and compares it line by line with your own spreadsheet.
6. Keeps a ledger you own in a file or folder; no server, nothing sent anywhere.
7. Writes to your apps only after one preview of the whole batch, never deletes, never duplicates.

## Three working examples (synthetic data in tests/fixtures and docs/examples)

1. «Which card credits haven't I used this year?» with a ledger and a CSV export → per-card table,
   questions for credits the bank never shows.
2. «What expires in the next 60 days? Put it in my calendar.» → dated list, one private event per
   date after a preview.
3. «Did my points game pay off in 2025? Compare with my sheet.» → net result at fallback and at
   value, each difference explained.

## Reviewer access (Claude directory)

A finerd-owned Google test account with a sample ledger file and calendar [finerd team to create
before submission]. ChatGPT needs no reviewer account for a skills-only plugin.
