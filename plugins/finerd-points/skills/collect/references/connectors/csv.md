# Any finance app, bank or card export (CSV)

`normalize.py csv --file export.csv --account-name "<the card's finance_link.account_id>" --date-col <col>
--desc-col <col> --amount-col <col> --negative-is debit|credit [--date-format %m/%d/%Y]
--from <first day> --to <last day>`

- Check the sign on one known purchase before choosing `--negative-is`; US-style dates need
  `--date-format %m/%d/%Y`.
- `normalize.py` keeps only date, description, amount and currency; it never copies other columns. If the
  file has full card or account numbers in the description itself, ask the person to remove them first.
- Coverage is the export's date range; say so if the export may be partial.
