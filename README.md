# finerd points

Open, crowdsourced skills for AI assistants that collect your points, miles, card credits and deadlines
from whatever you open, keep them in a ledger on your own computer, and show you a report. No server,
no sign-up.

- **The plugin:** [`plugins/finerd-points`](plugins/finerd-points/README.md) — what it does, what it
  runs, reads, sends and stores.
- **Install in Claude Code:** `/plugin marketplace add finerd-Inc/finerd-points`, then
  `/plugin install finerd-points@finerd`. Releases are signed tags (see SECURITY.md).
- **Contribute** a card, a program, a finance-app skill, a program sender or a short path:
  [CONTRIBUTING.md](CONTRIBUTING.md). The finerd team reviews and merges every change.

Repository layout: `shared/` holds the single source of scripts (`lib/`, including the commit
script `fp_commit.sh`), the facts catalog (`facts/`), finance-app skills (`apps/`), short paths
(`short-paths/`) and references; `tools/build.py` copies them into each self-contained skill folder,
and CI checks the copies. `tests/` holds the method's worked cases and synthetic fixtures.

MIT License. Card and program names belong to their owners; see NOTICE.
