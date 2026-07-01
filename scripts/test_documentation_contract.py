from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop"


def test_docs_describe_schema_v3_and_workflow_phases() -> None:
    documents = {
        "README.md": REPO_ROOT / "README.md",
        "README-ZH.md": REPO_ROOT / "README-ZH.md",
        "SKILL.md": SKILL_ROOT / "SKILL.md",
        "CODEX_CLAUDE_LOOP.md": SKILL_ROOT / "CODEX_CLAUDE_LOOP.md",
    }
    for name, path in documents.items():
        text = path.read_text(encoding="utf-8")
        assert "schema v3" in text.lower(), name
        for phase in ("planning", "dispatching", "reviewing", "finishing"):
            assert phase in text.lower(), name


def test_skill_docs_describe_windows_and_macos_boundary() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "CODEX_CLAUDE_LOOP.md").read_text(encoding="utf-8")
    for name, text in {
        "SKILL.md": skill,
        "CODEX_CLAUDE_LOOP.md": contract,
    }.items():
        assert "windows_scripts/delegate_to_claude.ps1" in text, name
        assert "macos_scripts/delegate_to_claude.sh" in text, name
        assert "Linux" in text, name
        assert "0.4.2" in text, name
        assert "restart Codex Desktop" in text, name


def test_readmes_describe_windows_and_macos_boundary() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (REPO_ROOT / "README-ZH.md").read_text(encoding="utf-8")
    assert "Windows and macOS" in readme
    assert "Windows 和 macOS" in zh_readme
    for name, text in {
        "README.md": readme,
        "README-ZH.md": zh_readme,
    }.items():
        assert "macos_scripts/delegate_to_claude.sh" in text, name
        assert "Linux" in text, name


def test_ai_install_supports_windows_and_macos() -> None:
    install = (REPO_ROOT / "AI_INSTALL.md").read_text(encoding="utf-8")
    assert "Windows 和 macOS" in install
    assert "macos_scripts/delegate_to_claude.sh" in install
    assert "非 Windows 环境必须停止" not in install
    assert "本插件当前只支持 Windows。" not in install


def test_doctor_describes_windows_check_not_plugin_boundary() -> None:
    doctor = (REPO_ROOT / "scripts" / "doctor.ps1").read_text(encoding="utf-8")
    assert "Windows-only" not in doctor
    assert "This doctor runs on Windows" in doctor


def test_docs_describe_update_requirement_for_schema_v3() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (REPO_ROOT / "README-ZH.md").read_text(encoding="utf-8")
    install = (REPO_ROOT / "AI_INSTALL.md").read_text(encoding="utf-8")
    for name, text in {
        "README.md": readme,
        "README-ZH.md": zh_readme,
        "AI_INSTALL.md": install,
    }.items():
        assert "0.4.1" in text, name
        assert "schema v3" in text.lower(), name
        assert "codex debug prompt-input" in text, name
    assert "restart Codex Desktop" in readme
    assert "重启 Codex Desktop" in zh_readme


if __name__ == "__main__":
    test_docs_describe_schema_v3_and_workflow_phases()
    test_skill_docs_describe_windows_and_macos_boundary()
    test_readmes_describe_windows_and_macos_boundary()
    test_ai_install_supports_windows_and_macos()
    test_docs_describe_update_requirement_for_schema_v3()
    print("ok")
