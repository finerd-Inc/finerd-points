#!/usr/bin/env python3
"""List catalog facts older than 90 days or not yet confirmed on a primary page (weekly CI job).

  python3 tools/stale_facts.py [--today YYYY-MM-DD] [--facts DIR]   # markdown for the one stale-list issue
Exit code 0 always; an empty list prints «Nothing is stale.».
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import fpfacts as ff  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    ap.add_argument("--facts", default=str(ROOT / "shared" / "facts"))
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    items = ff.stale_facts(ff.load_catalog(a.facts), today)
    print(f"Facts to re-check as of {today.isoformat()} (owner: the finerd team; clear within 30 days by "
          f"re-reading the issuer's or program's own page, or retire the fact).\n")
    if not items:
        print("Nothing is stale.")
        return
    print("| File | Fact | Checked on | Why |\n|---|---|---|---|")
    for f, item, checked, why in items:
        print(f"| `{f}` | {item} | {checked} | {why} |")
    print(f"\n{len(items)} fact(s). The skills already show each of them as unverified, with its check date.")


if __name__ == "__main__":
    main()
