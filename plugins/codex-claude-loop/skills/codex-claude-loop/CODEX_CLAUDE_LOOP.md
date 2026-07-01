# Codex Claude Loop Contract

This document defines the Codex-led, Claude Code implementation workflow.

## Invocation Boundary

The delegate runtime is only valid inside a Codex child agent.

Required chain:

```text
Codex main thread -> Codex child agent -> platform delegate wrapper -> delegate_to_claude.py -> Claude CLI
```

The delegate runtime rejects execution unless this environment variable is present:

```text
CODEX_CLAUDE_LOOP_CHILD_THREAD=1
```

The Codex main thread must not invoke `claude` directly. The Codex main thread must not directly invoke the delegate runtime. It may inspect artifacts and run verification scripts.

The plugin includes a hook gate at `hooks/hooks.json` to reinforce this route and deny non-compliant delegation tool calls when the host supports hooks.

When a user prompt activates Codex Claude Loop, the hook records loop mode in `.codex/codex_claude_loop/loop_mode.json`. While active, main-thread production-source writes are denied at `PreToolUse`; task files under `.codex/codex_claude_loop/`, child-thread delegate calls, and validation commands remain allowed. Users can explicitly disable it by asking to disable or exit loop mode.

## Roles

Codex main thread:

- Owns requirements, scope, planning, task decomposition, scheduling, risk judgment, acceptance, rejection, and final delivery.
- Writes and approves the plan before delegation.
- Reviews Claude's implementation diff and verification.
- Makes the final accept/reject decision.
- When the user explicitly asks to use Codex Claude Loop, does not directly edit production source files or implement fallback fixes in the main thread. If a delegate fails, the main thread may adjust the task, allowed paths, session key, or validation plan and delegate rework; inspect artifacts; run verification; or report the blocker to the user.

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
- Parallel workers: 5

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

## Work Modes

`WorkMode=fast` is the personal high-frequency path. It is intended for small, scoped changes and quick fixes where the main thread already understands the task. Fast mode keeps the compact report contract and allows a completed light-validation run to pass the run gate when headings, scope, and process status are clean.

`WorkMode=strict` is the complex-project path. It requires a task-file contract before dispatch, uses the expanded report contract, records review metadata, and makes workflow verification require accepted `spec` and `quality` reviewer runs for implementer tasks plus an accepted `final-verifier` run.

`WorkMode=auto` is the default. It selects strict mode for reviewer runs, final-verifier runs, writable parallel runs, or task files that already contain the strict contract sections; otherwise it selects fast mode.

## Workflow Phases

The plugin intentionally keeps one public skill entrypoint. To preserve clear responsibilities without multiplying skill files, the main thread should run larger tasks through these phases:

- Planning: capture user requirements, allowed paths, forbidden actions, acceptance criteria, verification commands, work mode, session key, and risk level.
- Dispatching: create or validate the task file, select role/session/parallel options, and send the work through a Codex child thread only.
- Reviewing: inspect `status_<run_id>.json`, `final_gate_<run_id>.json`, `claude_<run_id>.md`, changed files, scope checks, reviewer evidence, and reported validation.
- Finishing: run workflow verification, run main-thread full validation when required, decide accept/rework/reject, and summarize risks for the user.

The plugin supports Windows through `windows_scripts/delegate_to_claude.ps1` and macOS through `macos_scripts/delegate_to_claude.sh`. Both platforms use the same Python runtime and artifact contract. Linux entrypoints are not provided or validated. macOS wrapper support starts in plugin version `0.4.2`; after `codex plugin marketplace upgrade codex-claude-loop`, restart Codex Desktop or open a new session before relying on the updated plugin cache. On macOS GUI sessions, the runtime checks `PATH` first, then common Claude CLI locations such as `/opt/homebrew/bin/claude` and `/usr/local/bin/claude`.

Strict task files must contain these sections:

```text
Goal
Allowed Scope
Forbidden Actions
Acceptance Criteria
Verification
Report Requirements
```

Before strict dispatch, validate the task file:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\validate_delegate_task.ps1 `
  -TaskFile .\.codex\codex_claude_loop\tasks\<task>.md `
  -Tests "pnpm run build"
```

On macOS:

```zsh
./skills/codex-claude-loop/macos_scripts/validate_delegate_task.sh \
  --task-file ./.codex/codex_claude_loop/tasks/<task>.md \
  --tests "pnpm run build"
