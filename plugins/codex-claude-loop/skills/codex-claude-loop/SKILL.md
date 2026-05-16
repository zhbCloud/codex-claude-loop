---
name: codex-claude-loop
description: Use when the user wants Codex to plan, delegate implementation to Claude Code through a constrained child-agent workflow, review the result, and manage bounded rework loops with session reuse, parallel pools, and artifact verification.
---

# Codex Claude Loop

## Required Reading

Read `CODEX_CLAUDE_LOOP.md` in this skill directory before using the workflow. Treat it as the source of truth for state transitions, role boundaries, child-thread enforcement, artifact requirements, session modes, and review/rework limits.

## Core Rule

Use this skill when the user asks for a Codex-led workflow where Codex owns planning, review, risk judgment, and acceptance while Claude Code implements approved tasks or fixes rejected work.

The required chain is:

```text
Codex main thread -> Codex spawn_agent child thread -> codex-claude-loop delegate runtime -> Claude CLI
```

The Codex main thread must not run `claude` directly and must not run `windows_scripts/delegate_to_claude.ps1` directly.

## Main Thread Duties

- Understand the user's request and define scope.
- Draft and approve the plan.
- Delegate implementation to Claude only after plan approval.
- Review diff, validation output, artifacts, risks, and scope.
- Accept or reject the work. Claude cannot self-approve final acceptance.
- If rejected, delegate rework with precise findings and a bounded round count.

## Main Thread Progress Checks

The Codex main thread should avoid high-frequency polling and should not repeatedly tail `stream_<run_id>.jsonl` during normal runs.

Preferred progress flow:

- Ask the child thread to return `RunId` and `StatusPath` after delegate startup when using asynchronous execution.
- Check `status_<run_id>.json` first, or run `windows_scripts/watch_delegate_status.ps1 -RunId <run_id> -Watch`.
- Use low-frequency backoff when watching progress. The helper script handles this internally.
- Read `stream_<run_id>.jsonl` only for timeout, failure, or explicit diagnostic investigation.
- Read `claude_<run_id>.md` after the run reaches `completed` or `failed`.

## Child Thread Duties

The Codex child thread must:

- Set `CODEX_CLAUDE_LOOP_CHILD_THREAD=1` before invoking the delegate.
- Run `skills/codex-claude-loop/windows_scripts/delegate_to_claude.ps1`.
- Pass a task file with `-TaskFile`.
- Pass `-WorkflowId`, `-TaskId`, and `-Role` on every delegate run.
- Pass `-TaskMode implementation` or `-TaskMode rework`.
- Use `-ValidationPhase light` for the delegate pass, then run full validation at main-thread acceptance.
- Pass `-SessionKey` for stable context reuse.
- Pass `-AllowedPath` and `-ValidationCommand` whenever the main thread has defined scope and verification.
- Pass `-AllowParallel -Scope <path-or-scope>` for writable parallel runs.
- Return the artifact paths, changed files, validation result, and risks to the main thread.
- Default behavior is asynchronous startup (`StartOnly` path). Use `-WaitForCompletion` only when blocking execution is explicitly needed.
- Delegate script returns a final JSON line with `state`:
  - `started`: async startup succeeded, task is still running
  - `completed`: blocking run finished successfully
  - `failed`: blocking run finished with failure

Example (child thread command):

```powershell
$env:CODEX_CLAUDE_LOOP_CHILD_THREAD = "1"
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\delegate_to_claude.ps1 `
  -TaskFile .\.codex\codex_claude_loop\tasks\impl-001.md `
  -WorkflowId wf-demo-001 `
  -TaskId task-impl-001 `
  -Role implementer `
  -ValidationPhase light `
  -TaskMode implementation `
  -SessionMode PrimaryReuse `
  -SessionKey feature-x `
  -AllowedPath src `
  -ValidationCommand "pnpm run build"
```

## Required Claude Report Headings

Every Claude delegate report must include these exact headings:

```text
Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups
```

If any heading is missing, the main thread must reject the delegate report or ask for report repair through the delegate runtime.

## Default Limits

- Implementation rework rounds: 2
- Parallel pool size: 3
- P0/P1 findings: reject by default
- P2/P3 findings: Codex main thread decides

## Verification

After each delegate run, the main thread should run:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1 -RunId <run_id>
```

After each workflow batch, the main thread should run:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_workflow.ps1 -WorkflowId <workflow_id>
```

Before final acceptance, run full validation from main thread (example):

```powershell
pnpm run build
```

Only accept when both are true:

- `status_<run_id>.json` shows `status=completed`
- `final_gate_<run_id>.json` shows `gateStatus=passed`

When you need aggregated progress for a whole workflow:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\watch_delegate_status.ps1 -WorkflowId <workflow_id> -Watch
```

The final response to the user must include:

- 修改内容
- 验证结果
- 边缘情况
- 建议测试用例
- 可能的风险点
