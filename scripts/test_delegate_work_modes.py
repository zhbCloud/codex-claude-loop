from __future__ import annotations

import os
import json
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


def test_prepared_worker_publishes_its_own_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "path-alias").mkdir()
        root = root / "path-alias" / ".."
        assert str(root) != str(root.resolve())
        task = root / "task.md"
        task.write_text("Do a dry run.", encoding="utf-8")
        env = os.environ.copy()
        env["CODEX_CLAUDE_LOOP_CHILD_THREAD"] = "1"
        prepared = subprocess.run(
            [sys.executable, "-B", str(DELEGATE), "--task-file", str(task), "--workflow-id", "worker-test",
             "--task-id", "task", "--role", "implementer", "--session-key", "worker-test", "--work-mode", "fast",
             "--artifact-root", str(root / "artifacts"), "--dry-run", "--prepare-only"],
            cwd=root, env=env, text=True, capture_output=True, timeout=10,
        )
        assert prepared.returncode == 0, prepared.stderr
        config_path = next((root / "artifacts").glob("config_*.json"))
        config = read_json(config_path)
        status_path = Path(config["statusPath"])
        queued = read_json(status_path)
        queued["startedAt"] = "2000-01-01T00:00:00Z"
        status_path.write_text(json.dumps(queued), encoding="utf-8")
        worker = subprocess.Popen(
            [sys.executable, "-B", str(DELEGATE), "--worker-config", str(config_path)],
            cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = worker.communicate(timeout=10)
            assert worker.returncode == 0, stderr + stdout
            status = read_json(status_path)
            assert status["status"] == "completed"
            assert status["workerPid"] == worker.pid
            for field, suffix in (("workerLogPath", ".log"), ("workerErrorLogPath", ".err.log")):
                expected = (root / "artifacts" / f"worker_{config['runId']}{suffix}").resolve()
                actual = Path(status[field]).resolve()
                assert actual == expected, f"{field}: {actual} != {expected}"
            assert status["startedAt"] != queued["startedAt"]
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)
        wrapper = RUNTIME_ROOT.parent / "windows_scripts" / "delegate_to_claude.ps1"
        assert "Set-Content -LiteralPath $statusPath" not in wrapper.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_fast_light_run_passes_gate()
    test_strict_light_run_waits_for_full_validation()
    test_prepared_worker_publishes_its_own_metadata()
    print("ok")
