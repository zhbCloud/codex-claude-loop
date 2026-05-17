from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
from typing import Any

from .io_utils import read_json, read_text


def default_artifact_root() -> Path:
    return Path.cwd().resolve() / ".codex" / "codex_claude_loop" / "claude-delegate"


def latest_workflow_id(root: Path) -> str:
    files = sorted(root.glob("workflow_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError(f"No workflow artifacts found under {root}")
    name = files[0].name
    return name[len("workflow_") : -len(".json")]


def normalize_scope(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if raw in {"", ".", "./"}:
        return ""
    normalized = posixpath.normpath(raw).strip("/").lower()
    return "" if normalized == "." else normalized


def scopes_overlap(left: str, right: str) -> bool:
    a = normalize_scope(left)
    b = normalize_scope(right)
    if a == "" or b == "":
        return True
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def task_scope(task: dict[str, Any]) -> str:
    scope = str(task.get("scope") or "")
    if scope:
        return scope
    allowed = task.get("allowedPaths") if isinstance(task.get("allowedPaths"), list) else []
    return str(allowed[0]) if allowed else ""


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
    strict_pending_tasks: list[str] = []
    final_verifier_missing = False
    parallel_scope_conflicts: list[str] = []
    missing_test_evidence: list[str] = []

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
    tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), dict) else {}
    strict_tasks = [task for task in tasks.values() if isinstance(task, dict) and task.get("workMode") == "strict"]
    for task in strict_tasks:
        if task.get("role") == "implementer" and task.get("reviewDecision") != "accepted":
            strict_pending_tasks.append(str(task.get("taskId") or ""))
    final_verifier = workflow.get("finalVerifier") if isinstance(workflow.get("finalVerifier"), dict) else {}
    final_acceptance = workflow.get("finalAcceptance") if isinstance(workflow.get("finalAcceptance"), dict) else {}
    final_verifier_required = final_acceptance.get("finalVerifierRequired")
    if final_verifier_required is None:
        final_verifier_required = any(task.get("role") == "implementer" and "reviews" in task for task in strict_tasks)
    if strict_tasks and final_verifier_required and final_verifier.get("reviewDecision") != "accepted":
        final_verifier_missing = True
    if strict_pending_tasks:
        problems.append("Strict implementer tasks pending accepted spec/quality reviews: " + ", ".join(strict_pending_tasks))
    if final_verifier_missing:
        problems.append("Strict workflow requires an accepted final-verifier run")

    parallel_tasks = [
        task
        for task in tasks.values()
        if isinstance(task, dict)
        and task.get("role") == "implementer"
        and task.get("allowParallel") is True
        and task.get("status") == "completed"
    ]
    for index, left in enumerate(parallel_tasks):
        for right in parallel_tasks[index + 1 :]:
            if scopes_overlap(task_scope(left), task_scope(right)):
                parallel_scope_conflicts.append(f"{left.get('taskId')}<->{right.get('taskId')}")
    if parallel_scope_conflicts:
        problems.append("Parallel implementer scopes overlap: " + ", ".join(parallel_scope_conflicts))

    run_index = {
        str(run.get("runId") or ""): run
        for run in runs
        if isinstance(run, dict) and run.get("runId")
    }
    for task in tasks.values():
        if not isinstance(task, dict) or task.get("role") != "implementer":
            continue
        if "tests" not in task:
            continue
        tests = [str(item).strip() for item in (task.get("tests") if isinstance(task.get("tests"), list) else []) if str(item).strip()]
        if not tests:
            continue
        run_ids = [str(item) for item in (task.get("runs") if isinstance(task.get("runs"), list) else [])]
        latest_run_id = str(task.get("lastRunId") or (run_ids[-1] if run_ids else ""))
        run_doc = run_index.get(latest_run_id, {})
        config_path = Path(str(run_doc.get("configPath") or ""))
        output_path = Path(str(run_doc.get("outputPath") or ""))
        config_doc = read_json(config_path) if config_path.exists() else {}
        runtime_options = config_doc.get("runtimeOptions") if isinstance(config_doc.get("runtimeOptions"), dict) else {}
        if runtime_options.get("dryRun"):
            continue
        output_text = read_text(output_path) if output_path.exists() else ""
        missing = [item for item in tests if item not in output_text]
        if missing:
            missing_test_evidence.append(f"{task.get('taskId')}: " + "; ".join(missing))
    if missing_test_evidence:
        problems.append("Declared tests missing from worker verification evidence: " + " | ".join(missing_test_evidence))

    state = "running"
    if (
        failed_runs
        or missing_status
        or gate_failed_runs
        or gate_missing_runs
        or strict_pending_tasks
        or final_verifier_missing
        or parallel_scope_conflicts
        or missing_test_evidence
    ):
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
        "strictPendingTasks": strict_pending_tasks,
        "finalVerifierMissing": final_verifier_missing,
        "parallelScopeConflicts": parallel_scope_conflicts,
        "missingTestEvidence": missing_test_evidence,
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
    if result["strictPendingTasks"]:
        print("StrictPendingTasks: " + ", ".join(result["strictPendingTasks"]))
    if result["finalVerifierMissing"]:
        print("FinalVerifierMissing: true")
    if result["parallelScopeConflicts"]:
        print("ParallelScopeConflicts: " + ", ".join(result["parallelScopeConflicts"]))
    if result["missingTestEvidence"]:
        print("MissingTestEvidence: " + " | ".join(result["missingTestEvidence"]))
    for problem in result["problems"]:
        print(f"Problem: {problem}")

    return 0 if result["ok"] else 1
