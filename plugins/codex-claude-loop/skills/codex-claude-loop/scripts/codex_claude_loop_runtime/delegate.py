from __future__ import annotations

import argparse
import os
import posixpath
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .claude_cli import run_claude, write_startup_failure
from .common import (
    ARTIFACT_SCHEMA_VERSION,
    CHILD_MARKER_NAME,
    CHILD_MARKER_VALUE,
    DelegateError,
    INVOCATION_CONTRACT,
    STRICT_REVIEW_KINDS,
    WORK_MODES,
    has_required_headings,
    now_iso,
)
from .fingerprint import safe_key, task_fingerprint
from .io_utils import ensure_writable, read_json, read_text, write_json, write_text
from .reports import report_is_accepted
from .sessions import SessionLease, acquire_session, commit_session, release_session
from .state_machine import state_for_task_mode
from .task_contract import has_task_contract, validate_task_text
from .workflow import finalize_workflow_record, update_workflow_record, update_workflow_status, write_final_gate

ALLOWED_ROLES = {"planner", "implementer", "researcher", "reviewer", "final-verifier"}


def repo_root() -> Path:
    return Path.cwd().resolve()


def default_artifact_root(root: Path) -> Path:
    return root / ".codex" / "codex_claude_loop" / "claude-delegate"


def session_root(root: Path) -> Path:
    return root / ".codex" / "codex_claude_loop" / "session-pools"


def normalize_items(values: list[str] | None) -> list[str]:
    items: list[str] = []
    for value in values or []:
        for part in str(value).split(";"):
            part = part.strip()
            if part:
                items.append(part)
    return items


