from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop"
README_EXPECTATIONS = {
    "README.md": ("Windows 和 macOS", "重启 Codex Desktop"),
    "README-ZH.md": ("Windows 和 macOS", "重启 Codex Desktop"),
    "README.en.md": ("Windows and macOS", "restart Codex Desktop"),
}


def test_docs_describe_schema_v3_and_workflow_phases() -> None:
    documents = {name: REPO_ROOT / name for name in README_EXPECTATIONS}
    documents.update({
        "SKILL.md": SKILL_ROOT / "SKILL.md",
        "CODEX_CLAUDE_LOOP.md": SKILL_ROOT / "CODEX_CLAUDE_LOOP.md",
    })
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
    for name, (platform_phrase, _) in README_EXPECTATIONS.items():
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert platform_phrase in text, name
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
    documents = {"AI_INSTALL.md": (REPO_ROOT / "AI_INSTALL.md").read_text(encoding="utf-8")}
    for name, (_, restart_phrase) in README_EXPECTATIONS.items():
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert restart_phrase in text, name
        documents[name] = text
    for name, text in documents.items():
        assert "0.4.1" in text, name
        assert "schema v3" in text.lower(), name
        assert "codex debug prompt-input" in text, name


if __name__ == "__main__":
    test_docs_describe_schema_v3_and_workflow_phases()
    test_skill_docs_describe_windows_and_macos_boundary()
    test_readmes_describe_windows_and_macos_boundary()
    test_ai_install_supports_windows_and_macos()
    test_doctor_describes_windows_check_not_plugin_boundary()
    test_docs_describe_update_requirement_for_schema_v3()
    print("ok")
