from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .common import REQUIRED_HEADINGS, has_required_headings
from .io_utils import read_json, read_text


def default_artifact_root() -> Path:
    return Path.cwd().resolve() / ".codex" / "codex_claude_loop" / "claude-delegate"


def latest_run_id(root: Path) -> str:
    statuses = sorted(root.glob("status_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not statuses:
        raise RuntimeError(f"No status artifacts found under {root}")
    name = statuses[0].name
    return name[len("status_") : -len(".json")]


def verify_run(root: Path, run_id: str) -> dict[str, Any]:
    status_path = root / f"status_{run_id}.json"
    config_path = root / f"config_{run_id}.json"
    output_path = root / f"claude_{run_id}.md"
    prompt_path = root / f"prompt_{run_id}.md"
    stream_path = root / f"stream_{run_id}.jsonl"
    trace_path = root / f"trace_{run_id}.log"
    missing = [str(path) for path in (status_path, config_path, output_path, prompt_path, stream_path, trace_path) if not path.exists()]
    status = read_json(status_path) if status_path.exists() else {}
    config = read_json(config_path) if config_path.exists() else {}
    output = read_text(output_path) if output_path.exists() else ""
    problems: list[str] = []
    if missing:
        problems.append("Missing artifacts: " + ", ".join(missing))
    if not status.get("childThreadMarkerValidated"):
        problems.append("status.json does not confirm child-thread marker validation")
    if not config.get("childThreadMarkerValidated"):
        problems.append("config.json does not confirm child-thread marker validation")
    if not has_required_headings(output):
        problems.append("Claude report is missing required headings: " + ", ".join(REQUIRED_HEADINGS))
    if status.get("outOfScopeFiles"):
        problems.append("Out-of-scope files changed: " + ", ".join(status["outOfScopeFiles"]))
    if status.get("status") != "completed":
        problems.append(f"Run status is {status.get('status')!r}, expected 'completed'")
    return {
        "runId": run_id,
        "ok": not problems,
        "problems": problems,
        "statusPath": str(status_path),
        "configPath": str(config_path),
        "outputPath": str(output_path),
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify Codex Claude Loop delegate artifacts")
    p.add_argument("--run-id", default="")
    p.add_argument("--artifact-root", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    root = Path(ns.artifact_root).resolve() if ns.artifact_root else default_artifact_root()
    run_id = ns.run_id or latest_run_id(root)
    result = verify_run(root, run_id)
    print(f"RunId: {result['runId']}")
    print(f"OK: {result['ok']}")
    print(f"StatusPath: {result['statusPath']}")
    print(f"OutputPath: {result['outputPath']}")
    for problem in result["problems"]:
        print(f"Problem: {problem}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
