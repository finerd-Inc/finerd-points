"""Ledger folder and bin/commit (spec v2, appendix E): python3 -m unittest discover -s tests"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "lib"))
import fpledger as fl  # noqa: E402
import fpstore as st  # noqa: E402


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Folder:
    """A fresh ledger folder whose path has a space in it, like the default «~/finerd points»."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name, "finerd points").resolve()
        st.install(self.root)
        return self.root

    def __exit__(self, *exc):
        self.tmp.cleanup()


def first_ledger(root):
    led = fl.new_ledger("Test", storage="folder")
    res = st.create(root, led)
    assert res["result"] == "committed", res
    return led


def card(i):
    return [{"op": "add_card", "id": f"c{i}", "person": "me", "nickname": f"Card {i}"}]


def sh(root, *args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(["/bin/sh", str(root / "bin" / "commit"), *args], capture_output=True, text=True, env=e)
    return p.returncode, st.parse_output(p.stdout)


class CommitScript(unittest.TestCase):

    def test_first_ledger_and_update(self):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            self.assertEqual((bv, led["schema_version"]), (1, 2))
            self.assertEqual(led["commits"][0]["base_version"], 0)
            b = card(1)
            h, _ = st.preview(root, b)
            res = st.apply_and_publish(root, b, h)
            self.assertEqual(res["result"], "committed", res)
            led2, bh2, bv2 = st.read(root)
            self.assertEqual(bv2, 2)
            self.assertEqual([c["id"] for c in led2["cards"]], ["c1"])
            backup = root / "backups" / f"ledger.v1-{bh[:8]}.json"
            self.assertEqual(sha_file(backup), bh)
            self.assertEqual(st.check(root)["chain"], "ok 2")

    def test_second_first_ledger_refused(self):
        with Folder() as root:
            first_ledger(root)
            res = st.create(root, fl.new_ledger("Other", storage="folder"))
            self.assertEqual((res["result"], res["code"]), ("refused", "10"))

    def test_stale_base_refused_and_duplicate_op_refused(self):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            fl.apply_batch(led, card(1), fl.preview_batch(led, card(1))[0])
            res = st.publish(root, led, bh, bv, op_id="0123abcd-0001")
            self.assertEqual(res["result"], "committed")
            old, _, _ = st.read(root)
            # a second writer that still holds the old base
            led_b = json.loads(json.dumps(old))
            res2 = st.publish(root, led_b, bh, bv)
            self.assertEqual((res2["result"], res2["code"]), ("refused", "10"))
            # the same operation id again: Python refuses it, and so does the script on its own
            cur, ch, cv = st.read(root)
            with self.assertRaises(fl.LedgerError):
                st.publish(root, cur, ch, cv, op_id="0123abcd-0001")
            cand = json.loads(json.dumps(cur))
            cand["version"] = cv + 1
            data = st.serialize(cand)
            h = hashlib.sha256(data).hexdigest()
            (root / "work" / "dup.json").write_bytes(data)
            (root / "work" / "dup.json.meta").write_text(f"protocol=1\nop_id=0123abcd-0001\nversion={cv + 1}\nhash={h}\n")
            code, out = sh(root, "commit", "0123abcd-0001", ch, str(cv), "dup.json", h)
            self.assertEqual(code, 11, out)

    def test_bad_arguments_refused(self):
        with Folder() as root:
            first_ledger(root)
            good = "a" * 64
            cases = [
                ("ABCDEF12", good, "1", "cand.json", good),           # upper case op id
                ("abcdef12\nx", good, "1", "cand.json", good),        # newline
                ("abcdef12", "zz", "1", "cand.json", good),            # base hash
                ("abcdef12", good, "01", "cand.json", good),           # leading zero
                ("abcdef12", good, "1", "../ledger.json", good),       # path out of work/
                ("abcdef12", good, "1", ".hidden", good),              # hidden name
                ("abcdef12", good, "1", "cand.json", "x;rm -rf ~"),    # shell text
            ]
            for args in cases:
                code, out = sh(root, "commit", *args)
                self.assertEqual(code, 12, (args, out))
            code, _ = sh(root, "commit", "abcdef12")
            self.assertEqual(code, 12)

    def test_meta_must_match(self):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            op = st.new_op_id()
            cand = st.prepare_candidate(led, bv, op, "test")
            name, h = st.stage(root, cand, bv, op)
            code, out = sh(root, "commit", op, bh, str(bv), name, "b" * 64)
            self.assertEqual(code, 13, out)
            self.assertEqual(sha_file(root / "ledger.json"), bh)

    def test_changed_script_is_refused_then_reinstalled(self):
        with Folder() as root:
            first_ledger(root)
            with open(root / "bin" / "commit", "a") as f:
                f.write("\n# changed\n")
            led, bh, bv = st.read(root)
            with self.assertRaises(st.StoreError):
                st.publish(root, led, bh, bv)
            self.assertTrue(st.install_script(root))
            led, bh, bv = st.read(root)
            self.assertEqual(st.publish(root, led, bh, bv)["result"], "committed")

    def test_big_ledger(self):
        with Folder() as root:
            led = fl.new_ledger("Big", storage="folder")
            led["records"] = [{"id": f"r{i}", "text": "x" * 200} for i in range(30000)]  # about 7 MB
            res = st.create(root, led)
            self.assertEqual(res["result"], "committed", res)
            self.assertGreater((root / "ledger.json").stat().st_size, 6_000_000)
            self.assertEqual(st.read(root)[0]["records"][-1]["id"], "r29999")


class Races(unittest.TestCase):
    """Two writers on the same base: one wins, the other is refused and loses nothing."""

    def _race(self, pause_first):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            a = json.loads(json.dumps(led))
            b = json.loads(json.dumps(led))
            fl.apply_batch(a, card("a"), fl.preview_batch(a, card("a"))[0])
            fl.apply_batch(b, card("b"), fl.preview_batch(b, card("b"))[0])
            results = {}

            def run(name, l, env):
                results[name] = st.publish(root, l, bh, bv, writer=name, env=env)

            t1 = threading.Thread(target=run, args=("first", a, {"FP_TEST_PAUSE": "2"} if pause_first else {}))
            t1.start()
            time.sleep(0.5)
            t2 = threading.Thread(target=run, args=("second", b, {}))
            t2.start()
            t1.join()
            t2.join()
            states = sorted((r["result"], r.get("code")) for r in results.values())
            self.assertEqual(states, [("committed", None), ("refused", "10")], results)
            winner = "first" if results["first"]["result"] == "committed" else "second"
            final, _, fv = st.read(root)
            self.assertEqual(fv, 2)
            self.assertEqual([c["id"] for c in final["cards"]], ["ca" if winner == "first" else "cb"])
            self.assertEqual(st.check(root)["chain"], "ok 2")
            # the loser's batch is still in its work file, and it can re-apply on the new base
            loser = b if winner == "first" else a
            lb = card("b") if winner == "first" else card("a")
            h, _ = st.preview(root, lb)
            res = st.apply_and_publish(root, lb, h)
            self.assertEqual(res["result"], "committed")
            self.assertEqual(sorted(c["id"] for c in st.read(root)[0]["cards"]), ["ca", "cb"])
            del loser

    def test_pause_between_check_and_rename(self):
        self._race(pause_first=True)

    def test_plain_race(self):
        self._race(pause_first=False)

    def test_refused_commit_reapplies_when_nothing_conflicts(self):
        with Folder() as root:
            first_ledger(root)
            mine = card("mine")
            h, _ = st.preview(root, mine)
            # someone else publishes first
            other, obh, obv = st.read(root)
            fl.apply_batch(other, card("other"), fl.preview_batch(other, card("other"))[0])
            self.assertEqual(st.publish(root, other, obh, obv)["result"], "committed")
            # my previewed batch was made on version 1; it reads the same on version 2, so it goes through
            res = st.apply_and_publish(root, mine, h)
            self.assertEqual(res["result"], "committed", res)
            self.assertEqual(sorted(c["id"] for c in st.read(root)[0]["cards"]), ["cmine", "cother"])

    def test_unseen_batch_is_refused(self):
        with Folder() as root:
            first_ledger(root)
            led, _, _ = st.read(root)
            h, _ = fl.preview_batch(led, card(1))  # computed, but never shown through st.preview
            with self.assertRaises(st.StoreError):
                st.apply_and_publish(root, card(1), h)

    def test_conflicting_batch_needs_a_new_preview(self):
        with Folder() as root:
            first_ledger(root)
            h, _ = st.preview(root, card("x"))
            other, obh, obv = st.read(root)
            fl.apply_batch(other, card("x"), fl.preview_batch(other, card("x"))[0])
            st.publish(root, other, obh, obv)
            with self.assertRaises(fl.LedgerError):  # «cx already exists»: the batch no longer applies
                st.apply_and_publish(root, card("x"), h)


class Recovery(unittest.TestCase):

    def _planned(self, root, publish_too):
        """Simulate a crash after the journal entry was written (and, optionally, after the rename)."""
        led, bh, bv = st.read(root)
        op = st.new_op_id()
        cand = st.prepare_candidate(led, bv, op, "crashed")
        name, h = st.stage(root, cand, bv, op)
        j = root / "journal" / f"{op}.json"
        j.write_text('{\n  "protocol": 1,\n  "op_id": "%s",\n  "base_version": %d,\n  "base_hash": "%s",\n'
                     '  "new_version": %d,\n  "new_hash": "%s",\n  "candidate": "work/%s",\n  "at": "x",\n'
                     '  "host": "x",\n  "state": "planned"\n}\n' % (op, bv, bh, bv + 1, h, name))
        if publish_too:
            os.replace(root / "work" / name, root / "ledger.json")
        return op

    def test_crash_after_rename_counts_as_committed(self):
        with Folder() as root:
            first_ledger(root)
            op = self._planned(root, publish_too=True)
            res = st.check(root)
            self.assertIn(f"{op} committed", res["recovered"])
            self.assertEqual(res["chain"], "ok 2")

    def test_crash_before_rename_is_abandoned(self):
        with Folder() as root:
            first_ledger(root)
            op = self._planned(root, publish_too=False)
            res = st.check(root)
            self.assertIn(f"{op} abandoned", res["recovered"])
            self.assertEqual(res["chain"], "ok 1")
            led, bh, bv = st.read(root)
            self.assertEqual(st.publish(root, led, bh, bv)["result"], "committed")  # abandoned never blocks

    def test_chain_gap_is_reported(self):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            st.publish(root, led, bh, bv)
            # something outside the protocol replaced the ledger
            led, _, _ = st.read(root)
            led["cards"].append({"id": "sneaky", "person": "me", "nickname": "x"})
            (root / "ledger.json").write_bytes(st.serialize(led))
            res = st.check(root)
            self.assertEqual(res["exit"], 18)
            self.assertTrue(res["problems"])


class Locks(unittest.TestCase):

    def test_lock_of_a_dead_process_is_released(self):
        with Folder() as root:
            first_ledger(root)
            p = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
            p.wait()
            lock = root / ".lock"
            lock.mkdir()
            host = subprocess.run(["/bin/sh", "-c", "(hostname 2>/dev/null || uname -n) | tr -cd 'A-Za-z0-9.-' | cut -c1-64"],
                                  capture_output=True, text=True).stdout
            (lock / "owner").write_text(f"host={host}\npid={p.pid}\nop_id=dead\nepoch={int(time.time())}\n")
            led, bh, bv = st.read(root)
            res = st.publish(root, led, bh, bv)
            self.assertEqual(res["result"], "committed", res)
            self.assertTrue(any("no longer runs" in n for n in res["notes"]))
            self.assertFalse(lock.exists())

    def test_lock_of_a_live_process_waits_then_reports_busy(self):
        with Folder() as root:
            first_ledger(root)
            lock = root / ".lock"
            lock.mkdir()
            host = subprocess.run(["/bin/sh", "-c", "(hostname 2>/dev/null || uname -n) | tr -cd 'A-Za-z0-9.-' | cut -c1-64"],
                                  capture_output=True, text=True).stdout
            (lock / "owner").write_text(f"host={host}\npid={os.getpid()}\nop_id=live\nepoch={int(time.time())}\n")
            led, bh, bv = st.read(root)
            res = st.publish(root, led, bh, bv, env={"FP_LOCK_WAIT": "2"})
            self.assertEqual((res["result"], res["code"]), ("refused", "14"))
            self.assertTrue(lock.exists())  # never broken while its owner runs

    def test_nothing_is_deleted_by_the_script(self):
        with Folder() as root:
            first_ledger(root)
            for i in range(3):
                led, bh, bv = st.read(root)
                st.publish(root, led, bh, bv)
            released = list((root / "locks").iterdir())
            self.assertEqual(len(released), 4)  # every lock was parked, not removed
            self.assertEqual(len(list((root / "backups").iterdir())), 3)


class FolderChoice(unittest.TestCase):

    def test_refuses_home_synced_and_busy_folders(self):
        with self.assertRaises(st.StoreError):
            st.check_folder(Path.home())
        with self.assertRaises(st.StoreError):
            st.check_folder(Path.home() / "Library" / "CloudStorage" / "GoogleDrive-x" / "My Drive" / "points")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "notes.txt").write_text("x")
            with self.assertRaises(st.StoreError):
                st.check_folder(d)

    def test_cleanup_removes_old_work_and_released_locks(self):
        with Folder() as root:
            first_ledger(root)
            led, bh, bv = st.read(root)
            st.publish(root, led, bh, bv)
            old = time.time() - 40 * 86400
            for p in (root / "work").iterdir():
                os.utime(p, (old, old))
            removed = st.cleanup(root)
            self.assertTrue(any(r.startswith("locks/") for r in removed))
            self.assertTrue(any(r.startswith("work/") for r in removed))
            self.assertEqual(st.check(root)["chain"], "ok 2")


