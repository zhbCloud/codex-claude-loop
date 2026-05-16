from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .io_utils import read_json


def default_artifact_root() -> Path:
    return Path.cwd().resolve() / ".codex" / "codex_claude_loop" / "claude-delegate"


def latest_workflow_id(root: Path) -> str:
    files = sorted(root.glob("workflow_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError(f"No workflow artifacts found under {root}")
    name = files[0].name
    return name[len("workflow_") : -len(".json")]


def verify_workflow(root: Path, workflow_id: str) -> dict[str, Any]:
    workflow_path = root / f"workflow_{workflow_id}.json"
    if not workflow_path.exists():
        raise RuntimeError(f"Workflow artifact not found: {workflow_path}")

    workflow = read_json(workflow_path)
    runs = workflow.get("runs") if isinstance(workflow.get("runs"), list) else []

    problems: list[str] = []
    failed_runs: list[str] = []
    running_runs: list[str] = []
    missing_status: list[str] = []
    gate_pending_runs: list[str] = []
    gate_failed_runs: list[str] = []
    gate_missing_runs: list[str] = []

    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("runId") or "")
        status_path = Path(str(run.get("statusPath") or ""))
        status_value = str(run.get("status") or "")

        if not run_id:
            problems.append("Run entry missing runId")
            continue
        if not status_path.exists():
            missing_status.append(run_id)
            continue

        status_doc = read_json(status_path)
        effective_status = str(status_doc.get("status") or status_value)
        if effective_status == "failed":
            failed_runs.append(run_id)
        elif effective_status not in {"completed", "failed"}:
            running_runs.append(run_id)
        final_gate_path = Path(str(status_doc.get("finalGatePath") or root / f"final_gate_{run_id}.json"))
        if not final_gate_path.exists():
            gate_missing_runs.append(run_id)
            continue
        gate_doc = read_json(final_gate_path)
        gate_status = str(gate_doc.get("gateStatus") or "")
        if gate_status == "failed":
            gate_failed_runs.append(run_id)
        elif gate_status != "passed":
            gate_pending_runs.append(run_id)

    if not runs:
        problems.append("Workflow has no runs")
    if missing_status:
        problems.append("Missing status files for runs: " + ", ".join(missing_status))
    if failed_runs:
        problems.append("Failed runs: " + ", ".join(failed_runs))
    if gate_missing_runs:
        problems.append("Missing final gate files for runs: " + ", ".join(gate_missing_runs))
    if gate_failed_runs:
        problems.append("Final gate failed for runs: " + ", ".join(gate_failed_runs))
    if gate_pending_runs:
        problems.append("Final gate pending for runs: " + ", ".join(gate_pending_runs))

    state = "running"
    if failed_runs or missing_status or gate_failed_runs or gate_missing_runs:
        state = "failed"
    elif runs and not running_runs and not gate_pending_runs:
        state = "completed"

    return {
        "workflowId": workflow_id,
        "state": state,
        "ok": state == "completed" and not problems,
        "totalRuns": len(runs),
        "runningRuns": running_runs,
        "failedRuns": failed_runs,
        "gatePendingRuns": gate_pending_runs,
        "gateFailedRuns": gate_failed_runs,
        "gateMissingRuns": gate_missing_runs,
        "problems": problems,
        "workflowPath": str(workflow_path),
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify Codex Claude Loop workflow artifacts")
    p.add_argument("--workflow-id", default="")
    p.add_argument("--artifact-root", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    root = Path(ns.artifact_root).resolve() if ns.artifact_root else default_artifact_root()
    workflow_id = ns.workflow_id or latest_workflow_id(root)
    result = verify_workflow(root, workflow_id)

    print(f"WorkflowId: {result['workflowId']}")
    print(f"State: {result['state']}")
    print(f"OK: {result['ok']}")
    print(f"TotalRuns: {result['totalRuns']}")
    print(f"WorkflowPath: {result['workflowPath']}")
    if result["runningRuns"]:
        print("RunningRuns: " + ", ".join(result["runningRuns"]))
    if result["failedRuns"]:
        print("FailedRuns: " + ", ".join(result["failedRuns"]))
    if result["gatePendingRuns"]:
        print("GatePendingRuns: " + ", ".join(result["gatePendingRuns"]))
    if result["gateFailedRuns"]:
        print("GateFailedRuns: " + ", ".join(result["gateFailedRuns"]))
    if result["gateMissingRuns"]:
        print("GateMissingRuns: " + ", ".join(result["gateMissingRuns"]))
    for problem in result["problems"]:
        print(f"Problem: {problem}")

    return 0 if result["ok"] else 1
