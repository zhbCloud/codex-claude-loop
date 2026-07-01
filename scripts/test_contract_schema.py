from __future__ import annotations

import sys

RUNTIME_ROOT = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "plugins"
    / "codex-claude-loop"
    / "skills"
    / "codex-claude-loop"
    / "scripts"
)
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.common import ARTIFACT_SCHEMA_VERSION
from codex_claude_loop_runtime.contract import DEFAULT_CONTRACT, load_contract


def test_artifact_schema_version_is_v3() -> None:
    assert DEFAULT_CONTRACT["artifactSchemaVersion"] == 3
    assert load_contract()["artifactSchemaVersion"] == 3
    assert ARTIFACT_SCHEMA_VERSION == 3


if __name__ == "__main__":
    test_artifact_schema_version_is_v3()
    print("ok")
