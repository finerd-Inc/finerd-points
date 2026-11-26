---
app: monarch
name: Monarch
maintainer: "@finerd-Inc/maintainers"
status: active
writes: false
connector: "Monarch's own MCP connector (https://api.monarch.com/mcp; read or read and write, chosen when connecting)"
tools_read: [get_accounts, get_transactions]
tool_names_verified: null
directory: []
---

# Monarch (read only)

Read-only in this version: finerd points does not write into Monarch until the finerd team reviews and
releases a writing version; recommend connecting Monarch read-only. The tool names above are not yet
verified against the live connector (community connectors with other tool sets also exist); before using
them, list the connected tools and use only the account and transaction listing tools that only read. If
none fits, stop and say so. This limit is instruction-only; the person can also switch every other Monarch tool off in their AI
app's connector settings.

- Read card transactions for the date window and keep only the contract fields (date, merchant or
  original description, amount, currency, account name, pending); write them as a CSV or JSON and
  normalize with `normalize.py csv`. Statement credits show as positive amounts on the card.
- Monarch can leave out some aggregator-sourced accounts and limits usage; if a card is missing, say so
  and mark its coverage unknown.
- Never create, update, delete, hide, recategorize, tag or share anything in Monarch.
