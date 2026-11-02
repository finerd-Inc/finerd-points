# Security

Report vulnerabilities privately to **security@finerd.ai** [to be confirmed by the finerd team],
not in public issues. We answer within five working days.

## What we treat as security issues
- A skill instruction or script that could send a person's data anywhere, write to an app without
  a preview, delete anything, or store card numbers, passwords, codes, keys or ID numbers.
- Prompt injection through statements, emails, web pages or catalog text that changes what a
  skill does.
- A build or release that ships files other than the reviewed ones.

## How the project protects people
- Skills only, no server. Scripts use only the Python standard library and never open network
  connections.
- Every write is previewed as one batch; the ledger refuses a batch whose hash the person did not
  see, writes only with the writer lease, and never deletes (the one exception is a household
  member's privacy withdrawal, previewed).
- External writes carry deterministic operation ids and are confirmed only after a read-back.
- Main is protected; changes to skill instructions, connector write rules, the runner, host
  allowlists and build settings need a code owner's approval; releases are signed tags with a
  SHA-256 manifest of every file.
