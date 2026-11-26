# Finance-app skills

One folder per app: `apps/<app>/APP.md`. Each says how finerd points reads what it needs from that app
and, where the app skill writes, how it records entries there on the person's request. Finance apps are
optional: a person with none loses nothing in collection or in the report.

**How they are used.** They are reference material, not skills that trigger on their own: `collect`,
`card-credits` and `points` load an app's file only when the person has connected that app, so the core
preview and write rules always apply.

**The header every APP.md starts with** (checked by `tools/check_apps.py` in CI):

```
---
app: example-app                  # the folder name
name: Example App                 # as people know it
maintainer: "@github-handle"      # who answers for it
status: active | draft | broken   # broken = disabled until fixed; draft = not loaded
writes: false                     # true only for app skills the finerd team released (v1 rule)
connector: "what the person connects"
tools_read: [tool, …]             # the exact connector tools the skill may call to read
tools_write: [tool, …]            # only when writes: true
tool_names_verified: 2026-11-16   # the date the tool names were checked against the live connector, or null
directory: [claude]               # directory builds that may carry it (see below); [] = GitHub build only
---
```

**Rules.**
- Only the finerd team ships app skills that write (`writes: true`); a community app skill is read-only
  until the team reviews and releases it.
- Any change needs a code owner's review (`.github/CODEOWNERS`). Security review covers everything that
  can affect a write: instructions, scripts and their dependencies.
- The release check fails when a skill names any tool that deletes, archives, hides, shares, merges or
  edits in bulk, when `writes: false` lists write tools, or when `writes: true` comes from outside the
  finerd team.
- Where the host can restrict which tools a skill calls, that restriction is used; otherwise the limit
  is instruction-only, and the APP.md says so.
- Every write follows `references/writes.md`: one preview of the whole batch bound to the destination
  account and the exact entries; a marker `[finerd points op-…]` in each entry; search the destination
  for the marker before writing; per-entry states planned, sent, confirmed or unknown with a read-back;
  an unknown outcome is reconciled before any retry; never «roll back» by deleting.
- A redemption recorded in an app is a non-cash entry with its value and the marker; read back later,
  such entries are recognized (`normalize.py` gives them kind `noncash`) and never counted as cash
  spending or as a second redemption.
- **Directory builds** carry only the app skills a directory allows. Claude's directory: an app whose
  connector is in Claude's directory or owned by the publisher (finerd) — checked per app before each
  submission. Everything else ships in the GitHub build only.
