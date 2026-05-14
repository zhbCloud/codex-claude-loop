from __future__ import annotations

import hashlib
import re


def safe_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", value.strip())
    return value or "default"


def task_fingerprint(task_mode: str, task_text: str, allowed_paths: list[str], validation_commands: list[str], session_key: str) -> str:
    raw = "\n".join(
        [
            f"mode={task_mode}",
            f"session={session_key}",
            "allowed=" + "|".join(sorted(allowed_paths)),
            "validation=" + "|".join(sorted(validation_commands)),
            "task=" + task_text.strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
