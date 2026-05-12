from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .claude_cli import run_claude, write_startup_failure
from .common import ARTIFACT_SCHEMA_VERSION, CHILD_MARKER_NAME, CHILD_MARKER_VALUE, DelegateError, has_required_headings, now_iso
from .fingerprint import safe_key, task_fingerprint
from .io_utils import ensure_writable, read_text, write_json, write_text
from .sessions import SessionLease, acquire_session, release_session
from .state_machine import state_for_task_mode


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


def build_prompt(ns: argparse.Namespace, task_text: str, run_id: str, allowed_paths: list[str], validation_commands: list[str]) -> str:
    workflow_state = state_for_task_mode(ns.task_mode)
    allowed = "\n".join(f"- {item}" for item in allowed_paths) or "- Not specified; ask Codex main thread to narrow scope if needed."
    validation = "\n".join(f"- {item}" for item in validation_commands) or "- Not specified; explain what validation is appropriate and whether it was run."
    return f"""# Codex Claude Loop Delegate Task

RunId: {run_id}
TaskMode: {ns.task_mode}
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

## Required Report Headings

Your final answer must contain these exact headings:

Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups

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


def out_of_scope_files(changed_files: list[str], allowed_paths: list[str]) -> list[str]:
    if not allowed_paths:
        return []
    normalized_allowed = [item.replace("\\", "/").strip("/").lower() for item in allowed_paths]
    out: list[str] = []
    for file in changed_files:
        candidate = file.replace("\\", "/").strip("/").lower()
        if not any(candidate == prefix or candidate.startswith(prefix.rstrip("/") + "/") for prefix in normalized_allowed):
            out.append(file)
    return out


def dry_run_report(run_id: str, prompt_path: Path) -> str:
    return f"""Process Log
- Dry run enabled; Claude was not invoked.
- Delegate artifacts were generated.

Summary
Dry run completed for RunId {run_id}.

Changed Files
None

Verification
- dry-run artifact generation only

Final Result
PASS

Risks Or Follow-ups
- Inspect prompt before running without -DryRun: {prompt_path}
"""


def run(ns: argparse.Namespace) -> int:
    if os.environ.get(CHILD_MARKER_NAME) != CHILD_MARKER_VALUE:
        raise DelegateError(
            f"Direct delegate invocation is forbidden. Run inside a Codex child thread with {CHILD_MARKER_NAME}={CHILD_MARKER_VALUE}."
        )
    if ns.round < 1 or ns.round > ns.max_round:
        raise DelegateError(f"Round {ns.round} exceeds max round {ns.max_round}.")

    root = repo_root()
    task_file = Path(ns.task_file)
    if not task_file.exists():
        raise DelegateError(f"Task file not found: {task_file}")
    task_text = read_text(task_file)
    if not task_text.strip():
        raise DelegateError("Task file is empty.")

    allowed_paths = normalize_items(ns.allowed_path)
    validation_commands = normalize_items(ns.validation_command)
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
    for path in (output_path, config_path, status_path, prompt_path, stream_path, trace_path):
        ensure_writable(path)

    prompt = build_prompt(ns, task_text, run_id, allowed_paths, validation_commands)
    write_text(prompt_path, prompt)

    config: dict[str, Any] = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "runId": run_id,
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
        "childThreadMarkerName": CHILD_MARKER_NAME,
        "childThreadMarkerValidated": True,
        "promptPath": str(prompt_path),
        "outputPath": str(output_path),
        "statusPath": str(status_path),
        "streamPath": str(stream_path),
        "tracePath": str(trace_path),
    }
    status: dict[str, Any] = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "runId": run_id,
        "status": "starting",
        "startedAt": now_iso(),
        "childThreadMarkerValidated": True,
        "exitCode": None,
    }
    write_json(config_path, config)
    write_json(status_path, status)

    lease: SessionLease | None = None
    exit_code = 1
    try:
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

        if ns.dry_run:
            write_text(output_path, dry_run_report(run_id, prompt_path))
            write_text(stream_path, "")
            write_text(trace_path, f"[dry-run] {run_id}\n")
            result = {"exitCode": 0, "finalText": read_text(output_path), "sawResultSuccess": True, "hasRequiredHeadings": True}
        else:
            status.update({"status": "running", "updatedAt": now_iso()})
            write_json(status_path, status)
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
            )
            final_text = str(result.get("finalText") or "").strip()
            if not final_text:
                final_text = "Claude finished without assistant text."
            write_text(output_path, final_text)

        changed_files = git_changed_files(root)
        out_of_scope = out_of_scope_files(changed_files, allowed_paths)
        output_text = read_text(output_path)
        has_headings = has_required_headings(output_text)
        exit_code = int(result.get("exitCode") or 0)
        failed_reasons: list[str] = []
        if exit_code != 0:
            failed_reasons.append(f"Claude exited with code {exit_code}.")
        if not has_headings:
            failed_reasons.append("Claude report is missing required headings.")
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

        status.update(
            {
                "status": status_value,
                "completedAt": now_iso(),
                "exitCode": exit_code,
                "hasRequiredHeadings": has_headings,
                "changedFiles": changed_files,
                "outOfScopeFiles": out_of_scope,
                "failedReasons": failed_reasons,
                "outputPath": str(output_path),
                "configPath": str(config_path),
                "promptPath": str(prompt_path),
            }
        )
        write_json(status_path, status)

        print(f"RunId: {run_id}")
        print(f"Status: {status_value}")
        print(f"SessionKey: {session_key}")
        print(f"SessionId: {lease.session_id}")
        print(f"Resume: {lease.resume}")
        print(f"Output: {output_path}")
        print(f"StatusPath: {status_path}")
        return exit_code
    except Exception as exc:
        write_startup_failure(output_path, str(exc))
        status.update({"status": "failed", "completedAt": now_iso(), "exitCode": 1, "failedReasons": [str(exc)]})
        write_json(status_path, status)
        raise
    finally:
        if lease is not None:
            release_session(lease, fingerprint, ns.lease_ttl_seconds)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Codex Claude Loop delegate runtime")
    p.add_argument("--task-file", required=True)
    p.add_argument("--task-mode", choices=["plan-review", "implementation", "rework"], default="implementation")
    p.add_argument("--session-mode", choices=["PrimaryReuse", "PrimaryAnchor", "ParallelPool"], default="PrimaryReuse")
    p.add_argument("--session-key", default="")
    p.add_argument("--allowed-path", action="append", default=[])
    p.add_argument("--validation-command", action="append", default=[])
    p.add_argument("--artifact-root", default="")
    p.add_argument("--model", default="")
    p.add_argument("--name-prefix", default="codex-claude-loop")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--max-round", type=int, default=3)
    p.add_argument("--max-parallel", type=int, default=3)
    p.add_argument("--lease-ttl-seconds", type=int, default=7200)
    p.add_argument("--lease-wait-seconds", type=int, default=60)
    p.add_argument("--max-retry-count", type=int, default=1)
    p.add_argument("--bypass-permissions", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    try:
        return run(ns)
    except DelegateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

