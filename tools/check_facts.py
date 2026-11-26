#!/usr/bin/env python3
"""Validate the facts catalog (stdlib only).

Usage: python3 tools/check_facts.py [facts_dir]
Exits non-zero and prints every problem when a file breaks the schema in
shared/facts/README.md.
"""
import json
import re
import sys
from pathlib import Path

KINDS = {"statement_credit", "wallet_credit", "folio_credit", "certificate", "status",
         "percentage_credit", "membership_credit", "redemption_option", "other"}
PERIODS = {"month", "quarter", "half_year", "calendar_year", "card_year", "per_stay",
           "per_booking", "ongoing", "one_time"}
ENROLL = {"required", "not_required", "unknown"}
EVIDENCE = {"statement_credit", "wallet", "folio", "program_account", "none"}
SOURCE_KINDS = {"issuer", "program", "review", "community"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
EXPIRY_RULES = {"activity", "fixed", "never", "other"}


def is_date(v):
    return v is None or (isinstance(v, str) and DATE.match(v))


def check_sources_ref(where, refs, sources, errs):
    if not isinstance(refs, list) or not refs:
        errs.append(f"{where}: sources must be a non-empty list")
        return
    for r in refs:
        if r not in sources:
            errs.append(f"{where}: unknown source {r!r}")


def check_card(path, d, programs, errs):
    w = path.name
    if d.get("schema") != "finerd-points/card@1":
        errs.append(f"{w}: schema must be finerd-points/card@1")
    if d.get("id") != path.stem or not ID.match(d.get("id", "")):
        errs.append(f"{w}: id must equal the file name and be kebab-case")
    for k in ("name", "issuer", "country", "segment", "currency", "rule_version", "checked_on"):
        if not d.get(k):
            errs.append(f"{w}: missing {k}")
    if d.get("segment") not in {"personal", "business"}:
        errs.append(f"{w}: segment must be personal or business")
    if not is_date(d.get("checked_on")) or not is_date(d.get("rule_version")):
        errs.append(f"{w}: checked_on and rule_version must be YYYY-MM-DD")
    rp = d.get("rewards_program")
    if rp is not None and programs is not None and rp not in programs:
        errs.append(f"{w}: rewards_program {rp!r} has no programs/{rp}.json")
    sources = d.get("sources") or {}
    for sid, s in sources.items():
        for k in ("title", "url", "publisher", "kind", "checked_on"):
            if not s.get(k):
                errs.append(f"{w}: source {sid} missing {k}")
        if s.get("kind") not in SOURCE_KINDS:
            errs.append(f"{w}: source {sid} kind must be one of {sorted(SOURCE_KINDS)}")
        if not str(s.get("url", "")).startswith("https://"):
            errs.append(f"{w}: source {sid} url must be https")
        if not is_date(s.get("published")) or not is_date(s.get("checked_on")):
            errs.append(f"{w}: source {sid} dates must be YYYY-MM-DD or null")
    if not any(s.get("kind") in {"issuer", "program"} for s in sources.values()):
        errs.append(f"{w}: needs at least one issuer or program source")
    for i, fee in enumerate(d.get("annual_fee") or []):
        where = f"{w}: annual_fee[{i}]"
        if not isinstance(fee.get("amount"), (int, float)):
            errs.append(f"{where}: amount must be a number")
        if not is_date(fee.get("effective_from")) or not is_date(fee.get("effective_to")):
            errs.append(f"{where}: dates must be YYYY-MM-DD or null")
        check_sources_ref(where, fee.get("sources"), sources, errs)
    if not d.get("annual_fee"):
        errs.append(f"{w}: annual_fee must list at least one entry")
    seen = set()
    for b in d.get("benefits") or []:
        bid = b.get("id", "?")
        where = f"{w}: benefit {bid}"
        if not ID.match(bid):
            errs.append(f"{where}: id must be kebab-case")
        if bid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(bid)
        if not b.get("name"):
            errs.append(f"{where}: missing name")
        if b.get("kind") not in KINDS:
            errs.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if b.get("period") not in PERIODS:
            errs.append(f"{where}: period must be one of {sorted(PERIODS)}")
        if b.get("enrollment") not in ENROLL:
            errs.append(f"{where}: enrollment must be one of {sorted(ENROLL)}")
        if b.get("evidence") not in EVIDENCE:
            errs.append(f"{where}: evidence must be one of {sorted(EVIDENCE)}")
        for k in ("amount", "annual_max"):
            if b.get(k) is not None and not isinstance(b.get(k), (int, float)):
                errs.append(f"{where}: {k} must be a number or null")
        if not isinstance(b.get("carryover"), bool):
            errs.append(f"{where}: carryover must be true or false")
        m = b.get("match")
        if b.get("evidence") == "statement_credit":
            if not m or not m.get("keywords"):
                errs.append(f"{where}: statement_credit evidence needs match.keywords")
            elif any((not isinstance(k, str)) or k != k.upper() for k in m["keywords"]):
                errs.append(f"{where}: match keywords must be uppercase strings")
        elif m is not None:
            errs.append(f"{where}: match is only for statement_credit evidence")
        if not is_date(b.get("effective_from")) or not is_date(b.get("effective_to")):
            errs.append(f"{where}: dates must be YYYY-MM-DD or null")
        req = b.get("requires")
        if req is not None and (not isinstance(req, dict) or req.get("kind") not in
                                {"spend_threshold", "activation", "membership", "other"} or not req.get("note")):
            errs.append(f"{where}: requires must be {{kind: spend_threshold|activation|membership|other, note}}")
        if m and "verified" in m and not isinstance(m["verified"], bool):
            errs.append(f"{where}: match.verified must be true or false")
        check_sources_ref(where, b.get("sources"), sources, errs)
        if b.get("amount") is not None and b.get("unverified") is not True and not any(
                (sources.get(r) or {}).get("kind") in {"issuer", "program"} for r in b.get("sources") or []):
            errs.append(f"{where}: an amount needs the issuer's or program's own page among its sources")
        if b.get("checked_on") is not None and not is_date(b.get("checked_on")):
            errs.append(f"{where}: checked_on must be YYYY-MM-DD")
    for h in d.get("hosts") or []:
        if not HOST.match(str(h)):
            errs.append(f"{w}: host {h!r} must be a plain lowercase host name")
    for key in ("certificates", "thresholds", "upcoming_changes"):
        for i, item in enumerate(d.get(key) or []):
            check_sources_ref(f"{w}: {key}[{i}]", item.get("sources"), sources, errs)
    for i, item in enumerate(d.get("disagreements") or []):
        for j, v in enumerate(item.get("values") or []):
            check_sources_ref(f"{w}: disagreements[{i}].values[{j}]", v.get("sources"), sources, errs)


def check_program(path, d, errs):
    w = path.name
    if d.get("schema") != "finerd-points/program@1":
        errs.append(f"{w}: schema must be finerd-points/program@1")
    if d.get("id") != path.stem:
        errs.append(f"{w}: id must equal the file name")
    if d.get("unit") not in {"points", "miles", "cash"}:
        errs.append(f"{w}: unit must be points, miles or cash")
    if d.get("kind") not in {"hotel", "airline", "bank", "other"}:
        errs.append(f"{w}: kind must be hotel, airline, bank or other")
    sources = d.get("sources") or {}
    if not is_date(d.get("checked_on")) or not d.get("checked_on"):
        errs.append(f"{w}: checked_on must be YYYY-MM-DD")
    for h in d.get("hosts") or []:
        if not HOST.match(str(h)):
            errs.append(f"{w}: host {h!r} must be a plain lowercase host name")
    exp = d.get("expiry")
    if exp is not None:
        check_sources_ref(f"{w}: expiry", exp.get("sources"), sources, errs)
        if exp.get("rule") not in EXPIRY_RULES:
            errs.append(f"{w}: expiry.rule must be one of {sorted(EXPIRY_RULES)}")
        if not any((sources.get(r) or {}).get("kind") in {"issuer", "program"} for r in exp.get("sources") or []):
            errs.append(f"{w}: an expiry rule needs the program's own page among its sources")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Validate the finerd points facts catalog.")
    ap.add_argument("facts_dir", nargs="?", help="folder holding cards/ and programs/ (default: next to this script)")
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    default = next((d for d in (here.parent / "shared" / "facts", here.parent / "facts") if (d / "cards").is_dir()), None)
    root = Path(args.facts_dir) if args.facts_dir else default
    if root is None or not (root / "cards").is_dir():
        print(f"ERROR no facts catalog found at {root}; pass the folder that holds cards/ and programs/")
        sys.exit(1)
    errs = []
    programs = {p.stem for p in (root / "programs").glob("*.json")}
    for p in sorted((root / "programs").glob("*.json")):
        try:
            check_program(p, json.loads(p.read_text()), errs)
        except json.JSONDecodeError as e:
            errs.append(f"{p.name}: invalid JSON: {e}")
    cards = sorted((root / "cards").glob("*.json"))
    for p in cards:
        try:
            check_card(p, json.loads(p.read_text()), programs, errs)
        except json.JSONDecodeError as e:
            errs.append(f"{p.name}: invalid JSON: {e}")
    for e in errs:
        print("ERROR", e)
    if not cards:
        errs.append("no card files found")
    print(f"checked {len(cards)} cards, {len(programs)} programs: {len(errs)} problems")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
