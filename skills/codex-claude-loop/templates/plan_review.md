# Claude Plan Review Task

You are reviewing a Codex-authored implementation plan.

## Your Job

- Find ambiguity, missing scope, risky assumptions, missing validation, and likely implementation traps.
- Do not implement code.
- Do not approve the whole user request.
- Return `PASS` only if the plan is actionable, scoped, testable, and low risk.

## Review Checklist

- Requirements and non-goals are clear.
- Planned files and modules match the task.
- Validation commands are meaningful.
- Rollback and risk are understood.
- No unrelated refactor or architecture expansion is hidden in the plan.
- Edge cases are named.

## Required Report Headings

Process Log

Summary

Changed Files

Verification

Final Result

Risks Or Follow-ups
