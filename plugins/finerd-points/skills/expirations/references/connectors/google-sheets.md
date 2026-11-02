# Google Sheets (Claude: Google Sheets connector; ChatGPT: Google Drive app)

Use a Sheet as ledger storage only on a platform where the probe passed: create, append,
literal `=1+1` stays text, update, read back, find again by id in a new conversation.

- One sheet per ledger; the setup record keeps its link and id. Never create a second one; if a
  new conversation cannot find it, ask for the link.
- Write every cell as a literal string (RAW input), never as a formula.
- At setup, show who can open the sheet: sharing a sheet shares every tab.
- Until the Sheet layout ships, keep the ledger JSON as the source of truth and use the Sheet as
  an export: `ledger.py export` → one tab per CSV.
