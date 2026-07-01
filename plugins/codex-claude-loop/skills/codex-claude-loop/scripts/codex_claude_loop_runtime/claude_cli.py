from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import DelegateError, has_required_headings, now_iso
from .io_utils import read_json, write_json, write_text


DEFAULT_CLAUDE_FALLBACK_PATHS = (
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
    Path.home() / ".npm-global" / "bin" / "claude",
    Path.home() / ".local" / "bin" / "claude",
)


def build_claude_args(session_id: str, resume: bool, session_name: str, model: str, bypass_permissions: bool) -> list[str]:
    args = [
        "--verbose",
        "--print",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--name",
        session_name,
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        args.extend(["--model", model])
    args.extend(["--resume" if resume else "--session-id", session_id])
    if bypass_permissions:
        args.append("--dangerously-skip-permissions")
    return args


def resolve_claude_cli(
    path: str | None = None,
    fallback_paths: list[Path] | tuple[Path, ...] | None = None,
) -> str:
    resolved = shutil.which("claude", path=path)
    if resolved:
        return resolved

    candidates = DEFAULT_CLAUDE_FALLBACK_PATHS if fallback_paths is None else fallback_paths
    for candidate in candidates:
        if Path(candidate).is_file():
            return str(candidate)

    hint = " Ensure Claude CLI is installed and visible on PATH."
    if os.name != "nt":
        hint += " On macOS GUI sessions, restart Codex after installing Claude CLI, or ensure /opt/homebrew/bin or /usr/local/bin is available."
    raise DelegateError(f"Claude CLI was not found on PATH.{hint}")


def _extract_text(record: dict[str, Any]) -> list[str]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    items = content if isinstance(content, list) else [content]
    values: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text", "")).strip():
            values.append(str(item["text"]))
    return values


def _preview(value: str, limit: int = 500) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _update_status(status_path: Path | None, updates: dict[str, Any]) -> None:
    if status_path is None or not status_path.exists():
        return
    status = read_json(status_path)
    status.update(updates)
    status["updatedAt"] = now_iso()
    status["heartbeatAt"] = status["updatedAt"]
    write_json(status_path, status)


def run_claude(
    prompt: str,
    cwd: Path,
    stream_path: Path,
    trace_path: Path,
    session_id: str,
    resume: bool,
    session_name: str,
    model: str,
    bypass_permissions: bool,
    status_path: Path | None = None,
) -> dict[str, Any]:
    claude = resolve_claude_cli()

    args = build_claude_args(session_id, resume, session_name, model, bypass_permissions)
    assistant_texts: list[str] = []
    saw_result_success = False
    raw_non_json: list[str] = []
    stream_records = 0

    stream_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with stream_path.open("w", encoding="utf-8", newline="\n") as stream, trace_path.open("w", encoding="utf-8", newline="\n") as trace:
        trace.write(f"[claude] {claude} {' '.join(args)}\n")
        _update_status(
            status_path,
            {
                "phase": "claude_starting",
                "lastStreamAt": None,
                "lastStreamRecordType": None,
                "lastAssistantTextPreview": "",
                "lastRawOutputPreview": "",
                "streamRecords": 0,
            },
        )
        process = subprocess.Popen(
            [claude, *args],
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(prompt)
        if not prompt.endswith("\n"):
            process.stdin.write("\n")
        process.stdin.close()

        for line in process.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            stream_records += 1
            stream.write(line + "\n")
            stream.flush()
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raw_non_json.append(line)
                trace.write("[raw] non-json output\n")
                trace.flush()
                _update_status(
                    status_path,
                    {
                        "phase": "claude_running",
                        "lastStreamAt": now_iso(),
                        "lastStreamRecordType": "raw",
                        "lastRawOutputPreview": _preview(line),
                        "streamRecords": stream_records,
                    },
                )
                continue
            record_type = str(record.get("type", ""))
            trace.write(f"[{record_type or 'record'}]\n")
            if record_type == "assistant":
                extracted = _extract_text(record)
                assistant_texts.extend(extracted)
                if extracted:
                    _update_status(
                        status_path,
                        {
                            "phase": "claude_running",
                            "lastStreamAt": now_iso(),
                            "lastStreamRecordType": record_type,
                            "lastAssistantTextPreview": _preview(extracted[-1]),
                            "streamRecords": stream_records,
                        },
                    )
            if record_type == "result" and record.get("subtype") == "success":
                saw_result_success = True
            if record_type != "assistant":
                _update_status(
                    status_path,
                    {
                        "phase": "claude_running",
                        "lastStreamAt": now_iso(),
                        "lastStreamRecordType": record_type or "record",
                        "streamRecords": stream_records,
                    },
                )
            trace.flush()
        exit_code = process.wait()
        _update_status(
            status_path,
            {
                "phase": "claude_finished",
                "lastStreamAt": now_iso(),
                "streamRecords": stream_records,
            },
        )

    final_text = "\n\n".join(text.strip() for text in assistant_texts if text.strip()).strip()
    return {
        "exitCode": exit_code,
        "finalText": final_text,
        "sawResultSuccess": saw_result_success,
        "hasRequiredHeadings": has_required_headings(final_text),
        "rawNonJson": raw_non_json[:5],
    }


def write_startup_failure(output_path: Path, message: str) -> None:
    write_text(
        output_path,
        f"""Process Log
- Delegate failed before Claude execution started.

Summary
{message}

Changed Files
None

Verification
- not run; startup failed

Final Result
FAIL / NEED_HUMAN_INTERVENTION

Risks Or Follow-ups
- Resolve the startup blocker before retrying.
""",
    )
