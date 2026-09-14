from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import DelegateError, now_iso
from .io_utils import file_lock, read_json, write_json


@dataclass
class SessionLease:
    session_key: str
    session_mode: str
    session_id: str
    resume: bool
    slot_name: str
    state_path: Path
    lock_path: Path
    run_id: str
    activity_lock: contextlib.ExitStack


class AtomicLock:
    def __init__(self, path: Path, ttl_seconds: int, wait_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.wait_seconds = wait_seconds
        self.acquired = False
        self._context: contextlib.AbstractContextManager[None] | None = None

    def __enter__(self) -> "AtomicLock":
        self._context = file_lock(self.path, timeout_seconds=self.wait_seconds)
        try:
            self._context.__enter__()
        except TimeoutError as exc:
            raise DelegateError(f"Timed out waiting for session lock: {self.path}") from exc
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.acquired and self._context is not None:
            self.acquired = False
            self._context.__exit__(exc_type, exc, tb)


def _hold_activity_lock(stack: contextlib.ExitStack, state_root: Path, session_key: str, slot_name: str) -> bool:
    path = state_root / f"{session_key}.{slot_name}.active.lock"
    try:
        stack.enter_context(file_lock(path, timeout_seconds=0))
    except TimeoutError:
        return False
    return True


def _new_state(session_key: str) -> dict[str, Any]:
    return {
        "version": 1,
        "sessionKey": session_key,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "primary": {
            "sessionId": None,
            "pendingSessionId": None,
            "status": "available",
            "leaseRunId": None,
            "leasedAt": None,
            "lastUsedAt": None,
            "lastRunId": None,
            "validatedAt": None,
        },
        "parallelPool": [],
    }


def _read_state(path: Path, session_key: str) -> dict[str, Any]:
    if not path.exists():
        return _new_state(session_key)
    state = read_json(path)
    state.setdefault("primary", _new_state(session_key)["primary"])
    state.setdefault("parallelPool", [])
    return state


def _leased(slot: dict[str, Any], ttl_seconds: int) -> bool:
    if slot.get("status") != "leased":
        return False
    leased_at = slot.get("leasedAt")
    if not leased_at:
        return False
    if ttl_seconds <= 0:
        return True
    try:
        from datetime import datetime

        ts = datetime.fromisoformat(str(leased_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return time.time() - ts <= ttl_seconds


def acquire_session(
    state_root: Path,
    session_key: str,
    session_mode: str,
    run_id: str,
    fingerprint: str,
    max_parallel: int,
    lease_ttl_seconds: int,
    lease_wait_seconds: int,
) -> SessionLease:
    state_path = state_root / f"{session_key}.json"
    lock_path = state_root / f"{session_key}.lock"
    with AtomicLock(lock_path, lease_ttl_seconds, lease_wait_seconds), contextlib.ExitStack() as activity_lock:
        state = _read_state(state_path, session_key)
        state["updatedAt"] = now_iso()
        if session_mode in {"PrimaryReuse", "PrimaryAnchor"}:
            slot = state["primary"]
            if _leased(slot, lease_ttl_seconds) or not _hold_activity_lock(activity_lock, state_root, session_key, "primary"):
                raise DelegateError(f"Primary Claude session is already leased for SessionKey={session_key}")
            resume = bool(slot.get("sessionId") and slot.get("validatedAt"))
            session_id = str(slot["sessionId"]) if resume else str(uuid.uuid4())
            if not resume:
                slot["sessionId"] = None
                slot["pendingSessionId"] = session_id
            slot.update({"status": "leased", "leaseRunId": run_id, "leasedAt": now_iso()})
            write_json(state_path, state)
            return SessionLease(session_key, session_mode, session_id, resume, "primary", state_path, lock_path, run_id, activity_lock.pop_all())

        pool = state["parallelPool"]
        max_parallel = max(1, max_parallel)
        candidates: list[tuple[int, dict[str, Any], bool]] = []
        for index, slot in enumerate(pool):
            if not _leased(slot, lease_ttl_seconds):
                candidates.append((index, slot, slot.get("lastTaskFingerprint") == fingerprint))
        candidates.sort(key=lambda item: (0 if item[2] else 1, item[1].get("lastUsedAt") or ""))
        selected: tuple[int, dict[str, Any]] | None = None
        for index, slot, _ in candidates:
            if _hold_activity_lock(activity_lock, state_root, session_key, f"parallel-{index}"):
                selected = (index, slot)
                break
        if selected is None and len(pool) < max_parallel:
            index = len(pool)
            if not _hold_activity_lock(activity_lock, state_root, session_key, f"parallel-{index}"):
                raise DelegateError(f"No available ParallelPool slots for SessionKey={session_key}; maxParallel={max_parallel}")
            slot = {
                "sessionId": None,
                "pendingSessionId": None,
                "status": "available",
                "leaseRunId": None,
                "leasedAt": None,
                "lastUsedAt": None,
                "lastRunId": None,
                "validatedAt": None,
                "lastTaskFingerprint": fingerprint,
            }
            pool.append(slot)
            selected = (index, slot)
        if selected is None:
            raise DelegateError(f"No available ParallelPool slots for SessionKey={session_key}; maxParallel={max_parallel}")
        index, slot = selected
        resume = bool(slot.get("sessionId") and slot.get("validatedAt"))
        session_id = str(slot["sessionId"]) if resume else str(uuid.uuid4())
        if not resume:
            slot["sessionId"] = None
            slot["pendingSessionId"] = session_id
        slot.update(
            {
                "status": "leased",
                "leaseRunId": run_id,
                "leasedAt": now_iso(),
                "lastTaskFingerprint": fingerprint,
            }
        )
        write_json(state_path, state)
        return SessionLease(session_key, session_mode, session_id, resume, f"parallel-{index}", state_path, lock_path, run_id, activity_lock.pop_all())


def commit_session(lease: SessionLease, fingerprint: str, lease_ttl_seconds: int) -> None:
    with AtomicLock(lease.lock_path, lease_ttl_seconds, 30):
        state = _read_state(lease.state_path, lease.session_key)
        now = now_iso()
        if lease.slot_name == "primary":
            slot = state["primary"]
            if slot.get("leaseRunId") != lease.run_id:
                return
        else:
            index = int(lease.slot_name.split("-", 1)[1])
            if index < 0 or index >= len(state["parallelPool"]):
                return
            slot = state["parallelPool"][index]
            if slot.get("leaseRunId") != lease.run_id:
                return
            slot["lastTaskFingerprint"] = fingerprint

        slot["sessionId"] = lease.session_id
        slot["pendingSessionId"] = None
        slot["validatedAt"] = now
        state["updatedAt"] = now
        write_json(lease.state_path, state)


def release_session(lease: SessionLease, fingerprint: str, lease_ttl_seconds: int) -> None:
    with lease.activity_lock, contextlib.suppress(Exception):
        with AtomicLock(lease.lock_path, lease_ttl_seconds, 30):
            state = _read_state(lease.state_path, lease.session_key)
            now = now_iso()
            if lease.slot_name == "primary":
                slot = state["primary"]
                if slot.get("leaseRunId") == lease.run_id:
                    if slot.get("pendingSessionId") == lease.session_id:
                        slot["pendingSessionId"] = None
                    slot.update({"status": "available", "leaseRunId": None, "leasedAt": None, "lastUsedAt": now, "lastRunId": lease.run_id})
            else:
                index = int(lease.slot_name.split("-", 1)[1])
                if 0 <= index < len(state["parallelPool"]):
                    slot = state["parallelPool"][index]
                    if slot.get("leaseRunId") == lease.run_id:
                        if slot.get("pendingSessionId") == lease.session_id:
                            slot["pendingSessionId"] = None
                        slot.update(
                            {
                                "status": "available",
                                "leaseRunId": None,
                                "leasedAt": None,
                                "lastUsedAt": now,
                                "lastRunId": lease.run_id,
                                "lastTaskFingerprint": fingerprint,
                            }
                        )
            state["updatedAt"] = now
            write_json(lease.state_path, state)
