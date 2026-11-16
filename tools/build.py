#!/usr/bin/env python3
"""Copy shared sources into every skill folder, check the copies, and package builds.

  python3 tools/build.py            # sync shared/ into plugins/finerd-points/skills/*
  python3 tools/build.py --check    # CI: fail if any copy differs from shared/
  python3 tools/build.py package --target github|claude-directory|chatgpt   # → dist/<target>.zip

Each skill folder must be self-contained (Claude chat copies only the skill's folder into
its sandbox), so shared code, facts and references are copied, not linked.
"""
import argparse
import filecmp
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
PLUGIN = ROOT / "plugins" / "finerd-points"
SKILLS = PLUGIN / "skills"

# What each skill gets. scripts = shared/lib modules; facts = whole catalog; refs = shared/references.
STORE = ["fpstore.py", "fp_commit.sh"]  # every skill that writes the ledger carries the commit script
PLAN = {
    "points":         {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "balances.py"] + STORE,
                       "facts": True, "refs": True},
    "card-credits":   {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py"] + STORE,
                       "facts": True, "refs": True},
    "expirations":    {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py",
                                   "expirations.py"] + STORE,
                       "facts": True, "refs": True},
    "balances":       {"scripts": ["fpledger.py", "ledger.py", "balances.py"] + STORE, "facts": False, "refs": True},
    "points-reports": {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py", "yir.py",
                                   "balances.py", "spend.py", "render_report.py"],
                       "facts": True, "refs": True, "extra_refs": ["year-in-review-formula.md"],
                       "assets": True},
    "facts-check":    {"scripts": ["fpfacts.py"], "tools": ["check_facts.py"], "facts": True, "refs": False},
}
# Connector guides per build. The Claude directory build names only Google, finerd (the publisher's
# own connector), CSV and connectors listed in Claude's directory (verify before each submission).
CONNECTORS = {
    "github": None,  # all
    "claude-directory": ["README.md", "finerd.md", "google-calendar.md", "google-sheets.md", "csv.md"],
    "chatgpt": ["README.md", "finerd.md", "google-calendar.md", "google-sheets.md", "csv.md", "monarch.md",
                "copilot.md"],
}
SKIP = {"__pycache__", ".DS_Store"}


def expected_files(skill):
    """Map destination path (relative to the skill folder) → source path."""
    spec = PLAN[skill]
    out = {}
    for s in spec.get("scripts", []):
        src = SHARED / "lib" / s
        if src.exists():
            out[f"scripts/{s}"] = src
    for t in spec.get("tools", []):
        out[f"scripts/{t}"] = ROOT / "tools" / t
    if spec.get("facts"):
        for p in sorted((SHARED / "facts").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP):
                out[f"facts/{p.relative_to(SHARED / 'facts')}"] = p
    if spec.get("refs"):
        for p in sorted((SHARED / "references").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP) and p.name not in ("year-in-review-formula.md",):
                out[f"references/{p.relative_to(SHARED / 'references')}"] = p
    for r in spec.get("extra_refs", []):
        out[f"references/{r}"] = SHARED / "references" / r
    if spec.get("assets"):
        for p in sorted((SHARED / "assets").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP):
                out[f"assets/{p.relative_to(SHARED / 'assets')}"] = p
    return out


def managed_dirs():
    return ("scripts", "facts", "references", "assets")


ROOT_COPIES = ["LICENSE", "NOTICE", "TERMS.md", "PRIVACY.md", "SECURITY.md"]  # the plugin folder is submitted alone, so it carries its own copies


def sync():
    for f in ROOT_COPIES:
        shutil.copy2(ROOT / f, PLUGIN / f)
    for skill in PLAN:
        d = SKILLS / skill
        want = expected_files(skill)
        for sub in managed_dirs():
            if (d / sub).exists():
                shutil.rmtree(d / sub)
        for rel, src in want.items():
            dst = d / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        print(f"{skill}: {len(want)} files")


def check():
    problems = []
    for f in ROOT_COPIES:
        if not (PLUGIN / f).exists() or not filecmp.cmp(ROOT / f, PLUGIN / f, shallow=False):
            problems.append(f"plugins/finerd-points/{f} differs from {f}")
    for skill in PLAN:
        d = SKILLS / skill
        want = expected_files(skill)
        have = {str(p.relative_to(d)) for sub in managed_dirs() for p in (d / sub).rglob("*")
                if p.is_file() and not (set(p.parts) & SKIP)}
        for rel, src in want.items():
            if rel not in have:
                problems.append(f"{skill}: missing {rel}")
            elif not filecmp.cmp(src, d / rel, shallow=False):
                problems.append(f"{skill}: {rel} differs from {src.relative_to(ROOT)}")
        for rel in sorted(have - set(want)):
            problems.append(f"{skill}: unexpected {rel}")
        if not (d / "SKILL.md").exists():
            problems.append(f"{skill}: no SKILL.md")
    for p in PLUGIN.rglob("*"):
        if p.is_file() and p.stat().st_size >= 256 * 1024:
            problems.append(f"{p.relative_to(ROOT)} is {p.stat().st_size // 1024} KiB (directory review holds ≥256 KiB)")
    if (PLUGIN / "bin").exists():
        problems.append("plugins/finerd-points/bin/ must not exist (blocks install in Claude chat)")
    for msg in problems:
        print("ERROR", msg)
    n = sum(1 for p in PLUGIN.rglob("*") if p.is_file())
    print(f"{n} plugin files; {len(problems)} problems")
    return not problems


def package(target):
    if not check():
        sys.exit(1)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zpath = dist / f"finerd-points-{target}.zip"
    allowed = CONNECTORS[target]
    manifest = {}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PLUGIN.rglob("*")):
            if not p.is_file() or set(p.parts) & SKIP:
                continue
            rel = p.relative_to(PLUGIN)
            if allowed is not None and "connectors" in rel.parts and p.name not in allowed:
                continue
            data = p.read_bytes()
            manifest[str(rel)] = hashlib.sha256(data).hexdigest()
            z.writestr(f"finerd-points/{rel}", data)
        z.writestr("finerd-points/MANIFEST.sha256.json", json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if target == "claude-directory":
        import re
        bad = []
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if name.endswith((".md", ".py", ".json")):
                    text = z.read(name).decode("utf-8", "ignore")
                    if re.search(r"\b(Monarch|Copilot|YNAB)\b", text):
                        bad.append(name)
        if bad:
            zpath.unlink()
            sys.exit("Claude directory build names connectors not in Claude's directory (rule 3.F): " + ", ".join(bad))
    print(f"wrote {zpath.relative_to(ROOT)} ({len(manifest)} files)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="sync", choices=["sync", "package"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--target", choices=list(CONNECTORS), default="github")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    if a.cmd == "package":
        package(a.target)
    else:
        sync()


if __name__ == "__main__":
    main()
