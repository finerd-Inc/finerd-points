---
app: monarch
name: Monarch
maintainer: "@finerd-Inc/maintainers"
status: active
writes: false
connector: "Monarch connector the person added to their AI app"
tools_read: [get_accounts, get_transactions]
tool_names_verified: null
directory: []
---

# Monarch (read only)

Read-only in this version: finerd points does not write into Monarch until the finerd team reviews and
releases a writing version. The tool names above are not yet verified against a live Monarch connector
(several community connectors exist, with different tool sets); before using them, list the connected
tools and use only the account and transaction listing tools that only read. If none fits, stop and say
so. This limit is instruction-only; the person can also switch every other Monarch tool off in their AI
app's connector settings.

- Read card transactions for the date window and keep only the contract fields (date, merchant or
  original description, amount, currency, account name, pending); write them as a CSV or JSON and
  normalize with `normalize.py csv`. Statement credits show as positive amounts on the card.
- Monarch can leave out some aggregator-sourced accounts and limits usage; if a card is missing, say so
  and mark its coverage unknown.
- Never create, update, delete, hide, recategorize, tag or share anything in Monarch.
