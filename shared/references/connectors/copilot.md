# Copilot Money (official MCP, `https://mcp.copilot.money/mcp`, read-only)

- Read card transactions for the window and normalize them with `normalize.py csv`
  (positive = credit back to the card, unless the export uses the opposite sign: check one
  known purchase first and set `--negative-is` accordingly).
- Copilot's MCP cannot write, so finerd points never proposes writes to Copilot.