```

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

Workflow-level artifact:

- `workflow_<workflow_id>.json`
- `final_gate_<run_id>.json`

All newly generated artifacts use artifact schema v3. Version 3 covers run-level gates, workflow task metadata, reviewer evidence, final-verifier records, declared validation evidence, and parallel scope checks.

## Progress Monitoring Policy

The main thread should treat `status_<run_id>.json` as the primary progress surface. This keeps progress checks cheap and avoids repeated model/tool cycles caused by tailing raw stream logs.

Recommended behavior:

- Poll `status_<run_id>.json` with backoff, or call `windows_scripts/watch_delegate_status.ps1 -RunId <run_id> -Watch` on Windows or `macos_scripts/watch_delegate_status.sh --run-id <run_id> --watch` on macOS.
- For multi-run orchestration, call the same platform watcher with `-WorkflowId` on Windows or `--workflow-id` on macOS.
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
- `workflowId`, `taskId`, and `role`: workflow metadata for aggregated monitoring.

## Required Claude Report

Fast-mode Claude reports must finish with these exact headings:

```text
Process Log
Summary
Changed Files
Verification
Final Result
Risks Or Follow-ups
```

Strict-mode Claude reports must finish with these exact headings:

```text
Process Log
Status
Role
Summary
Changed Files
Verification
Findings
Final Result
Risks Or Follow-ups
```

Accepted tokens are `PASS` and `PASS_WITH_CONCERNS`. In strict mode, both `Status` and `Final Result` must use an accepted token, or the main thread must reject, rework, or ask for missing context.

The report must include commands actually run and their outcomes. If validation is blocked, Claude must explain the blocker and whether it is related to the delegated change.

## Scope Lock

The main thread should pass allowed paths with `-AllowedPath`.

Use `-AllowedPath .` only when the approved task genuinely owns the current repository-level diff, such as migration-wide sweeps where `package.json`, config files, and source files are expected to change. The runtime treats `.`, `./`, and the repository root absolute path as the whole repo.

When the target workspace is a Git repository, the delegate runtime checks `git diff --name-only` after Claude returns. If changed files are outside the allowed paths, the run is marked failed and must be reviewed or reworked.

## Standard Delegate Command (Child Thread)

```powershell
$env:CODEX_CLAUDE_LOOP_CHILD_THREAD = "1"
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\delegate_to_claude.ps1 `
  -TaskFile .\.codex\codex_claude_loop\tasks\<task>.md `
  -WorkflowId <workflow_id> `
  -TaskId <task_id> `
  -Role implementer `
  -WorkMode auto `
  -ValidationPhase light `
  -TaskMode implementation `
  -SessionMode PrimaryReuse `
  -SessionKey <session_key> `
  -AllowedPath src `
  -ValidationCommand "pnpm run build"
```

For multiple validation commands in PowerShell, pass an array in one parameter binding:

```powershell
-ValidationCommand @("node --check src/common/pwdEncryption.js", "node --check src/mock/index.js")
```

This command starts asynchronously by default and returns `RunId`/artifact paths quickly. Add `-WaitForCompletion` only when you explicitly want blocking behavior.
The delegate wrapper emits a JSON result line with `state` (`started`, `completed`, `failed`). Upstream schedulers must read this field instead of treating process return as completion semantics.

macOS child-thread command:

```zsh
export CODEX_CLAUDE_LOOP_CHILD_THREAD=1
./skills/codex-claude-loop/macos_scripts/delegate_to_claude.sh \
  --task-file ./.codex/codex_claude_loop/tasks/<task>.md \
  --workflow-id <workflow_id> \
  --task-id <task_id> \
  --role implementer \
  --work-mode auto \
  --validation-phase light \
  --task-mode implementation \
  --session-mode PrimaryReuse \
  --session-key <session_key> \
  --allowed-path src \
  --validation-command "pnpm run build"
```

The macOS wrapper runs the shared Python delegate in the foreground. Pass repeated options such as `--allowed-path` and `--validation-command` once per value.

For writable parallel runs, also pass:

```powershell
-AllowParallel -Scope <owned-path-or-scope>
```

## Validation Command Policy

The plan should define validation commands before implementation.

Claude may run only the provided validation commands unless it clearly explains why an extra command is necessary. The main thread decides whether that explanation is acceptable.

Recommended performance pattern:

- Delegate pass: `ValidationPhase=light`
- Main-thread acceptance gate: run full validation (for example `pnpm run build`)
- Final accept condition: `status_<run_id>.json.status=completed` and `final_gate_<run_id>.json.gateStatus=passed`

In fast mode, a clean completed light-validation delegate run can pass its run gate for speed. In strict mode, light-validation runs remain `pending_full_validation` until full validation evidence is available.

## Workflow Metadata Policy

Every delegate run must pass all three values:

- `WorkflowId`
- `TaskId`
- `Role` (`planner`, `implementer`, `researcher`, `reviewer`, `final-verifier`)
- `SessionKey`

If `AllowParallel` is used for writable work, `Scope` is required.

Reviewer runs must also pass `ReviewForTaskId` and `ReviewKind` (`spec` or `quality`).

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

If a run has `status=failed`, Codex must not silently accept its implementation. It may salvage the findings only by creating an explicit rework task for Claude, or by stopping and asking the user whether to leave the loop workflow.
