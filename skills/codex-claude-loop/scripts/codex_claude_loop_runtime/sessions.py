from __future__ import annotations

import contextlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import DelegateError, now_iso
from .io_utils import read_json, write_json


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


class AtomicLock:
    def __init__(self, path: Path, ttl_seconds: int, wait_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.wait_seconds = wait_seconds
        self.acquired = False

    def __enter__(self) -> "AtomicLock":
        deadline = time.monotonic() + max(0, self.wait_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"pid={os.getpid()} acquiredAt={now_iso()}\n")
                self.acquired = True
                return self
            except FileExistsError:
                if self._is_stale():
                    with contextlib.suppress(FileNotFoundError):
                        self.path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise DelegateError(f"Timed out waiting for session lock: {self.path}")
                time.sleep(0.25)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.acquired:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()

    def _is_stale(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > self.ttl_seconds


def _new_state(session_key: str) -> dict[str, Any]:
    return {
        "version": 1,
        "sessionKey": session_key,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "primary": {
            "sessionId": None,
            "status": "available",
            "leaseRunId": None,
            "leasedAt": None,
            "lastUsedAt": None,
            "lastRunId": None,
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
    if time.time() - ts > ttl_seconds:
        slot["status"] = "available"
        slot["leaseRunId"] = None
        slot["leasedAt"] = None
        return False
    return True


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
    with AtomicLock(lock_path, lease_ttl_seconds, lease_wait_seconds):
        state = _read_state(state_path, session_key)
        state["updatedAt"] = now_iso()
        if session_mode in {"PrimaryReuse", "PrimaryAnchor"}:
            slot = state["primary"]
            if _leased(slot, lease_ttl_seconds):
                raise DelegateError(f"Primary Claude session is already leased for SessionKey={session_key}")
            resume = bool(slot.get("sessionId"))
            if not resume:
                slot["sessionId"] = str(uuid.uuid4())
            slot.update({"status": "leased", "leaseRunId": run_id, "leasedAt": now_iso()})
            write_json(state_path, state)
            return SessionLease(session_key, session_mode, str(slot["sessionId"]), resume, "primary", state_path, lock_path, run_id)

        pool = state["parallelPool"]
        max_parallel = max(1, max_parallel)
        candidates: list[tuple[int, dict[str, Any], bool]] = []
        for index, slot in enumerate(pool):
            if not _leased(slot, lease_ttl_seconds):
                candidates.append((index, slot, slot.get("lastTaskFingerprint") == fingerprint))
        if not candidates and len(pool) < max_parallel:
            slot = {
                "sessionId": str(uuid.uuid4()),
                "status": "available",
                "leaseRunId": None,
                "leasedAt": None,
                "lastUsedAt": None,
                "lastRunId": None,
                "lastTaskFingerprint": fingerprint,
            }
            pool.append(slot)
            candidates.append((len(pool) - 1, slot, True))
        if not candidates:
            raise DelegateError(f"No available ParallelPool slots for SessionKey={session_key}; maxParallel={max_parallel}")
        candidates.sort(key=lambda item: (0 if item[2] else 1, item[1].get("lastUsedAt") or ""))
        index, slot, _ = candidates[0]
        resume = bool(slot.get("sessionId"))
        if not resume:
            slot["sessionId"] = str(uuid.uuid4())
        slot.update(
            {
                "status": "leased",
                "leaseRunId": run_id,
                "leasedAt": now_iso(),
                "lastTaskFingerprint": fingerprint,
            }
        )
        write_json(state_path, state)
        return SessionLease(session_key, session_mode, str(slot["sessionId"]), resume, f"parallel-{index}", state_path, lock_path, run_id)


def release_session(lease: SessionLease, fingerprint: str, lease_ttl_seconds: int) -> None:
    with contextlib.suppress(Exception):
        with AtomicLock(lease.lock_path, lease_ttl_seconds, 30):
            state = _read_state(lease.state_path, lease.session_key)
            now = now_iso()
            if lease.slot_name == "primary":
                slot = state["primary"]
                if slot.get("leaseRunId") == lease.run_id:
                    slot.update({"status": "available", "leaseRunId": None, "leasedAt": None, "lastUsedAt": now, "lastRunId": lease.run_id})
            else:
                index = int(lease.slot_name.split("-", 1)[1])
                if 0 <= index < len(state["parallelPool"]):
                    slot = state["parallelPool"][index]
                    if slot.get("leaseRunId") == lease.run_id:
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
