## What this changes

## Checklist
- [ ] `python3 tools/build.py && python3 tools/build.py --check` passes (copies in skills match `shared/`).
- [ ] `python3 -m unittest discover -s tests` passes.
- [ ] Facts: every value comes from the cited sources; the issuer's or program's page is one of them;
      summaries are in my own words; «not found» is `null`.
- [ ] No personal data, card numbers, member numbers, keys or real statements in code, tests or examples.

## For a short path (`shared/short-paths/<site>/PATH.md`, GitHub build only)
- Site's terms URL (for the record): 
- [ ] I am responsible for this short path and for following that site's terms. I understand the finerd
      team reviews it for security and correctness, not for the site's terms.
- [ ] It is a written recipe only: no scripts, no internal APIs, no clicks that change anything.

## For a finance-app skill (`shared/apps/<app>/APP.md`)
- [ ] `python3 tools/check_apps.py` passes; the header lists the exact tools and the date I checked them
      against the live connector.
- [ ] Read only, unless I am on the finerd team and this was reviewed as a writing skill.
