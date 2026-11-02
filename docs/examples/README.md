# Examples (synthetic data)

All data here is invented. Run from this folder with the scripts in `shared/lib` (or any skill's
`scripts/`):

1. `1-credits.md` — «Which card credits haven't I used this year?»: `normalize.py csv` on
   `gold.csv` and `bgold.csv`, then `credits.py --ledger demo.ledger.json --transactions *.txns.json --format md`.
2. `2-expirations.md` and `calendar-plan.json` — «What expires in the next 60 days? Put it in my
   calendar.»: `expirations.py --ledger demo.ledger.json --credits credits.json --days 60 --calendar-plan calendar-plan.json`.
3. `3-year-in-review.md` — «Did my points game pay off in 2025?»: `yir.py --ledger demo.ledger.json
   --year 2025 --spend spend-2025.json --format md`.

The outputs were generated with `--today 2026-11-02`.
