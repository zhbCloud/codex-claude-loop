from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "codex-claude-loop"
    / "skills"
    / "codex-claude-loop"
    / "scripts"
    / "watch_delegate_status.py"
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_watch(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WATCH_SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_completed_and_failed_run_exit_codes() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        write_json(
            root / "status_completed.json",
            {
                "runId": "completed",
                "workflowId": "workflow-1",
                "taskId": "task-1",
                "role": "implementer",
                "status": "completed",
                "phase": "finished",
                "updatedAt": "2026-07-02T00:00:00Z",
                "heartbeatAt": "2026-07-02T00:00:00Z",
                "streamRecords": 4,
            },
        )
        completed = run_watch(
            "--run-id",
            "completed",
            "--artifact-root",
            str(root),
        )
        assert completed.returncode == 0, completed.stderr
        assert "RunId=completed Status=completed Phase=finished" in completed.stdout
        assert "WorkflowId=workflow-1" in completed.stdout

        write_json(
            root / "status_failed.json",
            {
                "runId": "failed",
                "status": "failed",
                "failedReasons": ["verification failed"],
            },
        )
        failed = run_watch(
            "--run-id",
            "failed",
            "--artifact-root",
            str(root),
        )
        assert failed.returncode == 1
        assert "FailedReasons=verification failed" in failed.stdout


def test_workflow_summary_uses_current_status_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        status_path = root / "status_run-1.json"
        write_json(status_path, {"runId": "run-1", "status": "completed"})
        write_json(
            root / "workflow_workflow-1.json",
            {
                "runs": [
                    {
                        "runId": "run-1",
                        "taskId": "task-1",
                        "role": "implementer",
                        "status": "running",
                        "statusPath": str(status_path),
                    }
                ]
            },
        )

        result = run_watch(
            "--workflow-id",
            "workflow-1",
            "--artifact-root",
            str(root),
        )
        assert result.returncode == 0, result.stderr
        assert "WorkflowId=workflow-1 TotalRuns=1" in result.stdout
        assert "RunId=run-1 TaskId=task-1 Role=implementer Status=completed" in result.stdout
        assert "WorkflowSummary Completed=1 Running=0 Failed=0" in result.stdout


if __name__ == "__main__":
    test_completed_and_failed_run_exit_codes()
    test_workflow_summary_uses_current_status_artifacts()
    print("ok")
