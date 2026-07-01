from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MACOS_ROOT = (
    REPO_ROOT
    / "plugins"
    / "codex-claude-loop"
    / "skills"
    / "codex-claude-loop"
    / "macos_scripts"
)
RUNTIME_ROOT = MACOS_ROOT.parent / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))


def test_macos_runtime_and_core_wrappers() -> None:
    runtime = (MACOS_ROOT / "_runtime.sh").read_text(encoding="utf-8")
    assert runtime.startswith("#!/bin/zsh\n")
    assert "python3" in runtime
    assert "sys.version_info >= (3, 10)" in runtime

    wrappers = {
        "delegate_to_claude.sh": "delegate_to_claude.py",
        "validate_delegate_task.sh": "validate_delegate_task.py",
    }
    for name, python_script in wrappers.items():
        text = (MACOS_ROOT / name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/zsh\n"), name
        assert f'_runtime.sh" {python_script} "$@"' in text, name


def test_macos_verification_wrappers() -> None:
    wrappers = {
        "verify_artifacts.sh": "verify_artifacts.py",
        "verify_workflow.sh": "verify_workflow.py",
    }
    for name, python_script in wrappers.items():
        text = (MACOS_ROOT / name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/zsh\n"), name
        assert f'_runtime.sh" {python_script} "$@"' in text, name


def test_macos_scripts_use_lf_and_executable_git_mode() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    assert "*.yml text eol=lf" in attributes

    scripts = sorted(MACOS_ROOT.glob("*.sh"))
    assert scripts
    for script in scripts:
        assert b"\r\n" not in script.read_bytes(), script.name
        relative = script.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "ls-files", "--stage", "--", relative],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        assert result.stdout.startswith("100755 "), f"{script.name}: {result.stdout!r}"


def test_ci_validates_macos_scripts() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "validate-plugin.yml").read_text(encoding="utf-8")
    assert "macos-latest" in workflow
    assert "zsh -n" in workflow
    assert "test_macos_compatibility.py" in workflow


def test_manifest_and_readmes_publish_macos_support() -> None:
    manifest_path = (
        REPO_ROOT
        / "plugins"
        / "codex-claude-loop"
        / ".codex-plugin"
        / "plugin.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.4.2"
    assert "Windows and macOS" in manifest["description"]
    assert "Windows and macOS" in manifest["interface"]["longDescription"]

    for name in ("README.md", "README-ZH.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "0.4.2" in text, name


def test_claude_cli_resolution_uses_path_before_macos_fallbacks() -> None:
    from codex_claude_loop_runtime.claude_cli import resolve_claude_cli

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        path_dir = root / "path-bin"
        fallback_dir = root / "homebrew-bin"
        path_dir.mkdir()
        fallback_dir.mkdir()
        path_claude = path_dir / ("claude.exe" if os.name == "nt" else "claude")
        fallback_claude = fallback_dir / ("claude.exe" if os.name == "nt" else "claude")
        path_claude.write_text("", encoding="utf-8")
        fallback_claude.write_text("", encoding="utf-8")

        resolved = resolve_claude_cli(
            path=str(path_dir),
            fallback_paths=[fallback_claude],
        )
        assert Path(resolved).resolve() == path_claude.resolve()

        resolved = resolve_claude_cli(
            path=str(root / "missing"),
            fallback_paths=[fallback_claude],
        )
        assert Path(resolved).resolve() == fallback_claude.resolve()

        try:
            resolve_claude_cli(path=str(root / "missing"), fallback_paths=[])
        except RuntimeError as exc:
            assert "Claude CLI was not found" in str(exc)
        else:
            raise AssertionError("resolve_claude_cli should fail when claude is unavailable")


if __name__ == "__main__":
    test_macos_runtime_and_core_wrappers()
    test_macos_verification_wrappers()
    test_macos_scripts_use_lf_and_executable_git_mode()
    test_ci_validates_macos_scripts()
    test_manifest_and_readmes_publish_macos_support()
    test_claude_cli_resolution_uses_path_before_macos_fallbacks()
    print("ok")
