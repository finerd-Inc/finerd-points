# Facts check: amex-business-gold, Squarespace credit (2026-11-02)

Trigger: a real statement credit «Squarespace Statement Credit» posted on 2026-07-21, before the
catalog's `effective_from` of 2026-08-21.

| Field | Old | New | Sources |
|---|---|---|---|
| `benefits[squarespace].effective_from` | not set (earlier research said 2026-08-21) | 2025-10-23 | Doctor of Credit (posted 2025-10-23, updated 2026-08-21), The Points Guy, AwardWallet |
| `benefits[squarespace].note` | announced 2026-08-21 | started 2025-10-23; eligible purchases directly with Squarespace | same |

Amount ($150 per calendar year), enrollment (required) and evidence (statement credit) are
unchanged and agree across the issuer page and the three reviews. The earlier date came from the
review article's update date, not from the launch.

Checked with `python3 scripts/check_facts.py`: 10 cards, 7 programs, 0 problems.
