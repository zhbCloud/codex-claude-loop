from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "codex-claude-loop" / "skills" / "codex-claude-loop" / "scripts"
sys.path.insert(0, str(RUNTIME_ROOT))

from codex_claude_loop_runtime import io_utils
from codex_claude_loop_runtime.workflow import update_workflow_record, update_workflow_status


def register_runs(root_text: str, worker: int) -> None:
    root = Path(root_text)
    for index in range(6):
        run_id = f"run-{worker}-{index}"
        update_workflow_record(
            root, "wf", run_id, run_id, "implementer", "fast", "", [], [], [], [],
            False, "", "", "", str(root / f"status_{run_id}.json"), "", "", "running",
        )
        update_workflow_status(
            {"config": {"workflowId": "wf", "runId": run_id}, "status_path": root / f"status_{run_id}.json"},
            "completed",
        )


class WorkflowPersistenceTests(unittest.TestCase):
    def test_json_reader_and_writer_can_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            io_utils.write_json(target, {"version": "old"})
            reader_open = threading.Event()
            finish_reading = threading.Event()

            def slow_read(path: Path) -> str:
                with path.open("r", encoding="utf-8") as handle:
                    reader_open.set()
                    if not finish_reading.wait(5):
                        raise TimeoutError("reader not released")
                    return handle.read()

            with ThreadPoolExecutor(max_workers=2) as pool:
                with patch.object(io_utils, "read_text", side_effect=slow_read):
                    reader = pool.submit(io_utils.read_json, target)
                    self.assertTrue(reader_open.wait(5))
                    writer = pool.submit(io_utils.write_json, target, {"version": "new"})
                    try:
                        # Give the writer a bounded window while the reader owns the handle.
                        writer.result(timeout=0.1)
                    except TimeoutError:
                        pass
                    finally:
                        finish_reading.set()
                    self.assertEqual(reader.result(timeout=5), {"version": "old"})
                    writer.result(timeout=5)
            self.assertEqual(io_utils.read_json(target), {"version": "new"})

    def test_parallel_json_writers_use_separate_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"

            def write_many(worker: int) -> None:
                for index in range(20):
                    io_utils.write_json(target, {"worker": worker, "index": index, "payload": "x" * 8192})

            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(write_many, range(6)))
            self.assertEqual(len(io_utils.read_json(target)["payload"]), 8192)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_failed_replace_preserves_original_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            io_utils.write_json(target, {"original": True})
            with patch.object(io_utils.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    io_utils.write_json(target, {"original": False})
            self.assertEqual(io_utils.read_json(target), {"original": True})
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_workflow_parallel_processes_preserve_all_runs_and_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = multiprocessing.get_context("spawn")
            workers = [ctx.Process(target=register_runs, args=(tmp, index)) for index in range(4)]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=10)
                    self.assertEqual(worker.exitcode, 0)
                state = json.loads((Path(tmp) / "workflow_wf.json").read_text(encoding="utf-8"))
                expected = {f"run-{worker}-{index}" for worker in range(4) for index in range(6)}
                self.assertEqual({run["runId"] for run in state["runs"]}, expected)
                self.assertEqual(len(state["runs"]), len(expected))
                self.assertEqual(set(state["tasks"]), expected)
                self.assertEqual(set(state["taskMap"]), expected)
                self.assertTrue(all(run["status"] == "completed" for run in state["runs"]))
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
