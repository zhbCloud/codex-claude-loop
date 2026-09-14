from __future__ import annotations

import contextlib
import errno
import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def read_json(path: Path) -> dict[str, Any]:
    lock_path = path.with_name(path.name + ".write.lock")
    # Runtime artifacts already have a stable publication lock. Participate in
    # it so Windows readers do not prevent atomic replacement. Static plugin
    # files stay read-only and do not acquire new sidecar files.
    if lock_path.is_file():
        with file_lock(lock_path):
            return json.loads(read_text(path))
    return json.loads(read_text(path))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            tmp = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        with file_lock(path.with_name(path.name + ".write.lock")):
            os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def file_lock(path: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    """Hold a process-owned lock; keep its inode stable across acquisitions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            def acquire() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for file lock: {path}") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            release()


def ensure_writable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = path.with_name(path.name + ".probe")
    probe.write_text("", encoding="utf-8")
    probe.unlink(missing_ok=True)
