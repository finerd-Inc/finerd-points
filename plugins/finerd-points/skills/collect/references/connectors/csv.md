# Any finance app, bank or card export (CSV)

`normalize.py csv --file export.csv --account-name "<the card's finance_link.account_id>" --date-col <col>
--desc-col <col> --amount-col <col> --negative-is debit|credit [--date-format %m/%d/%Y]
--from <first day> --to <last day>`

- Check the sign on one known purchase before choosing `--negative-is`; US-style dates need
  `--date-format %m/%d/%Y`.
- Remove card numbers and account numbers from the file before reading it.
- Coverage is the export's date range; say so if the export may be partial.
