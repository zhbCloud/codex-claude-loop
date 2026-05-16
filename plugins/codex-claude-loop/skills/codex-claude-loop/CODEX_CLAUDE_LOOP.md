# Codex Claude Loop Contract

This document defines the Codex-led, Claude Code implementation workflow.

## Invocation Boundary

The delegate runtime is only valid inside a Codex child agent.

Required chain:

```text
Codex main thread -> Codex child agent -> delegate_to_claude.ps1 -> delegate_to_claude.py -> Claude CLI
```

The delegate runtime rejects execution unless this environment variable is present:

```text
CODEX_CLAUDE_LOOP_CHILD_THREAD=1
```

The Codex main thread must not invoke `claude` directly. The Codex main thread must not directly invoke the delegate runtime. It may inspect artifacts and run verification scripts.

## Roles

Codex main thread:

- Owns requirements, scope, planning, task decomposition, scheduling, risk judgment, acceptance, rejection, and final delivery.
- Writes and approves the plan before delegation.
- Reviews Claude's implementation diff and verification.
- Makes the final accept/reject decision.

Codex child thread:

- Acts as the execution-layer boundary.
- Sets the child marker.
- Invokes the delegate runtime.
- Reports artifact paths and concise outcomes back to the main thread.

Claude CLI:

- Implements approved Codex plans.
- Performs bounded rework.
- Runs or reports validation commands.
- Produces structured reports.
- Never makes final project acceptance decisions.

## State Machine

Allowed states:

```text
DraftPlan -> Approved
Approved -> Implement
Implement -> CodexReview
CodexReview -> Rework
Rework -> CodexReview
CodexReview -> Accepted
CodexReview -> Rejected
```

Invalid transitions are rejected by the runtime helper module and should be treated as workflow errors.

## Round Limits

Defaults:

- Implementation rework rounds: 2
- Parallel workers: 3

If a limit is hit, Codex main thread must stop automatic looping and decide whether to continue manually, narrow the scope, or reject the task.

## Session Modes

`PrimaryReuse`:

- Default serial mode.
- Reuses the primary Claude session for the same `SessionKey`.
- Best for approved implementation and follow-up rework on the same feature.

`PrimaryAnchor`:

- Parallel batch anchor.
- Establishes the main reusable context for later serial continuation.

`ParallelPool`:

- Independent pool slots for concurrent work.
- Slots prefer matching task fingerprints to increase context and cache reuse.
- A lease prevents two runs from writing to the same slot simultaneously.

## Task Fingerprint

The runtime builds a fingerprint from:

- task mode
- task text
- allowed paths
- validation commands
- session key

The fingerprint is used to route similar tasks to reusable sessions and parallel pool slots.

## Required Artifacts

Every run writes:

- `config_<run_id>.json`
- `status_<run_id>.json`
- `prompt_<run_id>.md`
- `claude_<run_id>.md`
- `stream_<run_id>.jsonl`
- `trace_<run_id>.log`

Artifacts are written under:

```text
.codex/codex_claude_loop/claude-delegate
```

Session pool state is written under:

```text
.codex/codex_claude_loop/session-pools
```

## Progress Monitoring Policy

The main thread should treat `status_<run_id>.json` as the primary progress surface. This keeps progress checks cheap and avoids repeated model/tool cycles caused by tailing raw stream logs.

Recommended behavior:

- Poll `status_<run_id>.json` with backoff, or call `windows_scripts/watch_delegate_status.ps1 -RunId <run_id> -Watch`.
- Do not repeatedly run `Get-Content -Tail` on `stream_<run_id>.jsonl` during normal progress checks.
- Inspect `stream_<run_id>.jsonl` only when the run is failed, stalled, timed out, or the user explicitly asks for raw stream diagnostics.
- Inspect `claude_<run_id>.md` only after the run reaches `completed` or `failed`.

The status artifact may include:

- `phase`: current runtime phase such as `queued`, `leasing_session`, `claude_running`, `finalizing`, `completed`, or `failed`.
- `heartbeatAt`: latest delegate heartbeat timestamp.
- `lastStreamAt`: latest Claude stream timestamp.
- `lastStreamRecordType`: latest Claude stream record type.
- `lastAssistantTextPreview`: compact assistant-text preview for progress reporting.
- `streamRecords`: count of Claude stream records processed.

## Required Claude Report

Claude must finish with these exact headings:

```text
Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups
```

The report must include commands actually run and their outcomes. If validation is blocked, Claude must explain the blocker and whether it is related to the delegated change.

## Scope Lock

The main thread should pass allowed paths with `-AllowedPath`.

When the target workspace is a Git repository, the delegate runtime checks `git diff --name-only` after Claude returns. If changed files are outside the allowed paths, the run is marked failed and must be reviewed or reworked.

## Validation Command Policy

The plan should define validation commands before implementation.

Claude may run only the provided validation commands unless it clearly explains why an extra command is necessary. The main thread decides whether that explanation is acceptable.

## Risk Policy

Risk severity:

- `P0`: data loss, security issue, destructive behavior, or build failure
- `P1`: core functional regression
- `P2`: boundary issue, compatibility concern, or performance risk
- `P3`: maintainability, style, or documentation concern

P0/P1 findings reject by default. P2/P3 findings are judged by Codex main thread.

## Stable Summary

Each run should maintain a compact stable summary in the Claude report:

- requirement summary
- approved decisions
- key files read or changed
- known risks
- next action

This helps later resumed sessions avoid repeated reading and modeling.

## Final Responsibility

Final acceptance belongs only to Codex main thread. Claude can say that its delegated task passed, but cannot declare the whole user request accepted.