if __name__ == "__main__":
    unittest.main()


class ChatPath(unittest.TestCase):
    """A chat works on a copy of ledger.json and publishes through the same bin/commit on the computer."""

    def _cli(self, *args):
        p = subprocess.run([sys.executable, str(ROOT / "shared" / "lib" / "ledger.py"), *args], capture_output=True,
                           text=True)
        return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout)

    def _chat_commit(self, root, sandbox, batch_rows):
        copy = sandbox / "ledger.json"
        copy.write_bytes((root / "ledger.json").read_bytes())          # device_stage_files
        bh = sha_file(root / "ledger.json")                           # device_bash: shasum -a 256 ledger.json
        batch = sandbox / "batch.json"
        batch.write_text(json.dumps(batch_rows))
        code, prev = self._cli("preview", "--ledger", str(copy), "--batch", str(batch), "--save",
                               str(sandbox / "seen.json"), "--json")
        self.assertEqual(code, 0, prev)
        return copy, bh, batch, prev["hash"]

    def _deliver_and_run(self, root, sandbox, copy, bh, batch, h):
        outbox = sandbox / "outbox"
        code, prep = self._cli("chat-prepare", "--ledger", str(copy), "--base-hash", bh, "--batch", str(batch),
                               "--confirm", h, "--seen", str(sandbox / "seen.json"), "--out", str(outbox))
        self.assertEqual((code, prep["result"]), (0, "prepared"), prep)
        for name in prep["deliver_into_work"]:                         # device_commit_files, new names only
            dst = root / "work" / name
            self.assertFalse(dst.exists())
            dst.write_bytes((outbox / name).read_bytes())
        return sh(root, *prep["commit_args"])                          # device_bash

    def test_chat_publishes_through_bin_commit(self):
        with Folder() as root, tempfile.TemporaryDirectory() as sb:
            first_ledger(root)
            sandbox = Path(sb)
            copy, bh, batch, h = self._chat_commit(root, sandbox, card("chat"))
            code, out = self._deliver_and_run(root, sandbox, copy, bh, batch, h)
            self.assertEqual((code, out["result"]), (0, "committed"), out)
            led, _, bv = st.read(root)
            self.assertEqual((bv, [c["id"] for c in led["cards"]]), (2, ["cchat"]))
            self.assertEqual(led["commits"][-1]["writer"], "chat")

    def test_local_write_after_chat_read_refuses_the_chat(self):
        with Folder() as root, tempfile.TemporaryDirectory() as sb:
            first_ledger(root)
            sandbox = Path(sb)
            copy, bh, batch, h = self._chat_commit(root, sandbox, card("chat"))
            led, lbh, lbv = st.read(root)                              # Claude Code writes meanwhile
            fl.apply_batch(led, card("local"), fl.preview_batch(led, card("local"))[0])
            self.assertEqual(st.publish(root, led, lbh, lbv)["result"], "committed")
            code, out = self._deliver_and_run(root, sandbox, copy, bh, batch, h)
            self.assertEqual(code, 10, out)
            # the chat brings the new ledger in and publishes the same batch, which still reads the same
            copy.write_bytes((root / "ledger.json").read_bytes())
            code, out = self._deliver_and_run(root, sandbox, copy, sha_file(root / "ledger.json"), batch, h)
            self.assertEqual((code, out["result"]), (0, "committed"), out)
            self.assertEqual(sorted(c["id"] for c in st.read(root)[0]["cards"]), ["cchat", "clocal"])
            self.assertEqual(st.check(root)["chain"], "ok 3")

    def test_chat_write_after_local_read_refuses_the_local_writer(self):
        with Folder() as root, tempfile.TemporaryDirectory() as sb:
            first_ledger(root)
            led, lbh, lbv = st.read(root)                              # Claude Code reads first
            sandbox = Path(sb)
            copy, bh, batch, h = self._chat_commit(root, sandbox, card("chat"))
            code, out = self._deliver_and_run(root, sandbox, copy, bh, batch, h)
            self.assertEqual(code, 0, out)
            fl.apply_batch(led, card("local"), fl.preview_batch(led, card("local"))[0])
            res = st.publish(root, led, lbh, lbv)
            self.assertEqual((res["result"], res["code"]), ("refused", "10"))


