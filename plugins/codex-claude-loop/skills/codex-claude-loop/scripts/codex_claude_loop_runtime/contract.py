from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import read_json

DEFAULT_CONTRACT: dict[str, Any] = {
    "schemaVersion": 1,
    "invocationContract": "codex_claude_loop_workflow",
    "artifactSchemaVersion": 3,
    "childThread": {"markerName": "CODEX_CLAUDE_LOOP_CHILD_THREAD", "markerValue": "1"},
    "workModes": ["auto", "fast", "strict"],
    "workerRoles": ["planner", "implementer", "researcher", "reviewer", "final-verifier"],
    "reviewKinds": ["spec", "quality"],
    "reportStatusValues": ["PASS", "PASS_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "FAIL"],
    "fastReportHeadings": [
        "Process Log",
        "Summary",
        "Changed Files",
        "Verification",
        "Final Result",
        "Risks Or Follow-ups",
    ],
    "strictReportHeadings": [
        "Process Log",
        "Status",
        "Role",
        "Summary",
        "Changed Files",
        "Verification",
        "Findings",
        "Final Result",
        "Risks Or Follow-ups",
    ],
}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def contract_path() -> Path:
    return skill_root() / "contract.json"


def load_contract() -> dict[str, Any]:
    path = contract_path()
    if not path.exists():
        return dict(DEFAULT_CONTRACT)
    loaded = read_json(path)
    merged = dict(DEFAULT_CONTRACT)
    merged.update(loaded)
    child_thread = dict(DEFAULT_CONTRACT["childThread"])
    child_thread.update(loaded.get("childThread") if isinstance(loaded.get("childThread"), dict) else {})
    merged["childThread"] = child_thread
    return merged
