from __future__ import annotations

from datetime import datetime, timezone

from .contract import load_contract

_CONTRACT = load_contract()
_CHILD_THREAD = _CONTRACT.get("childThread") if isinstance(_CONTRACT.get("childThread"), dict) else {}

CHILD_MARKER_NAME = str(_CHILD_THREAD.get("markerName") or "CODEX_CLAUDE_LOOP_CHILD_THREAD")
CHILD_MARKER_VALUE = str(_CHILD_THREAD.get("markerValue") or "1")
ARTIFACT_SCHEMA_VERSION = int(_CONTRACT.get("artifactSchemaVersion") or 2)
INVOCATION_CONTRACT = str(_CONTRACT.get("invocationContract") or "codex_claude_loop_workflow")
WORK_MODES = tuple(str(item) for item in (_CONTRACT.get("workModes") or ["auto", "fast", "strict"]))
STRICT_REVIEW_KINDS = tuple(str(item) for item in (_CONTRACT.get("reviewKinds") or ["spec", "quality"]))
REPORT_STATUS_VALUES = tuple(
    str(item)
    for item in (_CONTRACT.get("reportStatusValues") or ["PASS", "PASS_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "FAIL"])
)
FAST_REQUIRED_HEADINGS = tuple(
    str(item)
    for item in (
        _CONTRACT.get("fastReportHeadings")
        or ["Process Log", "Summary", "Changed Files", "Verification", "Final Result", "Risks Or Follow-ups"]
    )
)
STRICT_REQUIRED_HEADINGS = tuple(
    str(item)
    for item in (
        _CONTRACT.get("strictReportHeadings")
        or [
            "Process Log",
            "Status",
            "Role",
            "Summary",
            "Changed Files",
            "Verification",
            "Findings",
            "Final Result",
            "Risks Or Follow-ups",
        ]
    )
)
REQUIRED_HEADINGS = STRICT_REQUIRED_HEADINGS


class DelegateError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def has_required_headings(text: str, strict: bool = False) -> bool:
    lowered = text.lower()
    headings = STRICT_REQUIRED_HEADINGS if strict else FAST_REQUIRED_HEADINGS
    return all(heading.lower() in lowered for heading in headings)
