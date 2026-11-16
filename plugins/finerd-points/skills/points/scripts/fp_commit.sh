#!/bin/sh
# finerd points — bin/commit (protocol 1). The only way ledger.json is replaced.
# Spec v2, appendix E. Installed by the skills into <ledger folder>/bin/commit;
# the skills check its hash against their own copy before every use.
#
#   sh bin/commit commit <op_id> <base_hash|none> <base_version> <candidate> <candidate_hash>
#   sh bin/commit check        # take the lock, resolve «planned» journal entries, check the chain
#
# <candidate> is a file name inside work/. Next to it the writer puts <candidate>.meta:
#   protocol=1
#   op_id=<op_id>
#   version=<base_version + 1>
#   hash=<sha256 of the candidate file>
# and, optionally, <candidate>.batch.json (the accepted batch, kept in the journal).
#
# Arguments are generated values checked against fixed patterns; nothing from a page or the
# ledger reaches this command line. The script never deletes a file: a chat may rename and
# replace files in the folder but not delete them, so locks are released by renaming them
# into locks/, and old work files are cleaned up later by Claude Code or Cowork.
#
# Exit codes: 0 done · 10 base changed (another writer published first) · 11 operation already
# applied · 12 bad arguments · 13 candidate does not match its meta · 14 folder busy ·
# 15 backup name taken by a different file · 16 check after publishing failed ·
# 17 protocol mismatch · 18 journal chain broken (show the person).

set -u
umask 077
PROTOCOL=1
DIR=$(cd "$(dirname "$0")/.." && pwd -P) || exit 12
LOCK="$DIR/.lock"
GUARD="$DIR/.lock-guard"
LEDGER="$DIR/ledger.json"
OWN=0
OP=""

say() { printf '%s\n' "$*"; }
fail() { code=$1; shift; say "RESULT=refused CODE=$code REASON=$*"; exit "$code"; }

sha() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
    else sha256sum "$1" | cut -d' ' -f1; fi
}
stamp() { date -u +%Y%m%dT%H%M%SZ; }
epoch() { date -u +%s; }
rand() { od -An -N4 -tx1 /dev/urandom | tr -d ' \n'; }
host() { (hostname 2>/dev/null || uname -n) | tr -cd 'A-Za-z0-9.-' | cut -c1-64; }
val() { sed -n "s/^$2=//p" "$1" | head -n 1; }
jval() { sed -n "s/^  \"$2\": \"*\\([^\",]*\\)\"*,*\$/\\1/p" "$1" | head -n 1; }

