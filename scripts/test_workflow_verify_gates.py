from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.io_utils import write_json
from codex_claude_loop_runtime.verify_workflow import verify_workflow


def write_run(root: Path, run_id: str, task_id: str, *, output: str = "Verification\n- ok\n", dry_run: bool = False) -> dict:
    status_path = root / f"status_{run_id}.json"
    config_path = root / f"config_{run_id}.json"
    output_path = root / f"claude_{run_id}.md"
    prompt_path = root / f"prompt_{run_id}.md"
    stream_path = root / f"stream_{run_id}.jsonl"
    trace_path = root / f"trace_{run_id}.log"
    gate_path = root / f"final_gate_{run_id}.json"
    write_json(status_path, {"runId": run_id, "status": "completed", "finalGatePath": str(gate_path)})
    write_json(config_path, {"runId": run_id, "runtimeOptions": {"dryRun": dry_run}})
    output_path.write_text(output, encoding="utf-8")
    prompt_path.write_text("", encoding="utf-8")
    stream_path.write_text("", encoding="utf-8")
    trace_path.write_text("", encoding="utf-8")
    write_json(gate_path, {"runId": run_id, "gateStatus": "passed"})
    return {
        "runId": run_id,
        "taskId": task_id,
        "role": "implementer",
        "status": "completed",
        "statusPath": str(status_path),
        "configPath": str(config_path),
        "outputPath": str(output_path),
        "promptPath": str(prompt_path),
    }


def write_workflow(root: Path, workflow: dict) -> None:
    write_json(root / f"workflow_{workflow['workflowId']}.json", workflow)


def test_missing_spec_or_quality_review_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = write_run(root, "run-impl", "impl")
        write_workflow(
            root,
            {
                "workflowId": "wf",
                "runs": [run],
                "tasks": {
                    "impl": {
                        "taskId": "impl",
                        "role": "implementer",
                        "workMode": "strict",
                        "status": "completed",
                        "reviewDecision": "pending-review",
                        "runs": ["run-impl"],
                    }
                },
            },
        )
        result = verify_workflow(root, "wf")
        assert not result["ok"]
        assert result["strictPendingTasks"] == ["impl"]


def test_missing_final_verifier_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = write_run(root, "run-impl", "impl")
        write_workflow(
            root,
            {
                "workflowId": "wf",
                "runs": [run],
                "finalAcceptance": {"finalVerifierRequired": True},
                "tasks": {
                    "impl": {
                        "taskId": "impl",
                        "role": "implementer",
                        "workMode": "strict",
                        "status": "completed",
                        "reviewDecision": "accepted",
                        "runs": ["run-impl"],
                    }
                },
            },
        )
        result = verify_workflow(root, "wf")
        assert not result["ok"]
        assert result["finalVerifierMissing"]


def test_legacy_strict_without_new_final_verifier_flag_is_compatible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = write_run(root, "run-impl", "impl")
        write_workflow(
            root,
            {
                "workflowId": "wf",
                "runs": [run],
                "tasks": {
                    "impl": {
                        "taskId": "impl",
                        "role": "implementer",
                        "workMode": "strict",
                        "status": "completed",
                        "reviewDecision": "accepted",
                        "runs": ["run-impl"],
                    }
                },
            },
        )
        result = verify_workflow(root, "wf")
        assert result["ok"]
        assert not result["finalVerifierMissing"]


def test_parallel_scope_conflict_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_a = write_run(root, "run-a", "a")
        run_b = write_run(root, "run-b", "b")
        write_workflow(
            root,
            {
                "workflowId": "wf",
                "runs": [run_a, run_b],
                "tasks": {
                    "a": {"taskId": "a", "role": "implementer", "status": "completed", "allowParallel": True, "scope": "src", "runs": ["run-a"]},
                    "b": {"taskId": "b", "role": "implementer", "status": "completed", "allowParallel": True, "scope": "src/views", "runs": ["run-b"]},
                },
            },
        )
        result = verify_workflow(root, "wf")
        assert not result["ok"]
        assert result["parallelScopeConflicts"] == ["a<->b"]


def test_declared_test_missing_from_output_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = write_run(root, "run-impl", "impl", output="Verification\n- npm test\n")
        verifier = write_run(root, "run-final", "final")
        write_workflow(
            root,
            {
                "workflowId": "wf",
                "runs": [run, verifier],
                "finalVerifier": {"taskId": "final", "runId": "run-final", "reviewDecision": "accepted"},
                "tasks": {
                    "impl": {
                        "taskId": "impl",
                        "role": "implementer",
                        "workMode": "strict",
                        "status": "completed",
                        "reviewDecision": "accepted",
                        "tests": ["pnpm run build"],
                        "runs": ["run-impl"],
                        "lastRunId": "run-impl",
                    },
                    "final": {"taskId": "final", "role": "final-verifier", "workMode": "strict", "status": "completed", "runs": ["run-final"]},
                },
            },
        )
        result = verify_workflow(root, "wf")
        assert not result["ok"]
        assert result["missingTestEvidence"] == ["impl: pnpm run build"]


if __name__ == "__main__":
    test_missing_spec_or_quality_review_fails()
    test_missing_final_verifier_fails()
    test_legacy_strict_without_new_final_verifier_flag_is_compatible()
    test_parallel_scope_conflict_fails()
    test_declared_test_missing_from_output_fails()
    print("ok")
