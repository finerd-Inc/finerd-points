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
import re
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
STORE = ["fpstore.py", "fp_commit.sh", "fpcollect.py"]  # every skill with ledger.py writes through bin/commit
PLAN = {
    "points":         {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "balances.py"] + STORE,
                       "facts": True, "refs": True, "apps": True},
    "card-credits":   {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py"] + STORE,
                       "facts": True, "refs": True, "apps": True},
    "expirations":    {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py",
                                   "expirations.py"] + STORE,
                       "facts": True, "refs": True, "apps": True},
    "balances":       {"scripts": ["fpledger.py", "ledger.py", "balances.py"] + STORE, "facts": False, "refs": True,
                       "apps": True},
    "points-reports": {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py", "yir.py",
                                   "balances.py", "spend.py", "render_report.py", "expirations.py",
                                   "report.py"] + STORE,
                       "facts": True, "refs": True, "extra_refs": ["year-in-review-formula.md"],
                       "assets": True, "apps": True},
    "collect":        {"scripts": ["fpledger.py", "ledger.py", "normalize.py", "fpfacts.py", "credits.py", "yir.py",
                                   "balances.py", "expirations.py", "render_report.py", "report.py"] + STORE,
                       "facts": True, "refs": True, "assets": True, "apps": True, "short_paths": True},
    "facts-check":    {"scripts": ["fpfacts.py"], "tools": ["check_facts.py"], "facts": True, "refs": False},
}
# Builds. A directory build carries only the app skills whose APP.md lists that directory (Claude: the
# publisher's own connector or one in Claude's directory, checked per app before each submission), never
# short paths, and none of the text between github-build-only markers.
TARGETS = {"github": None, "claude-directory": "claude", "chatgpt": "chatgpt"}
LEGAL_TEXTS = {"TERMS.md", "PRIVACY.md"}
ALLOWED_SUFFIXES = {".md", ".py", ".json", ".sh", ".css", ".png"}
PNG_ALLOWED = {"assets/icon.png"}
GITHUB_ONLY = re.compile(r"\n?<!-- github-build-only:start -->.*?<!-- github-build-only:end -->\n?", re.S)
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
    if spec.get("apps"):
        for p in sorted((SHARED / "apps").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP):
                out[f"references/apps/{p.relative_to(SHARED / 'apps')}"] = p
    if spec.get("short_paths"):
        for p in sorted((SHARED / "short-paths").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP):
                out[f"short-paths/{p.relative_to(SHARED / 'short-paths')}"] = p
    if spec.get("assets"):
        for p in sorted((SHARED / "assets").rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP):
                out[f"assets/{p.relative_to(SHARED / 'assets')}"] = p
    return out


def managed_dirs():
    return ("scripts", "facts", "references", "assets", "short-paths")


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


# What each shared source folder may hold. Anything else (a script disguised as an image, a loader) never
# reaches a skill folder.
SOURCE_FORMATS = {"lib": {".py", ".sh"}, "references": {".md"}, "facts": {".json", ".md"}, "apps": {".md"},
                  "short-paths": {".md"}, "assets": {".css"}}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check():
    problems = []
    for sub, allowed in SOURCE_FORMATS.items():
        for p in (SHARED / sub).rglob("*"):
            if p.is_symlink():
                problems.append(f"shared/{sub}/{p.relative_to(SHARED / sub)} is a symbolic link")
            elif p.is_file() and not (set(p.parts) & SKIP) and p.suffix not in allowed:
                problems.append(f"shared/{sub}/{p.relative_to(SHARED / sub)}: only {', '.join(sorted(allowed))} "
                                f"files belong in shared/{sub}")
    icon = PLUGIN / "assets" / "icon.png"
    if icon.exists() and not icon.read_bytes().startswith(PNG_MAGIC):
        problems.append("plugins/finerd-points/assets/icon.png is not a PNG image")
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
    known = {PLUGIN / f for f in ROOT_COPIES} | {PLUGIN / ".claude-plugin" / "plugin.json", PLUGIN / "README.md",
                                                  PLUGIN / "assets" / "icon.png"}
    for skill in PLAN:
        known.add(SKILLS / skill / "SKILL.md")
        known |= {SKILLS / skill / rel for rel in expected_files(skill)}
    for p in PLUGIN.rglob("*"):
        if p.is_file() and not (set(p.parts) & SKIP) and p not in known:
            problems.append(f"{p.relative_to(ROOT)} is not part of the plugin (only generated copies, SKILL.md files and "
                            f"the manifest, README, legal texts and icon may be there)")
        if p.is_symlink():
            problems.append(f"{p.relative_to(ROOT)} is a symbolic link")
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


