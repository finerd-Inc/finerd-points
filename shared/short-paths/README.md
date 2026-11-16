# Short paths (community, GitHub build only)

A short path is a written recipe for one site: which page holds the full history, which filter or date
range shows all of it, how its rows look, and how the site marks the end of the history. It makes
`collect` faster and more complete on that site. It is never code: no scripts, no requests to the site's
internal APIs, no stored selectors that click — the reading rules in `references/reading-rules.md` apply
unchanged, and a short path cannot loosen them.

**Responsibility.** Whoever submits a short path is responsible for it and for following that site's
terms; the pull-request template and the terms of use say so. The finerd team reviews contributions for
security and correctness, not for the site's terms. Short paths ship only in the GitHub build, never in
directory builds.

**Format.** `short-paths/<site-id>/PATH.md`:

```
---
site: world-of-hyatt
hosts: [www.hyatt.com]              # the only hosts it applies to
market: US
contributor: "@github-handle"
checked_on: 2026-11-16              # the last date it was followed on the live site
---
Where: Account → Activity. Filter: «All» in the date menu shows 24 months; older history: …
Rows: date, description, points (+/−). End of history: the list stops with «No more activity».
Known traps: «Load more» stops silently after ~12 months — switch to the yearly filter instead.
```

**How `collect` uses one (GitHub build).** After identifying a site, if `short-paths/<site-id>/PATH.md`
exists and its `hosts` include the current host, read it as advice and follow it within the reading
rules. A short path older than 90 days is advice only to check against the page; if the page differs,
say so and read the page as it is.
