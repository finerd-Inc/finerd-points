---
app: copilot
name: Copilot Money
maintainer: "@finerd-Inc/maintainers"
status: active
writes: false
connector: "Copilot Money's own MCP connector (https://mcp.copilot.money/mcp, read only)"
tools_read: [get_accounts, get_transactions]
tool_names_verified: null
directory: []
---

# Copilot Money (read only)

Read-only in this version. Copilot Money's own connector reads only; community connectors for Copilot
also exist, some with write tools switched on by default — with one of those, use only the account and
transaction listing tools that only read. The tool names above are not yet verified against the live
connector; list the connected tools first, and if none fits, stop and say so. This limit is
instruction-only.

- Read card transactions for the date window and keep only the contract fields (date, merchant or
  original description, amount, currency, account name, pending); write them as a CSV and normalize with
  `normalize.py csv`.
- If a card is missing or the history is short, say so and mark its coverage unknown.
- Never create, update, delete, categorize, tag, hide or share anything in Copilot.
