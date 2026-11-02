# finerd points

Open, crowdsourced skills for AI assistants that track credit-card credits, points and miles,
expiring benefits and your yearly points result in a ledger you own. No server, no database.

- **The plugin:** [`plugins/finerd-points`](plugins/finerd-points/README.md) — what it does, what it
  runs, reads, sends and stores.
- **Install in Claude Code:** `/plugin marketplace add finerd-Inc/finerd-points`, then
  `/plugin install finerd-points@finerd`. Releases are signed tags (see SECURITY.md).
- **Contribute** a card, a program or a connector guide: [CONTRIBUTING.md](CONTRIBUTING.md). The
  finerd team reviews and merges every change.

Repository layout: `shared/` holds the single source of scripts (`lib/`), the facts catalog
(`facts/`) and references; `tools/build.py` copies them into each self-contained skill folder,
and CI checks the copies. `tests/` holds the method's worked cases and synthetic fixtures.

MIT License. Card and program names belong to their owners; see NOTICE.
