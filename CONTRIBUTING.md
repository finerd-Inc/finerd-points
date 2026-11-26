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

## Add or update a program
`shared/facts/programs/<id>.json`: unit, kind, the expiry rule as the program states it, and `hosts`
(where a member signs in and sees activity — `collect` reads only these hosts or ones the person
names). The program's own page must be among the sources of the expiry rule.

## Add a finance-app skill
One folder `shared/apps/<app>/APP.md` with the header in `shared/apps/README.md`: the exact connector
tools it may call, checked against the live connector, and how to read what finerd points needs.
Community app skills are read only; in the first version only the finerd team ships app skills that
write. `python3 tools/check_apps.py` must pass. Changes need a code owner's approval.

## Add a program sender
`shared/references/email-senders.md`: the program's or bank's own sender domain. No shared or consumer
mail domains, no wildcards. Needs a code owner's approval.

## Short paths
A short path is a written recipe for reading one site faster and more completely
(`shared/short-paths/<site>/PATH.md`, rules in `shared/short-paths/README.md`). Whoever submits it is
responsible for it and for following that site's terms; the finerd team reviews security and
correctness, not the site's terms. Short paths ship only in the GitHub build, never in directory
builds. There is no list of allowed or forbidden sites.

## Never commit
Personal data, real statements, card numbers, member numbers, API keys or anyone's balances —
tests use synthetic fixtures only.
