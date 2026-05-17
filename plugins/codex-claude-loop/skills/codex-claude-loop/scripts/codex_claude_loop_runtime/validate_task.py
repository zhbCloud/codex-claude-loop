from __future__ import annotations

import argparse

from .common import DelegateError
from .task_contract import validate_task_file


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate a strict Codex Claude Loop task file")
    p.add_argument("--task-file", required=True)
    p.add_argument("--tests", action="append", default=[])
    return p


def main(argv: list[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    try:
        validate_task_file(ns.task_file, ns.tests)
    except DelegateError as exc:
        print(f"Task validation failed: {exc}")
        return 1
    print(f"Task validation passed: {ns.task_file}")
    return 0
