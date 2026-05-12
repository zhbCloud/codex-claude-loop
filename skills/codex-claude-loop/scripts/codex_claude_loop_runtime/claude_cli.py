from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import DelegateError, has_required_headings
from .io_utils import write_text


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
) -> dict[str, Any]:
    claude = shutil.which("claude")
    if not claude:
        raise DelegateError("Claude CLI was not found on PATH.")

    args = build_claude_args(session_id, resume, session_name, model, bypass_permissions)
    assistant_texts: list[str] = []
    saw_result_success = False
    raw_non_json: list[str] = []

    stream_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with stream_path.open("w", encoding="utf-8", newline="\n") as stream, trace_path.open("w", encoding="utf-8", newline="\n") as trace:
        trace.write(f"[claude] {claude} {' '.join(args)}\n")
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
            stream.write(line + "\n")
            stream.flush()
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raw_non_json.append(line)
                trace.write("[raw] non-json output\n")
                trace.flush()
                continue
            record_type = str(record.get("type", ""))
            trace.write(f"[{record_type or 'record'}]\n")
            if record_type == "assistant":
                assistant_texts.extend(_extract_text(record))
            if record_type == "result" and record.get("subtype") == "success":
                saw_result_success = True
            trace.flush()
        exit_code = process.wait()

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
