from __future__ import annotations

from datetime import datetime, timezone


CHILD_MARKER_NAME = "CODEX_CLAUDE_LOOP_CHILD_THREAD"
CHILD_MARKER_VALUE = "1"
ARTIFACT_SCHEMA_VERSION = 1
REQUIRED_HEADINGS = (
    "Process Log",
    "Summary",
    "Changed Files",
    "Verification",
    "Final Result",
    "Risks Or Follow-ups",
)


class DelegateError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def has_required_headings(text: str) -> bool:
    lowered = text.lower()
    return all(heading.lower() in lowered for heading in REQUIRED_HEADINGS)
