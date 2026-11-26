#!/usr/bin/env python3
"""Check every finance-app skill (shared/apps/<app>/APP.md) before it ships (spec v2, app skills).

Fails when: the header is missing or malformed; a skill names a tool that deletes, archives, hides,
shares, merges or edits in bulk; writes: false lists write tools; writes: true comes from outside the
finerd team; a writing skill has no verified tool names.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "shared" / "apps"
FORBIDDEN = re.compile(r"(?i)(delete|remove|archive|hide|unhide|share|unshare|merge|bulk|batch_update|purge|"
                       r"close_account|change_account_type|apply_clusters)")
KEYS = ("app", "name", "maintainer", "status", "writes", "connector", "tools_read", "tool_names_verified",
        "directory")
DIRECTORIES = {"claude", "chatgpt"}


def header(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        v = v.split("#")[0].strip() if not v.strip().startswith('"') else v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        elif v in ("true", "false"):
            v = v == "true"
        elif v == "null":
            v = None
        else:
            v = v.strip('"')
        out[k.strip()] = v
    return out


def check():
    problems = []
    apps = {}
    for d in sorted(p for p in APPS.iterdir() if p.is_dir()):
        f = d / "APP.md"
        h = header(f) if f.exists() else None
        if h is None:
            problems.append(f"{d.name}: APP.md with a header is missing")
            continue
        apps[d.name] = h
        missing = [k for k in KEYS if k not in h]
        if missing:
            problems.append(f"{d.name}: header lacks {', '.join(missing)}")
            continue
        if h["app"] != d.name:
            problems.append(f"{d.name}: app is {h['app']!r}, not the folder name")
        if h["status"] not in ("active", "draft", "broken"):
            problems.append(f"{d.name}: status must be active, draft or broken")
        for k in ("tools_read", "tools_write", "directory"):
            v = h.get(k)
            if v is not None and not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
                problems.append(f"{d.name}: {k} must be a list of names, like [a, b]")
        if not isinstance(h.get("writes"), bool):
            problems.append(f"{d.name}: writes must be true or false")
            continue
        tools = [t for k in ("tools_read", "tools_write") if isinstance(h.get(k), list) for t in h[k]]
        bad = [t for t in tools if FORBIDDEN.search(t)]
        if bad:
            problems.append(f"{d.name}: names forbidden tools {', '.join(bad)}")
        if not h["writes"] and h.get("tools_write"):
            problems.append(f"{d.name}: writes is false but tools_write is listed")
        if h["writes"]:
            if not str(h["maintainer"]).startswith("@finerd-Inc/"):
                problems.append(f"{d.name}: only the finerd team ships app skills that write (v1)")
            if not h.get("tools_write"):
                problems.append(f"{d.name}: writes is true but no tools_write")
            if not h.get("tool_names_verified"):
                problems.append(f"{d.name}: a writing app skill needs tool names verified against the live connector")
        if not isinstance(h["directory"], list) or set(h["directory"]) - DIRECTORIES:
            problems.append(f"{d.name}: directory is a list of {', '.join(sorted(DIRECTORIES))}")
        body = f.read_text(encoding="utf-8").split("---", 2)[-1]
        if h["writes"] is False and re.search(r"(?i)\b(create|update|record)_\w+\(", body):
            problems.append(f"{d.name}: a read-only app skill shows a write call")
    return apps, problems


def main():
    apps, problems = check()
    for p in problems:
        print("ERROR", p)
    print(f"{len(apps)} app skills; {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
