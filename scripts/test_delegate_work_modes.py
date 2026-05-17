from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.io_utils import read_json

DELEGATE = RUNTIME_ROOT / "delegate_to_claude.py"

STRICT_TASK = """Goal
Implement the scoped task.

Allowed Scope
- .

Forbidden Actions
- Do not install dependencies.

Acceptance Criteria
- Dry-run artifacts are generated.

Verification
- dry-run

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


def run_delegate(root: Path, task: Path, mode: str, validation_phase: str = "light") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_CLAUDE_LOOP_CHILD_THREAD"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(DELEGATE),
            "--task-file",
            str(task),
            "--workflow-id",
            f"wf-{mode}",
            "--task-id",
            f"task-{mode}",
            "--role",
            "implementer",
            "--session-key",
            mode,
            "--work-mode",
            mode,
            "--validation-phase",
            validation_phase,
            "--allowed-path",
            ".",
            "--artifact-root",
            str(root / "artifacts"),
            "--dry-run",
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
    )


def latest_gate(root: Path) -> dict:
    gates = sorted((root / "artifacts").glob("final_gate_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    assert gates
    return read_json(gates[0])


def test_fast_light_run_passes_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        task = root / "task.md"
        task.write_text("Do a dry run.", encoding="utf-8")
        result = run_delegate(root, task, "fast")
        assert result.returncode == 0, result.stderr + result.stdout
        gate = latest_gate(root)
        assert gate["gateStatus"] == "passed"


def test_strict_light_run_waits_for_full_validation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        task = root / "task.md"
        task.write_text(STRICT_TASK, encoding="utf-8")
        result = run_delegate(root, task, "strict")
        assert result.returncode == 0, result.stderr + result.stdout
        gate = latest_gate(root)
        assert gate["gateStatus"] == "pending_full_validation"


if __name__ == "__main__":
    test_fast_light_run_passes_gate()
    test_strict_light_run_waits_for_full_validation()
    print("ok")
