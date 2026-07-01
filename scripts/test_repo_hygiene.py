from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def git_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def test_runtime_artifacts_are_not_tracked() -> None:
    tracked = git_files()
    offenders = [
        path
        for path in tracked
        if path.startswith(".codex/codex_claude_loop/")
        or "/__pycache__/" in path
        or path.endswith(".pyc")
        or ".pyc." in path
    ]
    assert offenders == []


def test_gitignore_blocks_runtime_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = [
        ".codex/codex_claude_loop/",
        "__pycache__/",
        "*.pyc",
        "*.pyc.*",
    ]
    missing = [pattern for pattern in required_patterns if pattern not in gitignore]
    assert missing == []


def test_gitattributes_pins_text_file_endings() -> None:
    gitattributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    required_rules = [
        "*.md text eol=lf",
        "*.json text eol=lf",
        "*.py text eol=lf",
        "*.mjs text eol=lf",
        "*.ps1 text eol=lf",
    ]
    missing = [rule for rule in required_rules if rule not in gitattributes]
    assert missing == []


if __name__ == "__main__":
    test_runtime_artifacts_are_not_tracked()
    test_gitignore_blocks_runtime_artifacts()
    test_gitattributes_pins_text_file_endings()
    print("ok")
