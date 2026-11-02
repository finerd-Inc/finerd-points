#!/usr/bin/env python3
"""Check docs/listing.md against the directories' length limits (ChatGPT submission rules)."""
import re
import sys
from pathlib import Path

text = (Path(__file__).resolve().parent.parent / "docs" / "listing.md").read_text(encoding="utf-8")
field = lambda name: re.search(rf"\*\*{name}:\*\* (.+)", text).group(1).strip()  # noqa: E731
desc = text.split("## Description", 1)[1].split("## Capabilities", 1)[0].strip()
caps = re.findall(r"^\d+\. (.+)$", text.split("## Capabilities", 1)[1].split("## Three", 1)[0], re.M)
problems = []
for name, limit in (("Package name", 64), ("Display name", 30), ("Subtitle", 30), ("Developer", 80)):
    if len(field(name)) > limit:
        problems.append(f"{name} is {len(field(name))} characters (limit {limit})")
if len(desc) > 4000:
    problems.append(f"description is {len(desc)} characters (limit 4000)")
if len(caps) > 20:
    problems.append(f"{len(caps)} capabilities (limit 20)")
for c in caps:
    if len(c) > 120:
        problems.append(f"capability over 120 characters: {c[:60]}…")
print("\n".join(problems) or f"listing OK: description {len(desc)} chars, {len(caps)} capabilities")
sys.exit(1 if problems else 0)
