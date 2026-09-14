from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime.io_utils import read_json, write_json
from codex_claude_loop_runtime.common import now_iso
from codex_claude_loop_runtime.verify_workflow import verify_workflow
from codex_claude_loop_runtime.workflow import finalize_workflow_record, update_workflow_record


def write_run(root: Path, run_id: str, task_id: str, *, output: str = "Verification\n- ok\n", dry_run: bool = False) -> dict:
    status_path = root / f"status_{run_id}.json"
    config_path = root / f"config_{run_id}.json"
    output_path = root / f"claude_{run_id}.md"
    prompt_path = root / f"prompt_{run_id}.md"
    stream_path = root / f"stream_{run_id}.jsonl"
    trace_path = root / f"trace_{run_id}.log"
    gate_path = root / f"final_gate_{run_id}.json"
    write_json(status_path, {"runId": run_id, "status": "completed", "finalGatePath": str(gate_path),
                             "startedAt": now_iso(), "completedAt": now_iso()})
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


def test_successful_retry_supersedes_terminal_history_but_not_live_run() -> None:
    for old_status, old_gate, expected in (
        ("failed", "failed", True),
        ("completed", "pending_full_validation", True),
        ("running", "pending_full_validation", False),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = write_run(root, "old", "impl")
            new = write_run(root, "new", "impl")
            write_json(Path(old["statusPath"]), {"status": old_status})
            write_json(root / "final_gate_old.json", {"gateStatus": old_gate})
            write_workflow(root, {"workflowId": "wf", "runs": [old, new], "tasks": {}})
            result = verify_workflow(root, "wf")
            assert result["ok"] is expected, result
            assert result["totalRuns"] == 2


def test_invalid_run_entries_fail_closed() -> None:
    for run in (None, "bad", 7, {}, {"runId": "bad"}):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_workflow(root, {"workflowId": "wf", "runs": [run]})
            result = verify_workflow(root, "wf")
            assert not result["ok"], (run, result)
            assert result["state"] == "failed", result


def test_retry_cannot_hide_a_different_task_or_role_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = write_run(root, "old", "review")
        old["role"] = "reviewer"
        write_json(Path(old["statusPath"]), {"status": "failed"})
        write_json(root / "final_gate_old.json", {"gateStatus": "failed"})
        new = write_run(root, "new", "review")
        write_workflow(root, {"workflowId": "wf", "runs": [old, new]})
        assert not verify_workflow(root, "wf")["ok"]


REPORT = "\n".join(
    "## " + heading + "\n" + value for heading, value in (
        ("Process Log", "done"), ("Status", "PASS"), ("Role", "implementer"),
        ("Summary", "done"), ("Changed Files", "none"), ("Verification", "ok"),
        ("Findings", "none"), ("Final Result", "PASS"), ("Risks Or Follow-ups", "none"),
    )
)


def start_run(root: Path, run_id: str, task_id: str, role: str = "implementer", kind: str = "") -> dict:
    run = write_run(root, run_id, task_id, output=REPORT)
    config = {"workflowId": "wf", "runId": run_id, "taskId": task_id, "role": role, "workMode": "strict",
              "reviewForTaskId": "impl" if role == "reviewer" else "", "reviewKind": kind}
    update_workflow_record(
        root, "wf", run_id, task_id, role, "strict", "", [], [], [], [], False,
        config["reviewForTaskId"], kind, run["configPath"], run["statusPath"], run["promptPath"], run["outputPath"], "running",
    )
    return {"config": config, "status_path": Path(run["statusPath"])}


def finish_run(context: dict) -> None:
    status = read_json(context["status_path"])
    status["completedAt"] = now_iso()
    write_json(context["status_path"], status)
    finalize_workflow_record(context, "completed", REPORT)


def accepted_workflow(root: Path) -> None:
    finish_run(start_run(root, "impl-v1", "impl"))
    finish_run(start_run(root, "spec-v1", "spec", "reviewer", "spec"))
    finish_run(start_run(root, "quality-v1", "quality", "reviewer", "quality"))
    finish_run(start_run(root, "final-v1", "final", "final-verifier"))
    assert verify_workflow(root, "wf")["ok"]


def test_rework_invalidates_old_reviews_and_final_verifier() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        accepted_workflow(root)
        finish_run(start_run(root, "impl-v2", "impl"))
        result = verify_workflow(root, "wf")
        assert not result["ok"], result
        assert result["strictPendingTasks"] == ["impl"]
        assert result["finalVerifierMissing"]
        finish_run(start_run(root, "spec-v2", "spec", "reviewer", "spec"))
        finish_run(start_run(root, "quality-v2", "quality", "reviewer", "quality"))
        assert not verify_workflow(root, "wf")["ok"]
        finish_run(start_run(root, "final-v2", "final", "final-verifier"))
        assert verify_workflow(root, "wf")["ok"]


def test_late_old_review_and_final_verifier_cannot_accept_new_implementation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        accepted_workflow(root)
        stale_spec = start_run(root, "stale-spec", "spec", "reviewer", "spec")
        stale_quality = start_run(root, "stale-quality", "quality", "reviewer", "quality")
        stale_final = start_run(root, "stale-final", "final", "final-verifier")
        finish_run(start_run(root, "impl-v2", "impl"))
        for context in (stale_spec, stale_quality, stale_final):
            finish_run(context)
        result = verify_workflow(root, "wf")
        assert not result["ok"], result
        assert result["strictPendingTasks"] == ["impl"]
        assert result["finalVerifierMissing"]


def test_verifier_rejects_stale_accepted_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        accepted_workflow(root)
        original = read_json(root / "workflow_wf.json")
        finish_run(start_run(root, "impl-v2", "impl"))
        changed = read_json(root / "workflow_wf.json")
        changed["tasks"]["impl"]["reviews"] = original["tasks"]["impl"]["reviews"]
        changed["tasks"]["impl"]["reviewDecision"] = "accepted"
        changed["finalVerifier"] = original["finalVerifier"]
        changed["finalAcceptance"] = original["finalAcceptance"]
        write_workflow(root, changed)
        assert not verify_workflow(root, "wf")["ok"]


def test_late_evidence_does_not_overwrite_newer_review_or_final_verifier() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        accepted_workflow(root)
        stale_spec = start_run(root, "stale-spec", "old-spec-task", "reviewer", "spec")
        stale_final = start_run(root, "stale-final", "old-final-task", "final-verifier")
        finish_run(start_run(root, "impl-v2", "impl"))
        finish_run(start_run(root, "spec-v2", "new-spec-task", "reviewer", "spec"))
        finish_run(start_run(root, "quality-v2", "new-quality-task", "reviewer", "quality"))
        workflow = read_json(root / "workflow_wf.json")
        assert workflow["tasks"]["impl"]["reviews"]["spec"]["runId"] == "spec-v2"
        finish_run(start_run(root, "final-v2", "new-final-task", "final-verifier"))
        finish_run(stale_spec)
        finish_run(stale_final)
        workflow = read_json(root / "workflow_wf.json")
        assert workflow["finalVerifier"]["runId"] == "final-v2"
        assert verify_workflow(root, "wf")["ok"]


def test_review_and_final_verifier_must_start_after_their_inputs_finish() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        implementation = start_run(root, "impl", "impl")
        spec = start_run(root, "spec", "spec", "reviewer", "spec")
        quality = start_run(root, "quality", "quality", "reviewer", "quality")
        finish_run(implementation)
        finish_run(spec)
        finish_run(quality)
        finish_run(start_run(root, "final", "final", "final-verifier"))
        result = verify_workflow(root, "wf")
        assert not result["ok"]
        assert result["strictPendingTasks"] == ["impl"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        finish_run(start_run(root, "impl", "impl"))
        spec = start_run(root, "spec", "spec", "reviewer", "spec")
        quality = start_run(root, "quality", "quality", "reviewer", "quality")
        final = start_run(root, "final", "final", "final-verifier")
        finish_run(spec)
        finish_run(quality)
        finish_run(final)
        assert verify_workflow(root, "wf")["finalVerifierMissing"]


def test_prepared_reviewer_is_valid_when_actual_execution_starts_later() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        implementation = start_run(root, "impl", "impl")
        spec = start_run(root, "spec", "spec", "reviewer", "spec")
        finish_run(implementation)
        status = read_json(spec["status_path"])
        status["startedAt"] = now_iso()  # execute_prepared resets this field at execution.
        write_json(spec["status_path"], status)
        finish_run(spec)
        finish_run(start_run(root, "quality", "quality", "reviewer", "quality"))
        finish_run(start_run(root, "final", "final", "final-verifier"))
        assert verify_workflow(root, "wf")["ok"]


if __name__ == "__main__":
    test_missing_spec_or_quality_review_fails()
    test_missing_final_verifier_fails()
    test_legacy_strict_without_new_final_verifier_flag_is_compatible()
    test_parallel_scope_conflict_fails()
    test_declared_test_missing_from_output_fails()
    test_successful_retry_supersedes_terminal_history_but_not_live_run()
    test_invalid_run_entries_fail_closed()
    test_retry_cannot_hide_a_different_task_or_role_failure()
    test_rework_invalidates_old_reviews_and_final_verifier()
    test_late_old_review_and_final_verifier_cannot_accept_new_implementation()
    test_verifier_rejects_stale_accepted_summary()
    test_late_evidence_does_not_overwrite_newer_review_or_final_verifier()
    test_review_and_final_verifier_must_start_after_their_inputs_finish()
    test_prepared_reviewer_is_valid_when_actual_execution_starts_later()
    print("ok")
