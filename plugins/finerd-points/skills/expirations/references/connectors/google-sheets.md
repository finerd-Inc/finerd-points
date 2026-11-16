# Google Sheets (Claude: Google Sheets connector; ChatGPT: Google Drive app)

A Google Sheet is never where the ledger is kept, and finerd points never writes to one.

- **Reading a sheet the person keeps** (their own points tracker): read it through their connector, read
  only, as a source of `kind: sheet` (`collect`). Columns you cannot map are left out and named.
- **Getting the ledger into a sheet:** `ledger.py export --folder <folder> --out <empty folder>` writes one
  CSV per collection (formula-safe); the person imports them into a sheet themselves.
- Sharing a sheet shares every tab in it; say so when the person mentions sharing.
