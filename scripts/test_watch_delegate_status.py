from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


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
WINDOWS_WATCH_SCRIPT = WATCH_SCRIPT.parents[1] / "windows_scripts" / "watch_delegate_status.ps1"
sys.path.insert(0, str(WATCH_SCRIPT.parent))

from codex_claude_loop_runtime import watch_status


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def watch_backends() -> tuple[str, ...]:
    return ("python", "powershell") if os.name == "nt" else ("python",)


def run_watch(*args: str, backend: str = "python") -> subprocess.CompletedProcess[str]:
    if backend == "powershell":
        powershell = shutil.which("pwsh")
        assert powershell, "PowerShell 7 is required to test the Windows watcher"
        options = {
            "--run-id": "-RunId",
            "--workflow-id": "-WorkflowId",
            "--artifact-root": "-ArtifactRoot",
            "--watch": "-Watch",
            "--timeout-seconds": "-TimeoutSeconds",
            "--max-interval-seconds": "-MaxIntervalSeconds",
            "--stream-tail-lines": "-StreamTailLines",
        }
        command = [powershell, "-NoProfile", "-NonInteractive", "-File", str(WINDOWS_WATCH_SCRIPT)]
        command.extend(options.get(argument, argument) for argument in args)
    else:
        command = [sys.executable, "-B", str(WATCH_SCRIPT), *args]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
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


def test_workflow_summary_and_exit_share_current_status_snapshot() -> None:
    scenarios = (
        ("running", ("completed",), 0, True),
        ("running", ("failed",), 0, False),
        ("running", ("completed",), 2, True),
        ("running", ("failed",), 2, True),
        ("running", ("completed", "running", "failed"), 2, True),
        ("failed", ("completed",), 0, True),
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stream_path = root / "stream.jsonl"
        stream_path.write_text("older\nnewer\nlast\n", encoding="utf-8")
        for stale_status, statuses, tail_lines, watch in scenarios:
            runs = []
            for index, status in enumerate(statuses):
                run_id = f"run-{index}"
                status_path = root / f"status_{run_id}.json"
                write_json(status_path, {"runId": run_id, "status": status, "streamPath": str(stream_path)})
                runs.append(
                    {
                        "runId": run_id,
                        "taskId": f"task-{index}",
                        "role": "implementer",
                        "status": stale_status,
                        "statusPath": str(status_path),
                    }
                )
            write_json(root / "workflow_workflow-1.json", {"runs": runs})
            args = [
                "--workflow-id", "workflow-1", "--artifact-root", str(root),
                "--stream-tail-lines", str(tail_lines),
            ]
            if watch:
                args.extend(["--watch", "--timeout-seconds", "1", "--max-interval-seconds", "1"])
            expected_summary = (
                f"WorkflowSummary Completed={statuses.count('completed')} "
                f"Running={statuses.count('running')} Failed={statuses.count('failed')}"
            )
            outputs = []
            for backend in watch_backends():
                result = run_watch(*args, backend=backend)
                context = (backend, stale_status, statuses, tail_lines, result.stdout, result.stderr)
                assert result.returncode == (1 if "failed" in statuses else 0), context
                assert expected_summary in result.stdout, context
                assert "WatchTimeout=" not in result.stdout, context
                for index, status in enumerate(statuses):
                    if tail_lines:
                        assert f"RunId=run-{index} Status={status}" in result.stdout, context
                        assert f"TaskId=task-{index}" in result.stdout, context
                    else:
                        assert f"RunId=run-{index} TaskId=task-{index} Role=implementer Status={status}" in result.stdout, context
                if tail_lines:
                    assert result.stdout.count("StreamTail:\nnewer\nlast\n") == len(statuses), context
                outputs.append(result.stdout.splitlines())
            assert all(output == outputs[0] for output in outputs), outputs


def test_stream_tail_preserves_splitlines_and_utf8_boundaries() -> None:
    cases = [
        "", "\n", "\r\n", "\n\n", "没有换行", "\n正文\n\n",
        "first\r\nsecond\rthird\n", "a\vb\fc\x1cd\x1de\x1ef\x85g\u2028h\u2029i",
        "header\n" + "汉字🙂" * 3000 + "\n末行\n",
        "header\n" + "x" * 100_000,
    ]
    for separator in ("\r\n", "\x85", "\u2028", "\u2029", "汉", "🙂"):
        padding = "x" * (8192 - len(separator.encode("utf-8")))
        cases.append("header\nfirst" + separator + padding + "\n")
    with tempfile.TemporaryDirectory() as temp_dir:
        stream_path = Path(temp_dir) / "stream.jsonl"
        for text in cases:
            stream_path.write_bytes(text.encode("utf-8"))
            status = {"runId": "tail", "streamPath": str(stream_path)}
            for line_count in (1, 2, 5, 1000):
                lines = watch_status.status_lines(status, line_count)
                actual = lines[lines.index("StreamTail:") + 1:]
                assert actual == text.splitlines()[-line_count:], (text[:40], line_count, actual)
            assert "StreamTail:" not in watch_status.status_lines(status, 0)


def test_stream_tail_read_volume_does_not_grow_with_history() -> None:
    original_open = Path.open
    read_volumes = []
    with tempfile.TemporaryDirectory() as temp_dir:
        stream_path = Path(temp_dir) / "stream.jsonl"
        for history_size in (1024 * 1024, 16 * 1024 * 1024):
            stream_path.write_bytes(b"history\n" * (history_size // 8) + b"recent-1\nrecent-2\n")
            bytes_read = 0

            class CountingStream:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    self.stream.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def read(self, size=-1):
                    nonlocal bytes_read
                    data = self.stream.read(size)
                    bytes_read += len(data.encode("utf-8") if isinstance(data, str) else data)
                    return data

            def counting_open(path, *args, **kwargs):
                return CountingStream(original_open(path, *args, **kwargs))

            with patch.object(Path, "open", counting_open):
                lines = watch_status.status_lines({"streamPath": str(stream_path)}, 2)
            assert lines[-2:] == ["recent-1", "recent-2"], lines
            assert 0 < bytes_read <= 64 * 1024, (history_size, bytes_read)
            read_volumes.append(bytes_read)
            print(f"StreamTailRead HistoryBytes={history_size} BytesRead={bytes_read}")
    assert read_volumes[0] == read_volumes[1], read_volumes


def test_stream_tail_reflects_appends_and_truncation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        stream_path = Path(temp_dir) / "stream.jsonl"
        status = {"streamPath": str(stream_path)}
        stream_path.write_bytes(b"older\nfirst\n")
        assert watch_status.status_lines(status, 1)[-1] == "first"
        with stream_path.open("ab") as stream:
            stream.write("追加\n".encode("utf-8"))
        assert watch_status.status_lines(status, 1)[-1] == "追加"
        stream_path.write_bytes(b"")
        assert watch_status.status_lines(status, 1)[-1] == "StreamTail:"
        stream_path.write_bytes("新日志".encode("utf-8"))
        assert watch_status.status_lines(status, 1)[-1] == "新日志"


if __name__ == "__main__":
    test_completed_and_failed_run_exit_codes()
    test_workflow_summary_uses_current_status_artifacts()
    test_workflow_summary_and_exit_share_current_status_snapshot()
    test_stream_tail_preserves_splitlines_and_utf8_boundaries()
    test_stream_tail_read_volume_does_not_grow_with_history()
    test_stream_tail_reflects_appends_and_truncation()
    print("ok")
