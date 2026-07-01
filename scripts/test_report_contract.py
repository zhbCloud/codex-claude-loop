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

from codex_claude_loop_runtime.reports import report_is_accepted


STRICT_PASS_WITH_CONCERNS = """Process Log
- completed

Status
PASS_WITH_CONCERNS

Role
reviewer

Summary
Accepted with minor follow-up.

Changed Files
None

Verification
- checked

Findings
- P3 follow-up only

Final Result
PASS_WITH_CONCERNS

Risks Or Follow-ups
- Follow up later.
"""


def test_pass_with_concerns_is_accepted_by_contract() -> None:
    assert report_is_accepted(STRICT_PASS_WITH_CONCERNS, strict=True)


if __name__ == "__main__":
    test_pass_with_concerns_is_accepted_by_contract()
    print("ok")