is_hex64() { case "$1" in ''|*[!0-9a-f]*) return 1;; esac; [ ${#1} -eq 64 ]; }
is_op() {
    case "$1" in [0-9a-f]*) ;; *) return 1;; esac
    case "$1" in *[!0-9a-f-]*) return 1;; esac
    [ ${#1} -ge 8 ] && [ ${#1} -le 64 ]
}
is_num() { case "$1" in ''|*[!0-9]*|0?*) return 1;; esac; [ ${#1} -le 9 ]; }
is_name() { case "$1" in ''|.*|*[!a-z0-9.-]*) return 1;; esac; [ ${#1} -le 100 ]; }

park() { # rename a lock directory into locks/ (never delete)
    mkdir -p "$DIR/locks" && mv "$1" "$DIR/locks/$2-$(stamp)-$$-$(rand)"
}

release() {
    if [ "$OWN" = 1 ]; then
        OWN=0
        if [ "$(val "$LOCK/owner" pid 2>/dev/null)" = "$$" ]; then
            park "$LOCK" released
        else
            say "NOTE=the folder lock no longer belongs to this commit; left as it is"
        fi
    fi
}
trap release 0
trap 'exit 130' INT TERM HUP

take_stale() { # 0 = a dead owner's lock was parked; the caller retries mkdir
    if [ -d "$GUARD" ] && older_than_2min "$GUARD"; then
        # never released automatically: two writers could each park the other's fresh guard
        say "NOTE=a guard lock left by a crashed commit blocks lock recovery; after the person agrees, run: sh bin/commit release-guard"
        return 1
    fi
    if [ ! -f "$LOCK/owner" ]; then
        # a commit that crashed between creating the lock and writing its owner record
        older_than_2min "$LOCK" || return 1
        mkdir "$GUARD" 2>/dev/null || return 1
        took=1
        if [ -d "$LOCK" ] && [ ! -f "$LOCK/owner" ] && older_than_2min "$LOCK"; then
            park "$LOCK" ownerless && say "NOTE=released a lock without an owner record" && took=0
        fi
        park "$GUARD" guard
        return $took
    fi
    snap=$(cat "$LOCK/owner")
    o_host=$(val "$LOCK/owner" host); o_pid=$(val "$LOCK/owner" pid); o_epoch=$(val "$LOCK/owner" epoch)
    is_num "$o_epoch" || o_epoch=0
    age=$(( $(epoch) - o_epoch ))
    if [ "$o_host" != "$(host)" ] || ! is_num "$o_pid" || ps -p "$o_pid" >/dev/null 2>&1; then
        [ "$age" -gt 600 ] && say "NOTE=the folder has been locked for $age seconds by $o_host pid $o_pid; it is not broken automatically"
        return 1
    fi
    mkdir "$GUARD" 2>/dev/null || return 1
    took=1
    if [ -f "$LOCK/owner" ] && [ "$(cat "$LOCK/owner")" = "$snap" ]; then
        park "$LOCK" stale && say "NOTE=released a lock left by pid $o_pid, which no longer runs" && took=0
    fi
    park "$GUARD" guard
    return $took
}

acquire() {
    i=0
    while :; do
        if mkdir "$LOCK" 2>/dev/null; then
            OWN=1
            printf 'host=%s\npid=%s\nop_id=%s\nepoch=%s\n' "$(host)" "$$" "$OP" "$(epoch)" > "$LOCK/owner.tmp" &&
                mv "$LOCK/owner.tmp" "$LOCK/owner"
            return 0
        fi
        take_stale && continue
        i=$((i + 1))
        [ "$i" -ge "${FP_LOCK_WAIT:-60}" ] && return 1
        sleep 1
    done
}

has_commit() { # the ledger's commits list carries this operation id (JSON escapes quotes inside strings,
    # so the pattern can only match a real "commit_id" key, with any whitespace around the colon)
    # all whitespace removed first: JSON may put spaces or newlines around the colon
    tr -d ' \t\r\n' < "$LEDGER" | grep -qF "\"commit_id\":\"$1\""
}

older_than_2min() { [ -n "$(find "$1" -prune -mmin +2 2>/dev/null)" ]; }

set_state() { # $1 journal file, $2 new state
    sed "s/^  \"state\": \"[a-z]*\"/  \"state\": \"$2\"/" "$1" > "$1.tmp.$$" && mv "$1.tmp.$$" "$1"
}

recover() { # resolve «planned» entries: committed if the ledger carries the op id, else abandoned
    for j in "$DIR"/journal/*.json; do
        [ -f "$j" ] || continue
        case "$j" in *.batch.json) continue;; esac
        [ "$(jval "$j" state)" = planned ] || continue
        jop=$(jval "$j" op_id)
        if [ -f "$LEDGER" ] && has_commit "$jop"; then
            set_state "$j" committed; say "RECOVERED=$jop committed"
        else
            set_state "$j" abandoned; say "RECOVERED=$jop abandoned"
        fi
    done
    sync
}

check_chain() {
    cur=none
    [ -f "$LEDGER" ] && cur=$(sha "$LEDGER")
    for j in "$DIR"/journal/*.json; do
        [ -f "$j" ] || continue
        case "$j" in *.batch.json) continue;; esac
        [ "$(jval "$j" state)" = committed ] || continue
        printf '%s %s %s %s\n' "$(jval "$j" base_version)" "$(jval "$j" base_hash)" "$(jval "$j" new_hash)" "$(jval "$j" op_id)"
    done | sort -n -k1,1 | awk -v cur="$cur" '
        { if (NR > 1) {
              if ($1 == pbv) { print "PROBLEM=two committed operations on version " $1 ": " pop " and " $4; bad = 1 }
              else if ($2 != pnh) { print "PROBLEM=the journal has a gap before operation " $4; bad = 1 } }
          pbv = $1; pnh = $3; pop = $4; n = NR }
        END { if (n > 0 && pnh != cur) { print "PROBLEM=ledger.json is not the last committed version"; bad = 1 }
              if (!bad) print "CHAIN=ok " n + 0
              exit bad }'
}

for x in "$DIR/ledger.json" "$DIR/work" "$DIR/journal" "$DIR/backups" "$DIR/locks" "$DIR/bin" "$DIR/.lock"; do
    [ -L "$x" ] && fail 12 "$(basename "$x") in the ledger folder is a symbolic link; refusing to write through it"
done

cmd=${1:-}
case "$cmd" in
release-guard)
    # only after the person agreed: a guard older than two minutes is left by a crashed commit
    [ -d "$GUARD" ] || { say "RESULT=nothing-to-release"; exit 0; }
    older_than_2min "$GUARD" || fail 14 "the guard lock is recent; a commit may be running"
    park "$GUARD" guard-released && say "RESULT=released"
    exit 0
    ;;
check)
    OP=check
    acquire || fail 14 "the folder is busy"
    recover
    check_chain || exit 18
    say "RESULT=checked"
    exit 0
    ;;
commit)
    [ $# -eq 6 ] || fail 12 "commit needs 5 arguments"
    OP=$2; BH=$3; BV=$4; CAND=$5; CH=$6
    is_op "$OP" || fail 12 "bad operation id"
    { [ "$BH" = none ] || is_hex64 "$BH"; } || fail 12 "bad base hash"
    is_num "$BV" || fail 12 "bad base version"
    is_name "$CAND" || fail 12 "bad candidate name"
    is_hex64 "$CH" || fail 12 "bad candidate hash"
    W="$DIR/work/$CAND"
    [ -f "$W" ] && [ -f "$W.meta" ] || fail 12 "candidate or its meta file is missing in work/"
    { [ -L "$W" ] || [ -L "$W.meta" ] || [ -L "$W.batch.json" ]; } && fail 12 "a candidate file is a symbolic link"
    [ "$(val "$W.meta" protocol)" = "$PROTOCOL" ] || fail 17 "candidate was made for another protocol"
    [ "$(val "$W.meta" op_id)" = "$OP" ] || fail 13 "meta op id differs"
    [ "$(val "$W.meta" version)" = "$((BV + 1))" ] || fail 13 "meta version is not base + 1"
    [ "$(val "$W.meta" hash)" = "$CH" ] || fail 13 "meta hash differs"
    mkdir -p "$DIR/journal" "$DIR/backups" "$DIR/locks"

    acquire || fail 14 "the folder is busy"
    recover

    if [ "$BH" = none ]; then
        [ "$BV" = 0 ] || fail 12 "a first ledger has base version 0"
        [ -e "$LEDGER" ] && fail 10 "a ledger already exists"
    else
        [ -f "$LEDGER" ] || fail 10 "there is no ledger to update"
        cur=$(sha "$LEDGER")
        [ "$cur" = "$BH" ] || fail 10 "BASE_CHANGED current=$cur"
        has_commit "$OP" && fail 11 "operation already in the ledger"
    fi
    [ -e "$DIR/journal/$OP.json" ] && fail 11 "operation already in the journal"
    [ "$(sha "$W")" = "$CH" ] || fail 13 "candidate hash differs"

    [ -n "${FP_TEST_PAUSE:-}" ] && is_num "$FP_TEST_PAUSE" && sleep "$FP_TEST_PAUSE"

    if [ "$BH" != none ]; then
        B="$DIR/backups/ledger.v$BV-$(printf '%s' "$BH" | cut -c1-8).json"
        if [ -e "$B" ]; then
            [ "$(sha "$B")" = "$BH" ] || fail 15 "backup $B exists with other content"
        else
            cp "$LEDGER" "$B.tmp.$$" && mv "$B.tmp.$$" "$B" || fail 15 "could not write the backup"
            [ "$(sha "$B")" = "$BH" ] || fail 15 "backup does not match the base"
        fi
    fi

    J="$DIR/journal/$OP.json"
    if [ -f "$W.batch.json" ]; then
        cp "$W.batch.json" "$DIR/journal/$OP.batch.json.tmp.$$" && mv -f "$DIR/journal/$OP.batch.json.tmp.$$" "$DIR/journal/$OP.batch.json"
    fi
    printf '{\n  "protocol": %s,\n  "op_id": "%s",\n  "base_version": %s,\n  "base_hash": "%s",\n  "new_version": %s,\n  "new_hash": "%s",\n  "candidate": "work/%s",\n  "at": "%s",\n  "host": "%s",\n  "state": "planned"\n}\n' \
        "$PROTOCOL" "$OP" "$BV" "$BH" "$((BV + 1))" "$CH" "$CAND" "$(stamp)" "$(host)" > "$J.tmp.$$" &&
        mv "$J.tmp.$$" "$J" || fail 16 "could not write the journal entry"
    sync

    mv -f "$W" "$LEDGER" || fail 16 "could not publish the candidate"
    sync
    new=$(sha "$LEDGER")
    [ "$new" = "$CH" ] || fail 16 "ledger.json does not match the candidate after publishing"
    set_state "$J" committed
    sync
    say "RESULT=committed VERSION=$((BV + 1)) HASH=$new"
    exit 0
    ;;
*)
    fail 12 "usage: commit <op_id> <base_hash|none> <base_version> <candidate> <candidate_hash> | check"
    ;;
esac