def _app_dirs():
    sys.path.insert(0, str(ROOT / "tools"))
    import check_apps
    apps, problems = check_apps.check()
    if problems:
        sys.exit("App skills do not pass tools/check_apps.py: " + "; ".join(problems))
    return apps


def package(target):
    if not check():
        sys.exit(1)
    directory = TARGETS[target]
    apps = _app_dirs()
    excluded = set() if directory is None else {a for a, h in apps.items()
                                                 if directory not in h["directory"] or h["status"] != "active"}
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zpath = dist / f"finerd-points-{target}.zip"
    manifest = {}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PLUGIN.rglob("*")):
            if not p.is_file() or set(p.parts) & SKIP:
                continue
            rel = p.relative_to(PLUGIN)
            if directory is not None:
                if "short-paths" in rel.parts:
                    continue
                if "apps" in rel.parts and rel.parts[rel.parts.index("apps") + 1] in excluded:
                    continue
            if p.suffix not in ALLOWED_SUFFIXES and p.name not in ("LICENSE", "NOTICE"):
                sys.exit(f"The {target} build may not carry {rel} (only {', '.join(sorted(ALLOWED_SUFFIXES))})")
            if p.suffix == ".png" and (str(rel) not in PNG_ALLOWED or not p.read_bytes().startswith(PNG_MAGIC)):
                sys.exit(f"The {target} build may not carry {rel}: the only image is the PNG icon")
            data = p.read_bytes()
            if directory is not None and p.suffix == ".md":
                data = GITHUB_ONLY.sub("\n", data.decode("utf-8")).encode("utf-8")
            manifest[str(rel)] = hashlib.sha256(data).hexdigest()
            z.writestr(f"finerd-points/{rel}", data)
        z.writestr("finerd-points/MANIFEST.sha256.json", json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if directory is not None:
        # Release check (spec v2): no short path, no loader or instruction that calls one, and no excluded
        # app skill or text that names it.
        names = [apps[a]["name"] for a in excluded] + sorted(excluded)
        rx = re.compile(r"short-paths|short path|github-build-only|references/apps/(" +
                        "|".join(re.escape(a) for a in sorted(excluded) or ["$^"]) + r")\b" +
                        ("|\\b(" + "|".join(re.escape(n) for n in names) + r")\b" if names else ""), re.I)
        bad = []
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if "short-paths" in name:
                    bad.append(name)
                elif not name.endswith(".png"):
                    if name.rsplit("/", 1)[-1] in LEGAL_TEXTS:
                        continue  # the terms disclose that short paths exist; they load nothing
                    m = rx.search(z.read(name).decode("utf-8", "ignore"))
                    if m:
                        bad.append(f"{name} ({m.group(0)})")
        if bad:
            zpath.unlink()
            sys.exit(f"The {target} build is not clean (short paths or app skills it may not carry): " + ", ".join(bad))
    print(f"wrote {zpath.relative_to(ROOT)} ({len(manifest)} files; app skills left out: "
          f"{', '.join(sorted(excluded)) or 'none'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="sync", choices=["sync", "package"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--target", choices=list(TARGETS), default="github")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    if a.cmd == "package":
        package(a.target)
    else:
        sync()


if __name__ == "__main__":
    main()
