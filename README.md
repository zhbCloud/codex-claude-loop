# Codex Claude Loop

[中文说明](./README-ZH.md)

Codex Claude Loop is a **Windows-only Codex plugin** for a strict Codex-led planning, delegation, implementation, rework, and acceptance workflow:

```text
Codex main thread -> Codex child agent -> plugin delegate runtime -> Claude CLI
```

Codex owns requirement analysis, planning, task decomposition, scheduling, risk judgment, code review, and final acceptance. Claude Code only acts as the implementation layer inside a Codex child agent, executing approved Codex tasks such as writing code, editing files, running specified validation commands, and applying Codex-requested rework.

## Important Limitations

- This plugin currently targets Windows only.
- PowerShell 7+ is recommended.
- Delegate scripts live under `plugins/codex-claude-loop/skills/codex-claude-loop/windows_scripts/`.
- macOS and Linux delegate scripts are not provided.
- Claude CLI must be installed and logged in if you want the runtime to actually call Claude.

## What It Provides

- Fixed workflow states: `DraftPlan`, `Approved`, `Implement`, `CodexReview`, `Rework`, `Accepted`, `Rejected`.
- Hard child-thread marker: `CODEX_CLAUDE_LOOP_CHILD_THREAD=1`.
- Direct main-thread delegate invocation is rejected.
- Reusable Claude sessions with `PrimaryReuse`, `PrimaryAnchor`, and `ParallelPool`.
- Session leases to avoid concurrent writes to the same Claude session.
- Audit artifacts under `.codex/codex_claude_loop/`.
- Structured Claude reports with required headings.
- Allowed-path diff checks when the target project is a Git repository.
- Default bounded loop: implementation rework up to 2 rounds.

## Windows Delegate Example

The delegate entrypoint is intended to be run by a Codex child agent, not by the Codex main thread:

```powershell
$env:CODEX_CLAUDE_LOOP_CHILD_THREAD = '1'
pwsh -NoProfile -File .\plugins\codex-claude-loop\skills\codex-claude-loop\windows_scripts\delegate_to_claude.ps1 `
  -TaskFile .\.codex\codex_claude_loop\tasks\20260512\001-implementation.md `
  -TaskMode implementation `
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
pwsh -NoProfile -File .\plugins\codex-claude-loop\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1 -RunId <run_id>
```

Check the latest run:

```powershell
pwsh -NoProfile -File .\plugins\codex-claude-loop\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1
```

## Installation

This repository is intended to be distributed as a Codex plugin marketplace. The marketplace file lives at `.agents/plugins/marketplace.json`, and the actual plugin lives under `plugins/codex-claude-loop/`. The recommended path is to ask Codex AI to inspect the repository and perform the installation; you can also install it manually.

### Method 1: Ask Codex AI to Install It

If you do not want to install it manually, give Codex this prompt:

```text
Please install and enable this Windows-only Codex plugin:

GitHub repository:
https://github.com/zhbCloud/codex-claude-loop.git

Requirements:
1. First check whether Codex CLI is installed on my machine.
2. If Codex CLI is not installed, tell me how to install it.
3. Confirm that the current system is Windows. If it is not Windows, stop the installation and explain why.
4. Check whether this repository is a valid Codex marketplace and confirm that plugins/codex-claude-loop/.codex-plugin/plugin.json exists.
5. Add this repository as a Codex plugin marketplace.
6. Install the codex-claude-loop plugin with user scope.
7. After installation, tell me whether I need to restart Codex.
8. Do not modify my project business code.
9. If any step fails, stop and explain the reason. Do not fall back to copying the skill directory manually.
```

Codex may ask for confirmation before it changes `~/.codex/config.toml`, downloads marketplace data, or writes plugin cache files.

### Method 2: Manual Installation

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

#### 0. Run the Installation Doctor

Before adding the marketplace, run the local doctor script from the repository root:

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1
```

The doctor checks the Windows requirement, Codex CLI availability, marketplace JSON, plugin layout, manifest path, skill path, README stale paths, and whether Codex can read the plugin through `plugin/read`.

