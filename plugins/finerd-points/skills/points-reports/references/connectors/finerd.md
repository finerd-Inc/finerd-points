# finerd (official MCP)

finerd is the best-supported finance app: it already has points accounts, verified balances
and transactions. finerd points works without it.

## Read paths
- **Spaces:** `list_spaces` → use the personal space unless the person names another.
- **Accounts:** `list_accounts(space_id)`. Cards are `BANK_ACCOUNT`s; loyalty programs are
  `REWARD` accounts. Link each ledger card to its finerd account id (`finance_link`).
- **Statement credits:** `search_transactions(space_id, account_ids=[card], search_string="credit",
  date_from, date_to, page_size=100)`; page until `has_more` is false. Credits usually arrive as
  type INCOME into the card account (e.g. «AMEX RESY CREDIT»). Also search each tracked benefit's
  keywords from the card's catalog file (for example "resy", "squarespace"), because some credits
  post without the word «credit».
- **Annual fees:** `search_transactions(..., search_string="membership fee")` and
  `"annual fee"`. Do not search just "fee" (it matches «coffee»).
- **Coverage:** the oldest transaction finerd holds for the card: call `search_transactions`
  with `account_ids=[card]`, the year's dates and `page_size=1`; read `total_matching`; call
  again with `page=total_matching-1`. Pass that date to `normalize.py --covered-from`.
- **Balances:** `list_verified_balances(space_id, account_id)` for each REWARD account (latest
  first: date and amount, verified from the program account) and `get_account_balances` for the
  current computed balance. Write them into a `finerd-points/balances@1` file (kind `verified`
  or `computed`).
- Save each raw tool result to a file and run `normalize.py finerd --account-name "<the card's
  finance_link.account_name, exactly>" …`; never retype numbers. A wrong name is refused with the
  account names found in the files.

## Write rules
- finerd points itself never writes to finerd. Only when the person asks (for example to record
  a redemption or a points accrual), follow the person's own finerd import skill if present
  (points-activity's `points-import`), with one preview and no duplicates.
- Never call delete, bulk update, archive, share or account-type tools. Before the first write,
  tell the person to set those finerd tools to «blocked» (or «ask») in their AI app's connector
  settings.
