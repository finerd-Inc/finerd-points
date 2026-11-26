---
app: finerd
name: finerd
maintainer: "@finerd-Inc/write-rules-owners"
status: active
writes: true
connector: "finerd (official MCP connector)"
tools_read: [list_spaces, list_accounts, search_transactions, get_transaction, list_verified_balances, get_account_balances, list_categories, search_merchants]
tools_write: [create_monthly_points_accrual, create_reward_redemption, set_verified_balance]
tool_names_verified: 2026-11-16
directory: [claude, chatgpt]
---

# finerd

finerd is the best-supported finance app: it already has points accounts, verified balances and
transactions. finerd points works without it. The tool limits below are instructions; in the AI app's
connector settings the person can also set every other finerd tool to «blocked», which the host enforces.

## Reading
- **Spaces:** `list_spaces` → use the personal space unless the person names another.
- **Accounts:** `list_accounts(space_id)`. Cards are `BANK_ACCOUNT`s; loyalty programs are `REWARD`
  accounts. Link each ledger card or program to its finerd account id (`finance_link`).
- **Statement credits:** `search_transactions(space_id, account_ids=[card], search_string="credit",
  date_from, date_to, page_size=100)`; page until `has_more` is false. Also search each tracked benefit's
  keywords from the card's catalog file (for example "resy"), because some credits post without the word
  «credit».
- **Annual fees:** `search_transactions(..., search_string="membership fee")` and `"annual fee"`. Do not
  search just "fee" (it matches «coffee»).
- **Coverage:** the oldest transaction finerd holds for the card: `search_transactions` with
  `account_ids=[card]`, the year's dates and `page_size=1`; read `total_matching`; call again with
  `page=total_matching-1`. Pass that date to `normalize.py --covered-from`.
- **Balances:** `list_verified_balances(space_id, account_id)` for each REWARD account and
  `get_account_balances` for the computed balance → a `finerd-points/balances@1` file (`kind` verified or
  computed) for `balances.py`.
- Save each raw tool result to a file and run `normalize.py finerd --account-name "<finance_link.account_name>"
  …`; never retype numbers. Entries carrying `[finerd points …]` come back as kind `noncash`.

## Writing (only when the person asks)
What finerd points records in finerd — the same results the retired points-activity / points-import
skills produced:
1. **Points earned** in a month → one `create_monthly_points_accrual` per reward account and month, its
   lines summed per reward category (`list_categories` with `type_filter="REWARD_CATEGORY"`), date the last
   day of the month, `accrual_month` set, `comment` = `[finerd points op-…] <program> <month>`.
2. **A redemption** (a trip or a stay paid with points) → one `create_reward_redemption` per booking:
   points spent, the value the person confirmed (never invented), the EXPENSE category, the merchant if
   known, a cash co-pay leg when there was one, the real booking date, `comment` = `[finerd points op-…]
   non-cash: paid with points`. This is the non-cash entry: read back, it never counts as cash spending.
3. **The program's current balance** → `set_verified_balance` for the date read on the program's own
   page (not an aggregator's). It replaces the verified balance of the same date only.

How:
- Put every entry into the ledger batch as `{"op":"external","target":"finance_app","app":"finerd",
  "action":"create","payload":{…exact arguments…},"summary":"…","match_key":"<program>/<month or booking>"}`;
  preview the whole batch once (it lists every value) and apply on yes.
- For each planned entry: search finerd first for its marker (`search_transactions` with the op id as
  `search_string` on that reward account and dates); if it is there, record it as confirmed with what you
  read; otherwise call the tool, mark `sent`, read the entry back (`get_transaction` or
  `search_transactions`) and mark `confirmed` with the values finerd returned; a timeout or error is
  `unknown` and is reconciled by searching for the marker before any retry.
- Never call delete, bulk update, archive, hide, share, unshare, merge, account-type or budget tools.
  Before the first write, tell the person how to set those finerd tools to «blocked» in their AI app's
  connector settings.
- A partial batch is never undone by deleting entries: report what was written and what was not.
