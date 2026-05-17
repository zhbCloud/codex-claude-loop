from __future__ import annotations

import sys
import tempfile
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.io_utils import read_json, write_json
from codex_claude_loop_runtime.sessions import acquire_session, commit_session, release_session


def acquire(root: Path, session_key: str, run_id: str):
    return acquire_session(
        root,
        session_key,
        "PrimaryReuse",
        run_id,
        "fingerprint",
        3,
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


if __name__ == "__main__":
    test_uncommitted_session_is_not_reused()
    test_committed_session_is_reused()
    test_legacy_unvalidated_session_is_ignored()
    print("ok")
