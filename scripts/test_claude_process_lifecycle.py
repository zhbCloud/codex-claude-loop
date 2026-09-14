from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime import claude_cli, delegate
from codex_claude_loop_runtime.io_utils import read_json


REPORT = """Process Log
- completed

Summary
Done.

Changed Files
None

Verification
- checked

Final Result
PASS

Risks Or Follow-ups
None
"""


class FakePipe:
    def __init__(self, name: str, events: list, *, lines: list[str] | None = None, error: BaseException | None = None, close_error: BaseException | None = None) -> None:
        self.name = name
        self.events = events
        self.lines = lines or []
        self.error = error
        self.close_error = close_error
        self.closed = False

    def write(self, text: str) -> int:
        self.events.append((self.name, "write"))
        if self.error is not None:
            raise self.error
        return len(text)

    def __iter__(self):
        yield from self.lines
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.events.append((self.name, "close"))
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeProcess:
    def __init__(self, *, read_error: BaseException | None = None, write_error: BaseException | None = None, terminate_error: BaseException | None = None, close_error: BaseException | None = None, ignore_terminate: bool = False) -> None:
        self.events: list = []
        self.stdin = FakePipe("stdin", self.events, error=write_error)
        self.stdout = FakePipe(
            "stdout",
            self.events,
            lines=[
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": REPORT}]}}) + "\n",
                json.dumps({"type": "result", "subtype": "success"}) + "\n",
            ],
            error=read_error,
            close_error=close_error,
        )
        self.stderr = None
        self.returncode = None
        self.terminate_error = terminate_error
        self.ignore_terminate = ignore_terminate
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.events.append(("process", "terminate"))
        if self.terminate_error is not None:
            raise self.terminate_error
        self.terminated = True

    def kill(self) -> None:
        self.events.append(("process", "kill"))
        self.killed = True

    def wait(self, timeout=None):
        self.events.append(("process", "wait", timeout))
        if self.ignore_terminate and self.terminated and not self.killed:
            raise subprocess.TimeoutExpired("fake-claude", timeout)
        self.returncode = -9 if self.killed else (-15 if self.terminated else 0)
        return self.returncode


def invoke_fake(root: Path, process: FakeProcess):
    with patch.object(claude_cli, "resolve_claude_cli", return_value="fake-claude"), patch.object(claude_cli.subprocess, "Popen", return_value=process):
        return claude_cli.run_claude("task", root, root / "stream.jsonl", root / "trace.log", "session", False, "test", "", False)


def assert_reaped(process: FakeProcess) -> None:
    assert process.returncode is not None
    assert process.stdin.closed
    assert process.stdout.closed


def test_success_reaps_process_and_closes_pipes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        process = FakeProcess()
        result = invoke_fake(Path(tmp), process)
        assert result["exitCode"] == 0
        assert result["finalText"] == REPORT.strip()
        assert not process.terminated
        assert not process.killed
        assert_reaped(process)


def test_io_failure_and_interrupt_reap_process_before_propagating() -> None:
    for error in (OSError("read failed"), KeyboardInterrupt()):
        with tempfile.TemporaryDirectory() as tmp:
            process = FakeProcess(read_error=error)
            try:
                invoke_fake(Path(tmp), process)
            except BaseException as exc:
                assert exc is error
            else:
                raise AssertionError("stream failure must propagate")
            assert process.terminated
            assert_reaped(process)


def test_prompt_write_failure_reaps_process() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        error = BrokenPipeError("input closed")
        process = FakeProcess(write_error=error)
        try:
            invoke_fake(Path(tmp), process)
        except BrokenPipeError as exc:
            assert exc is error
        else:
            raise AssertionError("input failure must propagate")
        assert process.terminated
        assert_reaped(process)


def test_unresponsive_process_is_killed_after_bounded_wait() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        error = OSError("read failed")
        process = FakeProcess(read_error=error, ignore_terminate=True)
        try:
            invoke_fake(Path(tmp), process)
        except OSError as exc:
            assert exc is error
        else:
            raise AssertionError("stream failure must propagate")
        assert process.terminated and process.killed
        assert_reaped(process)
        waits = [event for event in process.events if event[:2] == ("process", "wait")]
        assert len(waits) == 2
        assert all(event[2] is not None for event in waits)