def safe_identifier(value: str, default_prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-")
    if cleaned:
        return cleaned
    return f"{default_prefix}-{uuid.uuid4().hex[:8]}"


def effective_work_mode(ns: argparse.Namespace | SimpleNamespace, task_text: str) -> str:
    requested = str(getattr(ns, "work_mode", "auto") or "auto").lower()
    if requested in {"fast", "strict"}:
        return requested
    if getattr(ns, "allow_parallel", False):
        return "strict"
    if str(getattr(ns, "role", "") or "") in {"reviewer", "final-verifier"}:
        return "strict"
    if has_task_contract(task_text):
        return "strict"
    return "fast"


def build_prompt(ns: argparse.Namespace, task_text: str, run_id: str, allowed_paths: list[str], validation_commands: list[str]) -> str:
    workflow_state = state_for_task_mode(ns.task_mode)
    allowed = "\n".join(f"- {item}" for item in allowed_paths) or "- Not specified; ask Codex main thread to narrow scope if needed."
    validation = "\n".join(f"- {item}" for item in validation_commands) or "- Not specified; explain what validation is appropriate and whether it was run."
    if ns.validation_phase == "light":
        validation_policy = (
            "Validation phase is LIGHT. Prefer fast checks (syntax, quick smoke checks, targeted checks). "
            "Do not run heavy full-project builds unless explicitly required by the task."
        )
    else:
        validation_policy = "Validation phase is FULL. Run the provided full validation commands whenever possible."
    if ns.effective_work_mode == "strict":
        report_contract = """Your final answer must contain these exact headings:

Process Log
Status
Role
Summary
Changed Files
Verification
Findings
Final Result
Risks Or Follow-ups

Status and Final Result must use one of:
PASS
PASS_WITH_CONCERNS
NEEDS_CONTEXT
BLOCKED
FAIL

Role must match the delegated role."""
    else:
        report_contract = """Your final answer must contain these exact headings:

Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups

Final Result should be PASS, PASS_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED, or FAIL."""
    return f"""# Codex Claude Loop Delegate Task

RunId: {run_id}
WorkflowId: {ns.workflow_id}
TaskId: {ns.task_id}
Role: {ns.role}
TaskMode: {ns.task_mode}
WorkMode: {ns.effective_work_mode}
WorkflowState: {workflow_state}
Round: {ns.round}/{ns.max_round}

## Role Boundary

You are Claude executing inside the Codex Claude Loop delegate runtime.
Codex main thread owns final acceptance. You may report delegate success, but you must not declare the overall user request accepted.

## Scope Lock

Allowed paths:
{allowed}

Stay inside the allowed paths. If you need to touch anything else, stop and explain why.

## Validation Commands

{validation}

Run these commands when possible. If blocked, explain the blocker and whether it relates to your changes.
{validation_policy}

## Required Report Headings

{report_contract}

## Stable Summary Requirement

Include a concise stable summary covering requirement summary, decisions, key files, known risks, and next action.

## Task

{task_text}
"""


def git_changed_files(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return []
    result = subprocess.run(["git", "diff", "--name-only"], cwd=str(root), text=True, capture_output=True)
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _normalize_allowed_path(root: Path, allowed_path: str) -> str:
    raw = str(allowed_path).replace("\\", "/").strip()
    if raw in {"", ".", "./"}:
        return ""

    candidate_path = Path(raw)
    if candidate_path.is_absolute():
        try:
            raw = candidate_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return posixpath.normpath(raw).strip("/").lower()

    normalized = posixpath.normpath(raw).strip("/").lower()
    if normalized == ".":
        return ""
    return normalized


def normalize_allowed_paths(root: Path, allowed_paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in allowed_paths:
        value = _normalize_allowed_path(root, item)
        if value not in normalized:
            normalized.append(value)
    return normalized


def out_of_scope_files(changed_files: list[str], allowed_paths: list[str], root: Path | None = None) -> list[str]:
    if not allowed_paths:
        return []
    normalized_allowed = normalize_allowed_paths(root or repo_root(), allowed_paths)
    if "" in normalized_allowed:
        return []
    out: list[str] = []
    for file in changed_files:
        candidate = posixpath.normpath(file.replace("\\", "/")).strip("/").lower()
        if not any(candidate == prefix or candidate.startswith(prefix.rstrip("/") + "/") for prefix in normalized_allowed):
            out.append(file)
    return out


def dry_run_report(run_id: str, prompt_path: Path) -> str:
    return f"""Process Log
- Dry run enabled; Claude was not invoked.
- Delegate artifacts were generated.

Status
PASS

Role
implementer

Summary
Dry run completed for RunId {run_id}.

Changed Files
None

Verification
- dry-run artifact generation only

Findings
- No findings in dry-run mode.

Final Result
PASS

Risks Or Follow-ups
- Inspect prompt before running without -DryRun: {prompt_path}
"""


def prepare_run(ns: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get(CHILD_MARKER_NAME) != CHILD_MARKER_VALUE:
        raise DelegateError(
            f"Direct delegate invocation is forbidden. Run inside a Codex child thread with {CHILD_MARKER_NAME}={CHILD_MARKER_VALUE}."
        )
    if ns.round < 1 or ns.round > ns.max_round:
        raise DelegateError(f"Round {ns.round} exceeds max round {ns.max_round}.")
    if not str(ns.workflow_id).strip():
        raise DelegateError("WorkflowId is required.")
    if not str(ns.task_id).strip():
        raise DelegateError("TaskId is required.")
    if not str(ns.role).strip():
        raise DelegateError("Role is required.")
    if ns.role not in ALLOWED_ROLES:
        raise DelegateError(f"Role must be one of: {', '.join(sorted(ALLOWED_ROLES))}.")
    if ns.work_mode not in WORK_MODES:
        raise DelegateError("WorkMode must be one of: " + ", ".join(WORK_MODES) + ".")
    if ns.role == "reviewer":
        if not str(ns.review_for_task_id).strip():
            raise DelegateError("ReviewForTaskId is required when Role is reviewer.")
        if str(ns.review_kind).strip() not in STRICT_REVIEW_KINDS:
            raise DelegateError("ReviewKind must be one of " + ", ".join(STRICT_REVIEW_KINDS) + " when Role is reviewer.")
    if ns.allow_parallel and not str(ns.scope).strip():
        raise DelegateError("Scope is required when AllowParallel is enabled.")
    if ns.validation_phase not in {"light", "full"}:
        raise DelegateError("ValidationPhase must be either 'light' or 'full'.")
    workflow_id = safe_identifier(ns.workflow_id, "workflow")
    task_id = safe_identifier(ns.task_id, "task")
    ns.workflow_id = workflow_id
    ns.task_id = task_id

    root = repo_root()
    task_file = Path(ns.task_file)
    if not task_file.exists():
        raise DelegateError(f"Task file not found: {task_file}")
    task_text = read_text(task_file)
    if not task_text.strip():
        raise DelegateError("Task file is empty.")

    allowed_paths = normalize_items(ns.allowed_path)
    validation_commands = normalize_items(ns.validation_command)
    test_commands = normalize_items(ns.tests)
    depends_on = normalize_items(ns.depends_on)
    if test_commands:
        for command in test_commands:
            if command not in validation_commands:
                validation_commands.append(command)
    ns.effective_work_mode = effective_work_mode(ns, task_text)
    if ns.effective_work_mode == "strict":
        validate_task_text(task_text, test_commands)
    session_key = safe_key(ns.session_key or f"{ns.task_mode}-default")
    fingerprint = task_fingerprint(ns.task_mode, task_text, allowed_paths, validation_commands, session_key)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + "_" + uuid.uuid4().hex[:8]
    artifact_root = Path(ns.artifact_root).resolve() if ns.artifact_root else default_artifact_root(root)
    artifact_root.mkdir(parents=True, exist_ok=True)

    output_path = artifact_root / f"claude_{run_id}.md"
    config_path = artifact_root / f"config_{run_id}.json"
    status_path = artifact_root / f"status_{run_id}.json"
    prompt_path = artifact_root / f"prompt_{run_id}.md"
    stream_path = artifact_root / f"stream_{run_id}.jsonl"
    trace_path = artifact_root / f"trace_{run_id}.log"
    final_gate_path = artifact_root / f"final_gate_{run_id}.json"
    for path in (output_path, config_path, status_path, prompt_path, stream_path, trace_path, final_gate_path):
        ensure_writable(path)

    prompt = build_prompt(ns, task_text, run_id, allowed_paths, validation_commands)
    write_text(prompt_path, prompt)

    config: dict[str, Any] = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "invocationContract": INVOCATION_CONTRACT,
        "runId": run_id,
        "workflowId": ns.workflow_id,
        "taskId": ns.task_id,
        "role": ns.role,
        "workMode": ns.effective_work_mode,
        "requestedWorkMode": ns.work_mode,
        "reviewForTaskId": ns.review_for_task_id,
        "reviewKind": ns.review_kind,
        "dependsOn": depends_on,
        "scope": ns.scope,
        "validationPhase": ns.validation_phase,
        "repoRoot": str(root),
        "taskFile": str(task_file.resolve()),
        "taskMode": ns.task_mode,
        "round": ns.round,
        "maxRound": ns.max_round,
        "sessionMode": ns.session_mode,
        "sessionKey": session_key,
        "fingerprint": fingerprint,
        "allowedPaths": allowed_paths,
        "validationCommands": validation_commands,
        "tests": test_commands,
        "childThreadMarkerName": CHILD_MARKER_NAME,
        "childThreadMarkerValidated": True,
        "configPath": str(config_path),
        "promptPath": str(prompt_path),
        "outputPath": str(output_path),
        "statusPath": str(status_path),
        "streamPath": str(stream_path),
        "tracePath": str(trace_path),
        "finalGatePath": str(final_gate_path),
    }
    status: dict[str, Any] = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "runId": run_id,
        "workflowId": ns.workflow_id,
        "taskId": ns.task_id,
        "role": ns.role,
        "status": "queued" if ns.prepare_only else "starting",
        "phase": "queued" if ns.prepare_only else "preparing",
        "startedAt": now_iso(),
        "updatedAt": now_iso(),
        "heartbeatAt": now_iso(),
        "childThreadMarkerValidated": True,
        "exitCode": None,
        "statusPath": str(status_path),
        "streamPath": str(stream_path),
        "outputPath": str(output_path),
        "configPath": str(config_path),
        "promptPath": str(prompt_path),
        "lastStreamAt": None,
        "lastStreamRecordType": None,
        "lastAssistantTextPreview": "",
        "streamRecords": 0,
    }
    config["runtimeOptions"] = {
        "model": ns.model,
        "namePrefix": ns.name_prefix,
        "maxParallel": ns.max_parallel,
        "leaseTtlSeconds": ns.lease_ttl_seconds,
        "leaseWaitSeconds": ns.lease_wait_seconds,
        "maxRetryCount": ns.max_retry_count,
        "bypassPermissions": bool(ns.bypass_permissions),
        "dryRun": bool(ns.dry_run),
        "allowParallel": bool(ns.allow_parallel),
        "validationPhase": str(ns.validation_phase),
    }
    write_json(config_path, config)
    write_json(status_path, status)
    update_workflow_record(
        artifact_root,
        ns.workflow_id,
        run_id,
        ns.task_id,
        ns.role,
        ns.effective_work_mode,
        ns.scope,
        allowed_paths,
        validation_commands,
        test_commands,
        depends_on,
        bool(ns.allow_parallel),
        ns.review_for_task_id,
        ns.review_kind,
        str(config_path),
        str(status_path),
        str(prompt_path),
        str(output_path),
        "queued" if ns.prepare_only else "starting",
    )

    return {
        "root": root,
        "run_id": run_id,
        "session_key": session_key,
        "fingerprint": fingerprint,
        "allowed_paths": allowed_paths,
        "validation_commands": validation_commands,
        "prompt": prompt,
        "config": config,
        "output_path": output_path,
        "config_path": config_path,
        "status_path": status_path,
        "prompt_path": prompt_path,
        "stream_path": stream_path,
        "trace_path": trace_path,
        "final_gate_path": final_gate_path,
    }


def load_prepared_run(config_path: Path) -> tuple[SimpleNamespace, dict[str, Any]]:
    config = read_json(config_path)
    runtime_options = config.get("runtimeOptions") if isinstance(config.get("runtimeOptions"), dict) else {}
    ns = SimpleNamespace(
        task_mode=config["taskMode"],
        session_mode=config["sessionMode"],
        round=int(config["round"]),
        max_round=int(config["maxRound"]),
        max_parallel=int(runtime_options.get("maxParallel", 5)),
        lease_ttl_seconds=int(runtime_options.get("leaseTtlSeconds", 7200)),
        lease_wait_seconds=int(runtime_options.get("leaseWaitSeconds", 60)),
        max_retry_count=int(runtime_options.get("maxRetryCount", 1)),
        name_prefix=str(runtime_options.get("namePrefix", "codex-claude-loop")),
        model=str(runtime_options.get("model", "")),
        bypass_permissions=bool(runtime_options.get("bypassPermissions", False)),
        dry_run=bool(runtime_options.get("dryRun", False)),
        allow_parallel=bool(runtime_options.get("allowParallel", False)),
        workflow_id=str(config.get("workflowId") or ""),
        task_id=str(config.get("taskId") or ""),
        role=str(config.get("role") or ""),
        work_mode=str(config.get("workMode") or "fast"),
        effective_work_mode=str(config.get("workMode") or "fast"),
        requested_work_mode=str(config.get("requestedWorkMode") or config.get("workMode") or "auto"),
        review_for_task_id=str(config.get("reviewForTaskId") or ""),
        review_kind=str(config.get("reviewKind") or ""),
        scope=str(config.get("scope") or ""),
        validation_phase=str(config.get("validationPhase") or runtime_options.get("validationPhase") or "light"),
    )
    context = {
        "root": Path(config["repoRoot"]),
        "run_id": config["runId"],
        "session_key": config["sessionKey"],
        "fingerprint": config["fingerprint"],
        "allowed_paths": list(config.get("allowedPaths") or []),
        "validation_commands": list(config.get("validationCommands") or []),
        "prompt": read_text(Path(config["promptPath"])),
        "config": config,
        "output_path": Path(config["outputPath"]),
        "config_path": Path(config["configPath"]),
        "status_path": Path(config["statusPath"]),
        "prompt_path": Path(config["promptPath"]),
        "stream_path": Path(config["streamPath"]),
        "trace_path": Path(config["tracePath"]),
        "final_gate_path": Path(config.get("finalGatePath") or (Path(config["statusPath"]).resolve().parent / f"final_gate_{config['runId']}.json")),
    }
    return ns, context


def execute_prepared(ns: argparse.Namespace | SimpleNamespace, context: dict[str, Any]) -> int:
    root = Path(context["root"])
    run_id = str(context["run_id"])
    session_key = str(context["session_key"])
    fingerprint = str(context["fingerprint"])
    allowed_paths = list(context["allowed_paths"])
    prompt = str(context["prompt"])
    config = dict(context["config"])
    output_path = Path(context["output_path"])
    config_path = Path(context["config_path"])
    status_path = Path(context["status_path"])
    prompt_path = Path(context["prompt_path"])
    stream_path = Path(context["stream_path"])
    trace_path = Path(context["trace_path"])
    final_gate_path = Path(context["final_gate_path"])
    status = read_json(status_path) if status_path.exists() else {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "runId": run_id,
        "status": "starting",
        "startedAt": now_iso(),
        "childThreadMarkerValidated": True,
        "exitCode": None,
    }
    lease: SessionLease | None = None
    exit_code = 1
    try:
        status.update({"status": "leasing", "phase": "leasing_session", "updatedAt": now_iso(), "heartbeatAt": now_iso()})
        write_json(status_path, status)
        update_workflow_status(context, "leasing")
        lease = acquire_session(
            session_root(root),
            session_key,
            ns.session_mode,
            run_id,
            fingerprint,
            ns.max_parallel,
            ns.lease_ttl_seconds,
            ns.lease_wait_seconds,
        )
        config.update({"sessionId": lease.session_id, "resume": lease.resume, "slotName": lease.slot_name})
        write_json(config_path, config)
        status.update(
            {
                "status": "running",
                "phase": "claude_running" if not ns.dry_run else "dry_run",
                "updatedAt": now_iso(),
                "heartbeatAt": now_iso(),
                "sessionId": lease.session_id,
                "resume": lease.resume,
            }
        )
        write_json(status_path, status)
        update_workflow_status(context, "running")

        if ns.dry_run:
            write_text(output_path, dry_run_report(run_id, prompt_path))
            write_text(stream_path, "")
            write_text(trace_path, f"[dry-run] {run_id}\n")
            result = {"exitCode": 0, "finalText": read_text(output_path), "sawResultSuccess": True, "hasRequiredHeadings": True}
        else:
            result = run_claude(
                prompt,
                root,
                stream_path,
                trace_path,
                lease.session_id,
                lease.resume,
                f"{ns.name_prefix}-{session_key}",
                ns.model,
                ns.bypass_permissions,
                status_path,
            )
            final_text = str(result.get("finalText") or "").strip()
            if not final_text:
                final_text = "Claude finished without assistant text."
            write_text(output_path, final_text)

        changed_files = git_changed_files(root)
        out_of_scope = out_of_scope_files(changed_files, allowed_paths, root)
        output_text = read_text(output_path)
        work_mode = str(config.get("workMode") or getattr(ns, "effective_work_mode", "fast") or "fast")
        strict_mode = work_mode == "strict"
        has_headings = has_required_headings(output_text, strict=strict_mode)
        exit_code = int(result.get("exitCode") or 0)
        failed_reasons: list[str] = []
        if exit_code != 0:
            failed_reasons.append(f"Claude exited with code {exit_code}.")
        if not has_headings:
            failed_reasons.append("Claude report is missing required headings.")
        if strict_mode and not report_is_accepted(output_text, strict=True):
            failed_reasons.append("Strict report status/final result is not accepted.")
        if out_of_scope:
            failed_reasons.append("Changed files outside allowed paths: " + ", ".join(out_of_scope))
            write_text(
                output_path,
                output_text
                + "\n\nScope Check\n"
                + "FAILED: changed files outside allowed paths:\n"
                + "\n".join(f"- {item}" for item in out_of_scope)
                + "\n",
            )

        if failed_reasons:
            exit_code = exit_code or 2
            status_value = "failed"
        else:
            status_value = "completed"
            exit_code = 0
            if not ns.dry_run:
                commit_session(lease, fingerprint, ns.lease_ttl_seconds)
        if work_mode == "fast":
            gate_status = "passed" if status_value == "completed" else "failed"
        elif ns.validation_phase == "full":
            gate_status = "passed" if status_value == "completed" else "failed"
        else:
            gate_status = "pending_full_validation"
        gate_reasons = [] if gate_status == "passed" else (failed_reasons or ["Full validation not executed in this run."])
        write_final_gate(
            final_gate_path.parent,
            run_id,
            str(config.get("workflowId") or ""),
            str(config.get("taskId") or ""),
            ns.validation_phase,
            status_value,
            gate_status,
            gate_reasons,
        )

        status.update({"phase": "finalizing", "updatedAt": now_iso(), "heartbeatAt": now_iso()})
        write_json(status_path, status)
        update_workflow_status(context, "finalizing")
        status.update(
            {
                "status": status_value,
                "phase": status_value,
                "completedAt": now_iso(),
                "updatedAt": now_iso(),
                "heartbeatAt": now_iso(),
                "exitCode": exit_code,
                "hasRequiredHeadings": has_headings,
                "changedFiles": changed_files,
                "outOfScopeFiles": out_of_scope,
                "failedReasons": failed_reasons,
                "outputPath": str(output_path),
                "configPath": str(config_path),
                "promptPath": str(prompt_path),
                "finalGatePath": str(final_gate_path),
            }
        )
        write_json(status_path, status)
        update_workflow_status(context, status_value)
        finalize_workflow_record(context, status_value, read_text(output_path))

        print(f"RunId: {run_id}")
        print(f"Status: {status_value}")
        print(f"WorkflowId: {config.get('workflowId', '')}")
        print(f"TaskId: {config.get('taskId', '')}")
        print(f"Role: {config.get('role', '')}")
        print(f"WorkMode: {work_mode}")
        print(f"ValidationPhase: {config.get('validationPhase', '')}")
        print(f"SessionKey: {session_key}")
        print(f"SessionId: {lease.session_id}")
        print(f"Resume: {lease.resume}")
        print(f"Output: {output_path}")
        print(f"StatusPath: {status_path}")
        return exit_code
    except Exception as exc:
        write_startup_failure(output_path, str(exc))
        status.update(
            {
                "status": "failed",
                "phase": "failed",
                "completedAt": now_iso(),
                "updatedAt": now_iso(),
                "heartbeatAt": now_iso(),
                "exitCode": 1,
                "failedReasons": [str(exc)],
            }
        )
        write_json(status_path, status)
        update_workflow_status(context, "failed")
        raise
    finally:
        if lease is not None:
            release_session(lease, fingerprint, ns.lease_ttl_seconds)


def run_worker(config_path: Path) -> int:
    if os.environ.get(CHILD_MARKER_NAME) != CHILD_MARKER_VALUE:
        raise DelegateError(
            f"Direct delegate invocation is forbidden. Run inside a Codex child thread with {CHILD_MARKER_NAME}={CHILD_MARKER_VALUE}."
        )
    ns, context = load_prepared_run(config_path)
    return execute_prepared(ns, context)


def run(ns: argparse.Namespace) -> int:
    context = prepare_run(ns)
    status_path = Path(context["status_path"])
    config_path = Path(context["config_path"])
    status = read_json(status_path)

    if ns.prepare_only:
        print(f"RunId: {context['run_id']}")
        print(f"Status: {status.get('status', 'queued')}")
        print(f"WorkflowId: {ns.workflow_id}")
        print(f"TaskId: {ns.task_id}")
        print(f"Role: {ns.role}")
        print(f"ValidationPhase: {ns.validation_phase}")
        print(f"ConfigPath: {config_path}")
        print(f"Output: {context['output_path']}")
        print(f"StatusPath: {status_path}")
        return 0

    return execute_prepared(ns, context)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Codex Claude Loop delegate runtime")
    p.add_argument("--task-file", required=True)
    p.add_argument("--task-mode", choices=["implementation", "rework"], default="implementation")
    p.add_argument("--work-mode", choices=["auto", "fast", "strict"], default="auto")
    p.add_argument("--session-mode", choices=["PrimaryReuse", "PrimaryAnchor", "ParallelPool"], default="PrimaryReuse")
    p.add_argument("--workflow-id", default="")
    p.add_argument("--task-id", default="")
    p.add_argument("--role", default="")
    p.add_argument("--review-for-task-id", default="")
    p.add_argument("--review-kind", choices=["", "spec", "quality"], default="")
    p.add_argument("--depends-on", action="append", default=[])
    p.add_argument("--validation-phase", choices=["light", "full"], default="light")
    p.add_argument("--session-key", default="")
    p.add_argument("--scope", default="")
    p.add_argument("--allow-parallel", action="store_true")
    p.add_argument("--allowed-path", action="append", default=[])
    p.add_argument("--validation-command", action="append", default=[])
    p.add_argument("--tests", action="append", default=[])
    p.add_argument("--artifact-root", default="")
    p.add_argument("--model", default="")
    p.add_argument("--name-prefix", default="codex-claude-loop")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--max-round", type=int, default=3)
    p.add_argument("--max-parallel", type=int, default=5)
    p.add_argument("--lease-ttl-seconds", type=int, default=7200)
    p.add_argument("--lease-wait-seconds", type=int, default=60)
    p.add_argument("--max-retry-count", type=int, default=1)
    p.add_argument("--bypass-permissions", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--worker-config", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--worker-config" in argv:
        worker_config = argv[argv.index("--worker-config") + 1]
        try:
            return run_worker(Path(worker_config))
        except DelegateError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    ns = parser().parse_args(argv)
    try:
        return run(ns)
    except DelegateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
