# Codex Claude Loop

[中文说明](./README-ZH.md)

Codex Claude Loop is a **Windows-only Codex plugin** for a strict planning, delegation, implementation, and review workflow:

```text
Codex main thread -> Codex child agent -> plugin delegate runtime -> Claude CLI
```

Codex owns requirement analysis, planning, final review, risk judgment, and acceptance. Claude only reviews plans and implements approved work after a Codex child agent invokes the plugin delegate runtime.

## Important Limitations

- This plugin currently targets Windows only.
- PowerShell 7+ is recommended.
- Delegate scripts live under `skills/codex-claude-loop/windows_scripts/`.
- macOS and Linux delegate scripts are not provided.
- Claude CLI must be installed and logged in if you want the runtime to actually call Claude.

## What It Provides

- Fixed workflow states: `DraftPlan`, `ReviewPlan`, `RevisePlan`, `Approved`, `Implement`, `CodexReview`, `Rework`, `Accepted`, `Rejected`.
- Hard child-thread marker: `CODEX_CLAUDE_LOOP_CHILD_THREAD=1`.
- Direct main-thread delegate invocation is rejected.
- Reusable Claude sessions with `PrimaryReuse`, `PrimaryAnchor`, and `ParallelPool`.
- Session leases to avoid concurrent writes to the same Claude session.
- Audit artifacts under `.codex/codex_claude_loop/`.
- Structured Claude reports with required headings.
- Allowed-path diff checks when the target project is a Git repository.
- Default bounded loops: plan review up to 3 rounds, implementation rework up to 2 rounds.

## Windows Delegate Example

The delegate entrypoint is intended to be run by a Codex child agent, not by the Codex main thread:

```powershell
$env:CODEX_CLAUDE_LOOP_CHILD_THREAD = '1'
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\delegate_to_claude.ps1 `
  -TaskFile .\.codex\codex_claude_loop\tasks\20260512\001-plan-review.md `
  -TaskMode plan-review `
  -SessionMode PrimaryReuse `
  -SessionKey my-feature-loop `
  -AllowedPath src `
  -ValidationCommand "npm test"
```

Use `-DryRun` to generate artifacts and validate routing without invoking Claude.

## Artifact Layout

Default artifact root:

```text
.codex/codex_claude_loop/
  claude-delegate/
    claude_<run_id>.md
    config_<run_id>.json
    prompt_<run_id>.md
    status_<run_id>.json
    stream_<run_id>.jsonl
    trace_<run_id>.log
  session-pools/
    <session_key>.json
```

## Verification

Check one run:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1 -RunId <run_id>
```

Check the latest run:

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1
```

## Installation

This repository is intended to be distributed as a Codex plugin. Users can install it manually, or ask Codex AI to inspect the repository and perform the installation.

### Method 1: Manual Installation

#### Requirements

- Codex CLI is installed.
- Codex is logged in.
- The machine can access GitHub.
- Windows is required, and PowerShell 7+ is recommended.
- Claude CLI must be installed and logged in if you want the delegate runtime to actually call Claude.

Check Codex CLI:

```powershell
codex --version
```

If Codex CLI is not installed, install it first:

```powershell
npm i -g @openai/codex
```

#### 1. Add the Plugin Marketplace

```powershell
codex plugin marketplace add <your-github-repository-url>
```

Example:

```powershell
codex plugin marketplace add https://github.com/<owner>/codex-claude-loop
```

#### 2. Install the Plugin in Codex

Open Codex and run:

```text
/plugin install codex-claude-loop@<marketplace-name> --scope user
```

If your marketplace name matches the repository name, the command is usually:

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

#### 3. Restart or Refresh Codex

After installation, restart Codex or refresh the plugin list.

#### 4. Verify the Plugin

Send a prompt like this in Codex:

```text
Use codex-claude-loop so Codex drafts the plan first, then delegates execution to Claude through a child agent.
```

If the plugin is active, Codex should recognize the `codex-claude-loop` skill and follow this chain:

```text
Codex main thread -> Codex child agent -> codex-claude-loop delegate runtime -> Claude CLI
```

### Method 2: Ask Codex AI to Install It

If you do not want to install it manually, give Codex this prompt:

```text
Please install and enable this Windows-only Codex plugin:

GitHub repository:
https://github.com/<owner>/codex-claude-loop

Requirements:
1. First check whether Codex CLI is installed on my machine.
2. If Codex CLI is not installed, tell me how to install it.
3. Confirm that the current system is Windows. If it is not Windows, stop the installation and explain why.
4. Check whether this repository is a valid Codex plugin and confirm that .codex-plugin/plugin.json exists.
5. Add this repository as a Codex plugin marketplace.
6. Install the codex-claude-loop plugin with user scope.
7. After installation, tell me whether I need to restart Codex.
8. Do not modify my project business code.
9. If any step fails, stop and explain the reason. Do not fall back to copying the skill directory manually.
```

Codex may ask for confirmation before it changes `~/.codex/config.toml`, downloads marketplace data, or writes plugin cache files.

## Usage

After installation, trigger the workflow with a prompt like this:

```text
Use the codex-claude-loop workflow for this task. Codex should draft the plan first, Claude should review the plan, Claude should implement only after the plan is approved, and Codex should perform the final review.
```

For bug fixes, you can be more specific:

```text
Use codex-claude-loop to fix this bug.

Requirements:
1. Codex analyzes the issue and writes the repair plan first.
2. Claude only reviews the plan and performs implementation.
3. Codex checks the final diff, verification result, and risks.
4. If the review fails, enter the rework loop.
```

## Marketplace Note

Before publishing this repository publicly, make sure it includes a marketplace index such as:

```text
.agents/plugins/marketplace.json
```

Without a marketplace index, users may be able to clone the source, but `codex plugin marketplace add <repo>` may not discover `codex-claude-loop` as an installable plugin.
