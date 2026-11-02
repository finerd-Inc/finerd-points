# Contributing to finerd points

Anyone can propose a change; the finerd team reviews and merges every pull request.

## Add or update a card
1. Copy a file in `shared/facts/cards/` and follow `shared/facts/README.md`.
2. Sources: the issuer's own page plus at least two independent reviews; give each a check date.
   What all agree on is the fact; where they differ, record both values under `disagreements`.
3. Summaries in your own words; unknown values are `null`; a changed term gets a new entry with
   `effective_from`, never an edit of history.
4. Run `python3 tools/check_facts.py`, `python3 tools/build.py`, `python3 tools/build.py --check`
   and `python3 -m unittest discover -s tests`.

## Add a connector guide
One file in `shared/references/connectors/<app>.md`: how to read the fields of the normalized
transaction contract (`shared/lib/normalize.py`), and the write rules (never delete, archive or
share; one preview; duplicate checks). Write rules need a code owner's approval.

## Program adapters
Site-specific «short paths» for reading a program's own pages live in the separate
`program-adapters` package (GitHub only, not in the directories). Each adapter records the
program's terms URL, and its contributor takes responsibility for the access it performs; the
finerd team reviews security and correctness, not the program's terms. There is no list of allowed
or forbidden programs.

## Never commit
Personal data, real statements, card numbers, member numbers, API keys or anyone's balances —
tests use synthetic fixtures only.