For CI or repository-only validation, skip machine-specific Codex checks:

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1 -SkipCodexCli -SkipCodexRead
```

#### 1. Add the Plugin Marketplace

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

#### 2. Install the Plugin from Codex

Open Codex Desktop and use the plugin list or plugin install flow to install `codex-claude-loop@codex-claude-loop` with user scope.

If your Codex CLI build exposes plugin slash commands, you can also run this PowerShell command in your terminal to open the Codex CLI interactive interface:

```powershell
codex
```

Then type this slash command inside the Codex CLI interface:

```text
/plugin install codex-claude-loop@<marketplace-name> --scope user
```

`/plugin install ...` is not a PowerShell command. It must be entered inside the Codex CLI interactive interface opened by `codex`. If your Codex build does not expose this slash command, use the Codex Desktop plugin install flow instead.

If your marketplace name matches the repository name, the command is usually:

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

#### Troubleshooting: Local Plugin Path Format

If installation reports an error like one of these:

```text
local plugin source path must start with `./`
local plugin source path must not be empty
local plugin source path must stay within the marketplace root
```

Check the marketplace file:

```text
.agents/plugins/marketplace.json
```

The local plugin source path must point to the plugin subdirectory inside this marketplace:

```json
"path": "./plugins/codex-claude-loop"
```

Do not use `"path": "./"` for this repository. Codex treats the marketplace root and the plugin root as separate concepts, so the plugin must live in a non-empty child directory such as `plugins/codex-claude-loop/`.

#### 3. Restart or Refresh Codex

After installation, restart Codex or refresh the plugin list.

#### 4. Verify the Plugin

Send a prompt like this in Codex:

```text
Use codex-claude-loop so Codex drafts and approves the plan first, then delegates only the implementation work to Claude Code through a child agent.
```

If the plugin is active, Codex should recognize the `codex-claude-loop` skill and follow this chain:

```text
Codex main thread -> Codex child agent -> codex-claude-loop delegate runtime -> Claude CLI
```

## Usage

Copy a prompt and replace the `<...>` placeholders with your real task details.

### Fix a Bug

Short version:

```text
Use codex-claude-loop to fix this bug: <describe the bug>
```

With constraints:

```text
Use codex-claude-loop to fix this bug: <describe the bug>

Requirements:
- Codex analyzes the issue and approves the repair plan.
- Claude Code only implements the approved fix.
- Codex reviews the final diff and validation result.
```

### Build a Feature

Short version:

```text
Use codex-claude-loop to implement this feature: <describe the feature>
```

With constraints:

```text
Use codex-claude-loop to implement this feature: <describe the feature>

Requirements:
- Codex defines scope and acceptance criteria first.
- Claude Code only writes approved code changes.
- Codex reviews the final diff, validation result, and risks.
```

### Refactor a Module

Short version:

```text
Use codex-claude-loop to refactor this module: <module or file path>
```

With constraints:

```text
Use codex-claude-loop to refactor this module: <module or file path>

Requirements:
- Keep existing behavior unchanged.
- Limit edits to the specified module or files.
- Codex reviews the final diff before acceptance.
```

### Fix Build or Test Failures

Short version:

```text
Use codex-claude-loop to fix these build or test failures: <paste error or failing command>
```

With constraints:

```text
Use codex-claude-loop to fix these build or test failures: <paste error or failing command>

Requirements:
- Codex identifies the likely cause first.
- Claude Code only implements the approved fix.
- Codex checks that the requested validation passes.
```

### Work Within a File Scope

Short version:

```text
Use codex-claude-loop for this task: <describe the task>. Only modify these files: <file-list>.
```

With constraints:

```text
Use codex-claude-loop for this task: <describe the task>

Allowed files:
- <file path 1>
- <file path 2>

Requirements:
- Claude Code must stay inside the allowed file scope.
- Codex rejects changes outside the scope.
```

### Rework a Previous Attempt

Short version:

```text
Use codex-claude-loop to rework the previous implementation: <describe what must be fixed>
```

With constraints:

```text
Use codex-claude-loop to rework the previous implementation: <describe what must be fixed>

Requirements:
- Codex lists the rejection findings first.
- Claude Code only fixes those findings.
- Codex reviews the rework before acceptance.
```

## Marketplace Note

This repository includes a marketplace index:

```text
.agents/plugins/marketplace.json
```

The marketplace entry points to the plugin subdirectory:

```text
plugins/codex-claude-loop/
```

The plugin manifest lives at:

```text
plugins/codex-claude-loop/.codex-plugin/plugin.json
```

This repository also includes a CI workflow that runs `scripts/doctor.ps1 -SkipCodexCli -SkipCodexRead` on push and pull request, so marketplace layout regressions are caught before release.
