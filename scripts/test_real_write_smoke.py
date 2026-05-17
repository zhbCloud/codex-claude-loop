from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
DELEGATE = RUNTIME_ROOT / "delegate_to_claude.py"


TASK = """Goal
Overwrite allowed.txt with exactly this single line:
codex-claude-loop real write smoke passed

Allowed Scope
- allowed.txt

Forbidden Actions
- Do not edit any file except allowed.txt.
- Do not install dependencies.

Acceptance Criteria
- allowed.txt contains exactly the requested line.
- No other files are changed.

Verification
- Read allowed.txt after writing it.

Report Requirements
Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups
"""


def test_real_write_smoke_scope_gate() -> None:
    if not shutil.which("claude"):
        print("skip: Claude CLI not found")
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, check=True, text=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "smoke@example.invalid"], cwd=root, check=True, text=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=root, check=True, text=True, capture_output=True)
        (root / "allowed.txt").write_text("before\n", encoding="utf-8")
        (root / "blocked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True, text=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, text=True, capture_output=True)
        task = root / "task.md"
        task.write_text(TASK, encoding="utf-8")

        env = os.environ.copy()
        env["CODEX_CLAUDE_LOOP_CHILD_THREAD"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                str(DELEGATE),
                "--task-file",
                str(task),
                "--workflow-id",
                "real-write-smoke",
                "--task-id",
                "real-write-smoke-001",
                "--role",
                "implementer",
                "--session-key",
                "real-write-smoke",
                "--work-mode",
                "fast",
                "--validation-phase",
                "full",
                "--allowed-path",
                "allowed.txt",
                "--artifact-root",
                str(root / "artifacts"),
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (root / "allowed.txt").read_text(encoding="utf-8").strip() == "codex-claude-loop real write smoke passed"
        assert (root / "blocked.txt").read_text(encoding="utf-8").strip() == "before"
        changed = subprocess.run(["git", "diff", "--name-only"], cwd=root, check=True, text=True, capture_output=True).stdout.splitlines()
        assert changed == ["allowed.txt"]


if __name__ == "__main__":
    test_real_write_smoke_scope_gate()
    print("ok")
