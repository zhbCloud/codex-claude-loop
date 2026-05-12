from __future__ import annotations

from .common import DelegateError


ALLOWED_TRANSITIONS = {
    "DraftPlan": {"ReviewPlan"},
    "ReviewPlan": {"RevisePlan", "Approved"},
    "RevisePlan": {"ReviewPlan"},
    "Approved": {"Implement"},
    "Implement": {"CodexReview"},
    "CodexReview": {"Rework", "Accepted", "Rejected"},
    "Rework": {"CodexReview"},
    "Accepted": set(),
    "Rejected": set(),
}


TASK_MODE_TARGET_STATE = {
    "plan-review": "ReviewPlan",
    "implementation": "Implement",
    "rework": "Rework",
}


def validate_state_transition(source: str, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(source)
    if allowed is None:
        raise DelegateError(f"Unknown workflow state: {source}")
    if target not in allowed:
        raise DelegateError(f"Invalid workflow transition: {source} -> {target}")


def state_for_task_mode(task_mode: str) -> str:
    try:
        return TASK_MODE_TARGET_STATE[task_mode]
    except KeyError as exc:
        raise DelegateError(f"Unsupported task mode: {task_mode}") from exc
