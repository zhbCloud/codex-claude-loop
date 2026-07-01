from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .io_utils import read_json


class WatchStatusError(RuntimeError):
    pass


def artifact_root(explicit_root: str) -> Path:
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()
    return Path.cwd() / ".codex" / "codex_claude_loop" / "claude-delegate"


def latest_run_id(root: Path) -> str:
    candidates = sorted(
        root.glob("status_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise WatchStatusError(f"No status artifacts found under {root}")
    return candidates[0].stem.removeprefix("status_")


def read_status(root: Path, run_id: str) -> dict[str, Any]:
    path = root / f"status_{run_id}.json"
    if not path.is_file():
        raise WatchStatusError(f"Status artifact not found: {path}")
    return read_json(path)


def read_workflow(root: Path, workflow_id: str) -> dict[str, Any]:
    path = root / f"workflow_{workflow_id}.json"
    if not path.is_file():
        raise WatchStatusError(f"Workflow artifact not found: {path}")
    return read_json(path)


def display_value(value: object) -> str:
    if value is None or not str(value).strip():
        return "-"
    return str(value)


def status_lines(status: dict[str, Any], stream_tail_lines: int) -> list[str]:
    lines = [
        " ".join(
            [
                f"RunId={display_value(status.get('runId'))}",
                f"Status={display_value(status.get('status'))}",
                f"Phase={display_value(status.get('phase'))}",
                f"UpdatedAt={display_value(status.get('updatedAt'))}",
                f"HeartbeatAt={display_value(status.get('heartbeatAt'))}",
                f"StreamRecords={status.get('streamRecords', 0)}",
            ]
        )
    ]
    for key, label in (
        ("workflowId", "WorkflowId"),
        ("taskId", "TaskId"),
        ("role", "Role"),
        ("lastAssistantTextPreview", "LastAssistantTextPreview"),
    ):
        if status.get(key):
            lines.append(f"{label}={status[key]}")

    failed_reasons = status.get("failedReasons")
    if isinstance(failed_reasons, list) and failed_reasons:
        lines.append(f"FailedReasons={'; '.join(str(item) for item in failed_reasons)}")

    stream_path_value = status.get("streamPath")
    if stream_tail_lines > 0 and stream_path_value:
        stream_path = Path(str(stream_path_value))
        if stream_path.is_file():
            lines.append("StreamTail:")
            lines.extend(stream_path.read_text(encoding="utf-8").splitlines()[-stream_tail_lines:])
    return lines


def workflow_lines(root: Path, workflow_id: str, stream_tail_lines: int) -> tuple[list[str], list[str]]:
    workflow = read_workflow(root, workflow_id)
    runs = workflow.get("runs", [])
    if not isinstance(runs, list):
        raise WatchStatusError(f"Workflow runs must be a list: {workflow_id}")

    lines = [f"WorkflowId={workflow_id} TotalRuns={len(runs)}"]
    statuses: list[str] = []
    completed = 0
    failed = 0
    running = 0

    for run in runs:
        if not isinstance(run, dict):
            raise WatchStatusError(f"Workflow run must be an object: {workflow_id}")
        current = dict(run)
        status_path_value = run.get("statusPath")
        if status_path_value:
            status_path = Path(str(status_path_value))
            if status_path.is_file():
                current.update(read_json(status_path))

        status = str(current.get("status", ""))
        statuses.append(status)
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
        else:
            running += 1

        if stream_tail_lines > 0 and status_path_value:
            lines.extend(status_lines(current, stream_tail_lines))
        else:
            lines.append(
                " ".join(
                    [
                        f"RunId={display_value(current.get('runId'))}",
                        f"TaskId={display_value(current.get('taskId'))}",
                        f"Role={display_value(current.get('role'))}",
                        f"Status={display_value(status)}",
                    ]
                )
            )

    lines.append(f"WorkflowSummary Completed={completed} Running={running} Failed={failed}")
    return lines, statuses


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Watch Codex Claude Loop delegate status")
    result.add_argument("--run-id", default="")
    result.add_argument("--workflow-id", default="")
    result.add_argument("--artifact-root", default="")
    result.add_argument("--watch", action="store_true")
    result.add_argument("--initial-interval-seconds", type=int, default=1)
    result.add_argument("--max-interval-seconds", type=int, default=12)
    result.add_argument("--timeout-seconds", type=int, default=0)
    result.add_argument("--stream-tail-lines", type=int, default=0)
    return result


def run(ns: argparse.Namespace) -> int:
    root = artifact_root(ns.artifact_root)
    deadline = time.monotonic() + ns.timeout_seconds if ns.timeout_seconds > 0 else None
    interval = max(1, ns.initial_interval_seconds)
    max_interval = max(interval, ns.max_interval_seconds)

    while True:
        if ns.workflow_id:
            lines, statuses = workflow_lines(root, ns.workflow_id, ns.stream_tail_lines)
            print("\n".join(lines))
            has_failed = "failed" in statuses
            all_finished = bool(statuses) and all(status in {"completed", "failed"} for status in statuses)
            if not ns.watch or has_failed or all_finished:
                return 1 if has_failed else 0
        else:
            run_id = ns.run_id or latest_run_id(root)
            status = read_status(root, run_id)
            print("\n".join(status_lines(status, ns.stream_tail_lines)))
            status_value = str(status.get("status", ""))
            if not ns.watch or status_value in {"completed", "failed"}:
                return 1 if status_value == "failed" else 0

        if deadline is not None and time.monotonic() >= deadline:
            print(f"WatchTimeout=TimeoutSeconds:{ns.timeout_seconds}")
            return 2

        time.sleep(interval)
        interval = min(max_interval, max(interval + 3, int(interval * 1.5)))


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parser().parse_args(argv))
    except (WatchStatusError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
