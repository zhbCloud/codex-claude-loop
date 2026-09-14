from __future__ import annotations

import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime import sessions
from codex_claude_loop_runtime.common import DelegateError
from codex_claude_loop_runtime.io_utils import read_json, write_json
from codex_claude_loop_runtime.sessions import AtomicLock, acquire_session, commit_session, release_session


def acquire(root: Path, session_key: str, run_id: str, *, mode: str = "PrimaryReuse", max_parallel: int = 3):
    return acquire_session(
        root,
        session_key,
        mode,
        run_id,
        "fingerprint",
        max_parallel,
        7200,
        1,
    )


def test_uncommitted_session_is_not_reused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lease = acquire(root, "case", "run-1")
        assert lease.resume is False
        state = read_json(root / "case.json")
        assert state["primary"]["sessionId"] is None
        assert state["primary"]["pendingSessionId"] == lease.session_id

        release_session(lease, "fingerprint", 7200)
        state = read_json(root / "case.json")
        assert state["primary"]["sessionId"] is None
        assert state["primary"]["pendingSessionId"] is None

        next_lease = acquire(root, "case", "run-2")
        assert next_lease.resume is False
        assert next_lease.session_id != lease.session_id
        release_session(next_lease, "fingerprint", 7200)


def test_committed_session_is_reused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lease = acquire(root, "case", "run-1")
        commit_session(lease, "fingerprint", 7200)
        release_session(lease, "fingerprint", 7200)

        state = read_json(root / "case.json")
        assert state["primary"]["sessionId"] == lease.session_id
        assert state["primary"]["validatedAt"]

        next_lease = acquire(root, "case", "run-2")
        assert next_lease.resume is True
        assert next_lease.session_id == lease.session_id
        release_session(next_lease, "fingerprint", 7200)


def test_legacy_unvalidated_session_is_ignored() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(
            root / "case.json",
            {
                "version": 1,
                "sessionKey": "case",
                "primary": {
                    "sessionId": "legacy-session",
                    "status": "available",
                    "leaseRunId": None,
                    "leasedAt": None,
                    "lastUsedAt": None,
                    "lastRunId": None,
                },
                "parallelPool": [],
            },
        )

        lease = acquire(root, "case", "run-1")
        assert lease.resume is False
        assert lease.session_id != "legacy-session"
        state = read_json(root / "case.json")
        assert state["primary"]["sessionId"] is None
        release_session(lease, "fingerprint", 7200)


def test_active_primary_cannot_be_reclaimed_after_ttl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = acquire(root, "case", "run-1")
        commit_session(first, "fingerprint", 7200)
        release_session(first, "fingerprint", 7200)
        active = acquire(root, "case", "run-2")
        try:
            assert active.resume
            before = read_json(root / "case.json")
            with patch.object(sessions.time, "time", return_value=time.time() + 7201):
                try:
                    acquire(root, "case", "run-3")
                except DelegateError:
                    pass
                else:
                    raise AssertionError("TTL must not reclaim a live owner's session")
            assert read_json(root / "case.json") == before
        finally:
            release_session(active, "fingerprint", 7200)


def test_pool_skips_active_expired_slots_without_changing_owners() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        active = acquire(root, "case", "run-1", mode="ParallelPool", max_parallel=2)
        other = acquire(root, "case", "run-2", mode="ParallelPool", max_parallel=2)
        replacement = None
        try:
            commit_session(active, "fingerprint", 7200)
            commit_session(other, "fingerprint", 7200)
            before = read_json(root / "case.json")
            with patch.object(sessions.time, "time", return_value=time.time() + 7201):
                try:
                    acquire(root, "case", "run-3", mode="ParallelPool", max_parallel=2)
                except DelegateError:
                    pass
                else:
                    raise AssertionError("expired but live pool slots must remain unavailable")
                assert read_json(root / "case.json") == before
                release_session(other, "fingerprint", 7200)
                replacement = acquire(root, "case", "run-3", mode="ParallelPool", max_parallel=2)
                assert replacement.slot_name == other.slot_name
                assert replacement.session_id == other.session_id
                assert replacement.resume
                state = read_json(root / "case.json")
                assert state["parallelPool"][0]["leaseRunId"] == active.run_id
        finally:
            if replacement is not None:
                release_session(replacement, "fingerprint", 7200)
            release_session(other, "fingerprint", 7200)
            release_session(active, "fingerprint", 7200)


def test_atomic_lock_ttl_cannot_steal_live_lock() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "case.lock"
        with AtomicLock(path, 1, 0):
            os.utime(path, (0, 0))
            try:
                with AtomicLock(path, 1, 0):
                    raise AssertionError("an old mtime must not allow stealing a live OS lock")
            except DelegateError:
                pass
        assert path.exists()
        with AtomicLock(path, 1, 0):
            pass


def test_failed_acquire_does_not_leak_activity_lock() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch.object(sessions, "write_json", side_effect=OSError("write failed")):
            try:
                acquire(root, "case", "failed")
            except OSError:
                pass
            else:
                raise AssertionError("session write error must propagate")
        lease = acquire(root, "case", "next")
        release_session(lease, "fingerprint", 7200)


def test_old_owner_cannot_commit_or_release_replacement() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = acquire(root, "case", "old")
        commit_session(old, "fingerprint", 7200)
        old.activity_lock.close()
        replacement = None
        try:
            with patch.object(sessions.time, "time", return_value=time.time() + 7201):
                replacement = acquire(root, "case", "new")
            before = read_json(root / "case.json")["primary"]
            commit_session(old, "old-fingerprint", 7200)
            release_session(old, "old-fingerprint", 7200)
            assert read_json(root / "case.json")["primary"] == before
            assert before["leaseRunId"] == replacement.run_id
        finally:
            release_session(old, "fingerprint", 7200)
            if replacement is not None:
                release_session(replacement, "fingerprint", 7200)


def _acquire_then_exit(root: str, connection) -> None:
    lease = acquire(Path(root), "case", "crashed-owner")
    commit_session(lease, "fingerprint", 7200)
    connection.send(lease.session_id)
    connection.close()
    os._exit(0)


def test_crashed_owner_releases_os_lock_but_preserves_metadata_ttl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_acquire_then_exit, args=(str(root), sender))
        process.start()
        sender.close()
        replacement = None
        try:
            assert receiver.poll(10), "test owner did not acquire its session"
            session_id = receiver.recv()
            process.join(timeout=10)
            assert process.exitcode == 0
            try:
                acquire(root, "case", "too-soon")
            except DelegateError:
                pass
            else:
                raise AssertionError("existing metadata TTL must remain in effect after a crash")
            with patch.object(sessions.time, "time", return_value=time.time() + 7201):
                replacement = acquire(root, "case", "recovered")
            assert replacement.resume
            assert replacement.session_id == session_id
        finally:
            receiver.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
            process.close()
            if replacement is not None:
                release_session(replacement, "fingerprint", 7200)


if __name__ == "__main__":
    test_uncommitted_session_is_not_reused()
    test_committed_session_is_reused()
    test_legacy_unvalidated_session_is_ignored()
    test_active_primary_cannot_be_reclaimed_after_ttl()
    test_pool_skips_active_expired_slots_without_changing_owners()
    test_atomic_lock_ttl_cannot_steal_live_lock()
    test_failed_acquire_does_not_leak_activity_lock()
    test_old_owner_cannot_commit_or_release_replacement()
    test_crashed_owner_releases_os_lock_but_preserves_metadata_ttl()
    print("ok")
