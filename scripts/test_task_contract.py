from __future__ import annotations

import sys

RUNTIME_ROOT = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "plugins"
    / "codex-claude-loop"
    / "skills"
    / "codex-claude-loop"
    / "scripts"
)
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.common import DelegateError
from codex_claude_loop_runtime.task_contract import has_task_contract, validate_task_text


VALID_TASK = """Goal
Implement the smallest scoped change.

Allowed Scope
- src/example.ts

Forbidden Actions
- Do not edit dependencies.

Acceptance Criteria
- Behavior matches the request.

Verification
- pnpm run build

Report Requirements
Process Log
Status
Role
Summary
Changed Files
Verification
Findings
Final Result
Risks Or Follow-ups
"""


def test_valid_contract_passes() -> None:
    assert has_task_contract(VALID_TASK)
    validate_task_text(VALID_TASK, ["pnpm run build"])


def test_missing_section_fails() -> None:
    text = VALID_TASK.replace("Forbidden Actions", "Forbidden")
    try:
        validate_task_text(text)
    except DelegateError as exc:
        assert "Missing required sections" in str(exc)
    else:
        raise AssertionError("missing section should fail")


def test_missing_report_heading_fails() -> None:
    text = VALID_TASK.replace("Findings\n", "")
    try:
        validate_task_text(text)
    except DelegateError as exc:
        assert "Report Requirements is missing headings" in str(exc)
    else:
        raise AssertionError("missing report heading should fail")


if __name__ == "__main__":
    test_valid_contract_passes()
    test_missing_section_fails()
    test_missing_report_heading_fails()
    print("ok")