def execute_fake(root: Path, process: FakeProcess, release):
    context = {
        "root": root,
        "run_id": "run",
        "session_key": "session",
        "fingerprint": "fingerprint",
        "allowed_paths": [],
        "prompt": "task",
        "config": {"workflowId": "workflow", "taskId": "task", "role": "implementer", "workMode": "fast"},
    }
    for name, filename in {
        "output_path": "output.md", "config_path": "config.json", "status_path": "status.json",
        "prompt_path": "prompt.md", "stream_path": "stream.jsonl", "trace_path": "trace.log", "final_gate_path": "gate.json",
    }.items():
        context[name] = root / filename
    ns = SimpleNamespace(session_mode="PrimaryReuse", max_parallel=3, lease_ttl_seconds=7200, lease_wait_seconds=0, dry_run=False, name_prefix="test", model="", bypass_permissions=False, validation_phase="light")
    lease = SimpleNamespace(session_id="session", resume=False, slot_name="primary")
    with (
        patch.object(claude_cli, "resolve_claude_cli", return_value="fake-claude"),
        patch.object(claude_cli.subprocess, "Popen", return_value=process),
        patch.object(delegate, "acquire_session", return_value=lease),
        patch.object(delegate, "commit_session"),
        patch.object(delegate, "release_session", side_effect=release),
        patch.object(delegate, "update_workflow_status"),
        patch.object(delegate, "finalize_workflow_record"),
    ):
        return delegate.execute_prepared(ns, context)


def test_delegate_releases_only_after_process_cleanup() -> None:
    for error in (None, OSError("read failed"), KeyboardInterrupt()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            process = FakeProcess(read_error=error)
            released = []

            def release(*args):
                assert_reaped(process)
                released.append(True)

            try:
                result = execute_fake(root, process, release)
            except BaseException as exc:
                assert error is not None and exc is error
            else:
                assert error is None and result == 0
            assert released == [True]
            status = read_json(root / "status.json")
            assert status["status"] == ("completed" if error is None else "failed")
            if isinstance(error, KeyboardInterrupt):
                assert status["failedReasons"] == ["Claude execution interrupted."]


def test_cleanup_failure_preserves_lease_and_reports_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        process = FakeProcess(read_error=OSError("read failed"), terminate_error=PermissionError("stop denied"))
        released = []
        try:
            execute_fake(root, process, lambda *args: released.append(True))
        except claude_cli.ClaudeProcessCleanupError:
            pass
        else:
            raise AssertionError("unconfirmed process cleanup must fail closed")
        assert released == []
        assert process.returncode is None
        assert process.stdin.closed and process.stdout.closed
        assert read_json(root / "status.json")["status"] == "failed"


def test_close_interrupt_cannot_hide_failed_process_cleanup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stop_error = PermissionError("stop denied")
        process = FakeProcess(read_error=OSError("read failed"), terminate_error=stop_error, close_error=KeyboardInterrupt())
        released = []
        try:
            execute_fake(root, process, lambda *args: released.append(True))
        except claude_cli.ClaudeProcessCleanupError as exc:
            assert exc.__cause__ is stop_error
        else:
            raise AssertionError("pipe-close interruption must not hide an unreaped process")
        assert released == []
        assert process.returncode is None
        assert process.stdin.closed and process.stdout.closed
        assert read_json(root / "status.json")["status"] == "failed"


def test_prepared_timestamp_is_replaced_at_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        delegate.write_json(root / "status.json", {"startedAt": "2000-01-01T00:00:00Z", "status": "queued"})
        execute_fake(root, FakeProcess(), lambda *args: None)
        status = read_json(root / "status.json")
        assert status["startedAt"] != "2000-01-01T00:00:00Z"
        assert status["startedAt"] <= status["completedAt"]


if __name__ == "__main__":
    test_success_reaps_process_and_closes_pipes()
    test_io_failure_and_interrupt_reap_process_before_propagating()
    test_prompt_write_failure_reaps_process()
    test_unresponsive_process_is_killed_after_bounded_wait()
    test_delegate_releases_only_after_process_cleanup()
    test_cleanup_failure_preserves_lease_and_reports_failure()
    test_close_interrupt_cannot_hide_failed_process_cleanup()
    test_prepared_timestamp_is_replaced_at_execution()
    print("ok")
