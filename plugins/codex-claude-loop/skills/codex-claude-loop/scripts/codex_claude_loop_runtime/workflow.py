from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .common import ARTIFACT_SCHEMA_VERSION, INVOCATION_CONTRACT, STRICT_REVIEW_KINDS, now_iso
from .io_utils import file_lock, read_json, write_json
from .reports import report_is_accepted, report_token


def latest_task_run(task: dict[str, Any]) -> str:
    runs = task.get("runs")
    return str(runs[-1]) if isinstance(runs, list) and runs else str(task.get("lastRunId") or "")


def _run_status(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("statusPath")
    if not value or not Path(str(value)).is_file():
        return {}
    status = read_json(Path(str(value)))
    return status if isinstance(status, dict) else {}


def _started_after_completion(run: dict[str, Any], predecessor: dict[str, Any]) -> bool:
    status = _run_status(run)
    preceding_status = _run_status(predecessor)
    if preceding_status.get("status") != "completed":
        return False
    try:
        started = datetime.fromisoformat(str(status.get("startedAt") or "").replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(preceding_status.get("completedAt") or "").replace("Z", "+00:00"))
        return started >= completed
    except (TypeError, ValueError):
        return False


def review_is_current(workflow: dict[str, Any], task: dict[str, Any], kind: str) -> bool:
    reviews = task.get("reviews") if isinstance(task.get("reviews"), dict) else {}
    review = reviews.get(kind) if isinstance(reviews.get(kind), dict) else {}
    if review.get("reviewDecision") != "accepted" or task.get("status") != "completed":
        return False
    runs = {str(run.get("runId")): run for run in workflow.get("runs", []) if isinstance(run, dict)}
    implementation = runs.get(latest_task_run(task))
    evidence = runs.get(str(review.get("runId") or ""))
    if implementation is None or evidence is None or not _started_after_completion(evidence, implementation):
        return False
    reviewer = workflow.get("tasks", {}).get(str(review.get("taskId") or ""), {})
    return (
        latest_task_run(reviewer) == review.get("runId")
        and evidence.get("role") == "reviewer"
        and evidence.get("reviewForTaskId") == task.get("taskId")
        and evidence.get("reviewKind") == kind
        and reviewer.get("status") == "completed"
    )


def final_verifier_is_current(workflow: dict[str, Any]) -> bool:
    verifier = workflow.get("finalVerifier") if isinstance(workflow.get("finalVerifier"), dict) else {}
    if verifier.get("reviewDecision") != "accepted":
        return False
    tasks = workflow.get("tasks", {})
    verifier_task = tasks.get(str(verifier.get("taskId") or ""), {})
    if latest_task_run(verifier_task) != verifier.get("runId") or verifier_task.get("status") != "completed":
        return False
    runs = {str(run.get("runId")): run for run in workflow.get("runs", []) if isinstance(run, dict)}
    verifier_run = runs.get(str(verifier.get("runId") or ""))
    if verifier_task.get("role") != "final-verifier" or verifier_run is None:
        return False
    for task in tasks.values():
        if not isinstance(task, dict) or task.get("role") not in {"implementer", "reviewer"}:
            continue
        # Only the current accepted reviews are inputs to final verification;
        # superseded read-only reviewers may finish later without invalidating it.
        if task.get("role") == "reviewer":
            target = tasks.get(str(task.get("reviewForTaskId") or ""), {})
            evidence = (target.get("reviews") or {}).get(str(task.get("reviewKind") or ""), {})
            if evidence.get("runId") != latest_task_run(task):
                continue
        predecessor = runs.get(latest_task_run(task))
        if predecessor is None or task.get("status") != "completed":
            return False
        if not _started_after_completion(verifier_run, predecessor):
            return False
        if task.get("role") == "implementer" and task.get("workMode") == "strict":
            if not all(review_is_current(workflow, task, kind) for kind in STRICT_REVIEW_KINDS):
                return False
    return True


def _refresh_final_acceptance(workflow: dict[str, Any]) -> None:
    strict_tasks = [task for task in workflow.get("tasks", {}).values() if isinstance(task, dict) and task.get("workMode") == "strict"]
    pending = [str(task.get("taskId") or "") for task in strict_tasks
               if task.get("role") == "implementer" and task.get("reviewDecision") != "accepted"]
    final_accepted = final_verifier_is_current(workflow)
    workflow["finalAcceptance"] = {
        "status": "accepted" if not pending and (not strict_tasks or final_accepted) else "pending-review",
        "pendingTasks": pending,
        "finalVerifierRequired": bool(strict_tasks),
        "finalVerifierAccepted": final_accepted,
    }


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
    with file_lock(workflow_path.with_suffix(".json.lock")):
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
        if role == "implementer" and work_mode == "strict":
            task["reviews"] = {}
            task["reviewDecision"] = "pending-review"
        elif role == "reviewer" and review_for_task_id:
            target = workflow["tasks"].get(review_for_task_id)
            if isinstance(target, dict):
                target.setdefault("reviews", {}).pop(review_kind, None)
                target["reviewDecision"] = "pending-review"
        if role in {"implementer", "reviewer", "final-verifier"}:
            workflow.pop("finalVerifier", None)
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
        _refresh_final_acceptance(workflow)
        write_json(workflow_path, workflow)


def update_workflow_status(context: dict[str, Any], status_value: str) -> None:
    config = dict(context["config"])
    workflow_id = str(config.get("workflowId") or "")
    run_id = str(config.get("runId") or "")
    if not workflow_id or not run_id:
        return

    artifact_root = Path(context["status_path"]).resolve().parent
    workflow_path = artifact_root / f"workflow_{workflow_id}.json"
    with file_lock(workflow_path.with_suffix(".json.lock")):
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
    with file_lock(workflow_path.with_suffix(".json.lock")):
        if not workflow_path.exists():
            return

        workflow = read_json(workflow_path)
        tasks = workflow.setdefault("tasks", {})
        task = tasks.setdefault(task_id, {"taskId": task_id, "runs": []})
        for item in workflow.get("runs", []):
            if isinstance(item, dict) and item.get("runId") == run_id:
                item["status"] = status_value
        if latest_task_run(task) != run_id:
            # An older attempt may finish late; it must not replace current task evidence.
            write_json(workflow_path, workflow)
            return
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
            if not all(review_is_current(workflow, task, kind) for kind in STRICT_REVIEW_KINDS):
                task["reviewDecision"] = "pending-review"
        if role == "reviewer":
            review_for_task_id = str(config.get("reviewForTaskId") or "")
            review_kind = str(config.get("reviewKind") or "")
            if review_for_task_id and review_kind:
                target = tasks.setdefault(review_for_task_id, {"taskId": review_for_task_id, "role": "implementer", "runs": []})
                reviews = target.setdefault("reviews", {})
                positions = {str(run.get("runId")): index for index, run in enumerate(workflow.get("runs", [])) if isinstance(run, dict)}
                current_review = reviews.get(review_kind) or {}
                if positions.get(str(current_review.get("runId") or ""), -1) > positions.get(run_id, -1):
                    _refresh_final_acceptance(workflow)
                    write_json(workflow_path, workflow)
                    return
                reviews[review_kind] = {
                    "runId": run_id,
                    "taskId": task_id,
                    "status": status_value,
                    "reportStatus": report_status,
                    "reportFinalResult": report_final,
                    "reviewDecision": decision,
                    "updatedAt": now_iso(),
                }
                if not review_is_current(workflow, target, review_kind):
                    reviews[review_kind]["reviewDecision"] = "needs-review"
                if all(review_is_current(workflow, target, kind) for kind in STRICT_REVIEW_KINDS):
                    target["reviewDecision"] = "accepted"
                else:
                    target["reviewDecision"] = "pending-review"
        if role == "final-verifier":
            positions = {str(run.get("runId")): index for index, run in enumerate(workflow.get("runs", [])) if isinstance(run, dict)}
            current_verifier = workflow.get("finalVerifier") or {}
            if positions.get(str(current_verifier.get("runId") or ""), -1) > positions.get(run_id, -1):
                _refresh_final_acceptance(workflow)
                write_json(workflow_path, workflow)
                return
            workflow["finalVerifier"] = {
                "taskId": task_id,
                "runId": run_id,
                "status": status_value,
                "reviewDecision": decision,
                "updatedAt": now_iso(),
            }
            if not final_verifier_is_current(workflow):
                workflow["finalVerifier"]["reviewDecision"] = "needs-review"

        _refresh_final_acceptance(workflow)
        workflow["updatedAt"] = now_iso()
        write_json(workflow_path, workflow)
