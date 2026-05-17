from __future__ import annotations

import sys
import tempfile
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.delegate import normalize_allowed_paths, out_of_scope_files


def test_dot_allows_entire_repo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        changed = ["package.json", "src/App.vue", "plugins/foo/plugin.json"]
        assert out_of_scope_files(changed, ["."], root) == []
        assert normalize_allowed_paths(root, ["."]) == [""]


def test_relative_allowed_path_limits_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        changed = ["src/App.vue", "package.json", "src/views/Home.vue"]
        assert out_of_scope_files(changed, ["src"], root) == ["package.json"]


def test_absolute_allowed_path_inside_repo_is_relative() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        src = root / "src"
        changed = ["src/App.vue", "README.md"]
        assert normalize_allowed_paths(root, [str(src)]) == ["src"]
        assert out_of_scope_files(changed, [str(src)], root) == ["README.md"]


def test_windows_style_path_matches_posix_changed_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        changed = ["src/views/Home.vue", "package.json"]
        assert out_of_scope_files(changed, [r"src\views"], root) == ["package.json"]


if __name__ == "__main__":
    test_dot_allows_entire_repo()
    test_relative_allowed_path_limits_scope()
    test_absolute_allowed_path_inside_repo_is_relative()
    test_windows_style_path_matches_posix_changed_files()
    print("ok")
