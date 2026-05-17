from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import ARTIFACT_SCHEMA_VERSION, INVOCATION_CONTRACT, STRICT_REVIEW_KINDS, now_iso
from .io_utils import read_json, write_json
from .reports import report_is_accepted, report_token


def update_workflow_record(
    artifact_root: Path,
    workflow_id: str,
    run_id: str,
    task_id: str,
    role: str,
    work_mode: str,
    scope: str,
    allowed_paths: list[str],
    validation_commands: list[str],
    tests: list[str],
    depends_on: list[str],
    allow_parallel: bool,
    review_for_task_id: str,
    review_kind: str,
    config_path: str,
    status_path: str,
    prompt_path: str,
    output_path: str,
    status_value: str,
) -> None:
    workflow_path = artifact_root / f"workflow_{workflow_id}.json"
    if workflow_path.exists():
        workflow = read_json(workflow_path)
    else:
        workflow = {
            "artifactSchema": ARTIFACT_SCHEMA_VERSION,
            "invocationContract": INVOCATION_CONTRACT,
            "workflowId": workflow_id,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
            "runs": [],
            "taskMap": {},
            "tasks": {},
            "workModes": [],
        }

    workflow.setdefault("runs", [])
    workflow.setdefault("taskMap", {})
    workflow.setdefault("tasks", {})
    workflow.setdefault("workModes", [])
    workflow["updatedAt"] = now_iso()
    if work_mode not in workflow["workModes"]:
        workflow["workModes"].append(work_mode)
    workflow["taskMap"][run_id] = {"taskId": task_id, "role": role}
    task = workflow["tasks"].setdefault(task_id, {"taskId": task_id, "runs": []})
    task.update(
        {
            "role": role,
            "workMode": work_mode,
            "scope": scope,
            "allowedPaths": allowed_paths,
            "validationCommands": validation_commands,
            "tests": tests,
            "dependsOn": depends_on,
            "allowParallel": allow_parallel,
            "status": status_value,
        }
    )
    if review_for_task_id:
        task["reviewForTaskId"] = review_for_task_id
    if review_kind:
        task["reviewKind"] = review_kind
    if run_id not in task["runs"]:
        task["runs"].append(run_id)
    workflow["runs"].append(
        {
            "runId": run_id,
            "taskId": task_id,
            "role": role,
            "workMode": work_mode,
            "reviewForTaskId": review_for_task_id,
            "reviewKind": review_kind,
            "status": status_value,
            "statusPath": status_path,
            "configPath": config_path,
            "promptPath": prompt_path,
            "outputPath": output_path,
            "updatedAt": now_iso(),
        }
    )
    write_json(workflow_path, workflow)


def update_workflow_status(context: dict[str, Any], status_value: str) -> None:
    config = dict(context["config"])
    workflow_id = str(config.get("workflowId") or "")
    run_id = str(config.get("runId") or "")
    if not workflow_id or not run_id:
        return

    artifact_root = Path(context["status_path"]).resolve().parent
    workflow_path = artifact_root / f"workflow_{workflow_id}.json"
    if not workflow_path.exists():
        return

    workflow = read_json(workflow_path)
    runs = workflow.get("runs")
    if not isinstance(runs, list):
        return

    for item in runs:
        if isinstance(item, dict) and item.get("runId") == run_id:
            item["status"] = status_value
            item["updatedAt"] = now_iso()

    workflow["updatedAt"] = now_iso()
    write_json(workflow_path, workflow)


def write_final_gate(
    artifact_root: Path,
    run_id: str,
    workflow_id: str,
    task_id: str,
    validation_phase: str,
    run_status: str,
    gate_status: str,
    reasons: list[str],
) -> Path:
    gate_path = artifact_root / f"final_gate_{run_id}.json"
    gate_doc = {
        "runId": run_id,
        "workflowId": workflow_id,
        "taskId": task_id,
        "validationPhase": validation_phase,
        "runStatus": run_status,
        "gateStatus": gate_status,
        "reasons": reasons,
        "updatedAt": now_iso(),
    }
    write_json(gate_path, gate_doc)
    return gate_path


def finalize_workflow_record(context: dict[str, Any], status_value: str, output_text: str) -> None:
    config = dict(context["config"])
    workflow_id = str(config.get("workflowId") or "")
    run_id = str(config.get("runId") or "")
    task_id = str(config.get("taskId") or "")
    if not workflow_id or not run_id or not task_id:
        return

    artifact_root = Path(context["status_path"]).resolve().parent
    workflow_path = artifact_root / f"workflow_{workflow_id}.json"
    if not workflow_path.exists():
        return

    workflow = read_json(workflow_path)
    tasks = workflow.setdefault("tasks", {})
    task = tasks.setdefault(task_id, {"taskId": task_id, "runs": []})
    role = str(config.get("role") or "")
    work_mode = str(config.get("workMode") or "fast")
    report_status = report_token(output_text, "Status")
    report_final = report_token(output_text, "Final Result")
    accepted = status_value == "completed" and report_is_accepted(output_text, work_mode == "strict")
    decision = "accepted" if accepted else "needs-review"
    if status_value != "completed" or report_final in {"FAIL", "BLOCKED"}:
        decision = "rejected"

    task.update(
        {
            "status": status_value,
            "lastRunId": run_id,
            "lastReportStatus": report_status,
            "lastReportFinalResult": report_final,
            "reviewDecision": decision,
            "updatedAt": now_iso(),
        }
    )
    if role == "implementer" and work_mode == "strict" and decision == "accepted":
        task.setdefault("reviews", {})
        if not all((task["reviews"].get(kind) or {}).get("reviewDecision") == "accepted" for kind in STRICT_REVIEW_KINDS):
            task["reviewDecision"] = "pending-review"
    if role == "reviewer":
        review_for_task_id = str(config.get("reviewForTaskId") or "")
        review_kind = str(config.get("reviewKind") or "")
        if review_for_task_id and review_kind:
            target = tasks.setdefault(review_for_task_id, {"taskId": review_for_task_id, "role": "implementer", "runs": []})
            reviews = target.setdefault("reviews", {})
            reviews[review_kind] = {
                "runId": run_id,
                "taskId": task_id,
                "status": status_value,
                "reportStatus": report_status,
                "reportFinalResult": report_final,
                "reviewDecision": decision,
                "updatedAt": now_iso(),
            }
            if all((reviews.get(kind) or {}).get("reviewDecision") == "accepted" for kind in STRICT_REVIEW_KINDS):
                target["reviewDecision"] = "accepted"
            else:
                target["reviewDecision"] = "pending-review"
    if role == "final-verifier":
        workflow["finalVerifier"] = {
            "taskId": task_id,
            "runId": run_id,
            "status": status_value,
            "reviewDecision": decision,
            "updatedAt": now_iso(),
        }

    strict_tasks = [item for item in tasks.values() if isinstance(item, dict) and item.get("workMode") == "strict"]
    pending = [
        str(item.get("taskId") or "")
        for item in strict_tasks
        if item.get("role") == "implementer" and item.get("reviewDecision") != "accepted"
    ]
    final_verifier = workflow.get("finalVerifier") if isinstance(workflow.get("finalVerifier"), dict) else {}
    workflow["finalAcceptance"] = {
        "status": "accepted" if not pending and (not strict_tasks or final_verifier.get("reviewDecision") == "accepted") else "pending-review",
        "pendingTasks": pending,
        "finalVerifierRequired": bool(strict_tasks),
        "finalVerifierAccepted": final_verifier.get("reviewDecision") == "accepted",
    }
    workflow["updatedAt"] = now_iso()
    write_json(workflow_path, workflow)