class HouseholdRemoval(unittest.TestCase):

    def test_member_removed_everywhere_and_never_replayed(self):
        import fpcollect as fc
        with Folder() as root:
            first_ledger(root)
            add = [{"op": "add_person", "id": "anna", "name": "Anna", "consent": {"given": True, "on": "2026-11-16"}},
                   {"op": "add_source", "id": "aw", "kind": "aggregator", "name": "AwardWallet",
                    "accounts": [{"id": "anna-hy", "label": "Anna Hyatt", "person": "anna"},
                                 {"id": "me-hy", "label": "My Hyatt", "person": "me"}]}]
            h, _ = st.preview(root, add)
            self.assertEqual(st.apply_and_publish(root, add, h)["result"], "committed")
            led, _, _ = st.read(root)
            rd = {"source": "aw", "account": "anna-hy", "section": "activity", "read_id": "r1",
                  "requested": ["2026-01-01", "2026-11-16"], "covered": None, "state": "partial",
                  "read_at": "2026-11-16T00:00:00Z", "unit": "points",
                  "rows": [{"date": "2026-05-01", "amount": 777, "description": "Anna stay", "status": "posted"}]}
            batch, _ = fc.plan_read(led, rd)
            h, _ = st.preview(root, batch)
            self.assertEqual(st.apply_and_publish(root, batch, h)["result"], "committed")
            (root / "work" / "batch-old.json").write_text(json.dumps(batch))
            led, _, _ = st.read(root)
            hh, plan, text = fl.redaction_plan(led, "anna")
            self.assertEqual(plan["records"], [led["records"][0]["id"]])
            for _ in range(2):  # the publish helper retries once if needed
                led, bh, bv = st.read(root)
                fl.redact_person(led, "anna", hh)
                if st.publish(root, led, bh, bv)["result"] == "committed":
                    break
            changed = st.scrub_pending_redactions(root)
            self.assertIn("work/batch-old.json", changed)
            for p in list((root / "backups").glob("*.json")) + list((root / "journal").glob("*.batch.json")):
                self.assertNotIn("Anna", p.read_text(), p.name)
            led, _, _ = st.read(root)
            self.assertEqual(led["records"], [])
            self.assertEqual([a["id"] for a in led["sources"][0]["accounts"]], ["me-hy"])
            self.assertTrue(led["_meta"]["redactions"][-1]["files_scrubbed"])
            with self.assertRaises(fl.LedgerError):  # an old batch can never bring her data back
                fl.preview_batch(led, [{"op": "add_person", "id": "anna", "name": "Anna",
                                        "consent": {"given": True, "on": "2026-11-17"}}])
