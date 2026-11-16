# Monarch (official MCP, `https://api.monarch.com/mcp`)

- Read access is enough for finerd points. Monarch offers read or read+write at connection time;
  recommend read-only unless the person wants writes.
- Read card transactions for the date window, keep only the contract fields (date, merchant or
  original description, amount, currency, account name, pending), write them as a CSV or JSON and
  normalize with `normalize.py csv`. Statement credits show as positive amounts on the card.
- Monarch excludes some aggregator-sourced accounts and has weekly usage limits; if a card is
  missing, say so and mark its coverage unknown.
- Never delete, hide, recategorize in bulk or share. Writes only on request, after one preview.
