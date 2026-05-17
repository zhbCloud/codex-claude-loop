# Codex Claude Loop

[中文说明](./README-ZH.md)

Codex Claude Loop is a **Windows-only Codex plugin** for a strict Codex-led planning, delegation, implementation, rework, and acceptance workflow:

```text
Codex main thread -> Codex child agent -> plugin delegate runtime -> Claude CLI
```

Codex owns requirement analysis, planning, task decomposition, scheduling, risk judgment, code review, and final acceptance. Claude Code only acts as the implementation layer inside a Codex child agent, executing approved Codex tasks such as writing code, editing files, running specified validation commands, and applying Codex-requested rework.

When the user explicitly asks to use Codex Claude Loop, the Codex main thread should not directly edit production source files as a fallback implementation path. If delegation fails, Codex should adjust the task, scope, session, or validation command and delegate rework, or report the blocker to the user.

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
- Allowed-path diff checks when the target project is a Git repository; `-AllowedPath .`, `./`, or the repository root absolute path means the current repository scope.
- Default bounded loop: implementation rework up to 2 rounds.

## Runtime Notes

- In PowerShell, pass multiple validation commands as one array binding: `-ValidationCommand @("node --check src/a.js", "node --check src/b.js")`. Do not repeat the `-ValidationCommand` parameter name.
- If a delegate returns `status=failed`, Codex main thread must not silently treat the worktree edits as accepted. It should create an explicit Claude rework task, or stop and ask the user whether to leave the loop workflow.
- When the user prompt triggers `codex-claude-loop`, delegation, multi-agent, or Claude Code routing, the hook writes `.codex/codex_claude_loop/loop_mode.json` and enables loop mode. In loop mode, main-thread `apply_patch`, shell write commands, dependency installs, and other production-source writes are denied; `.codex/codex_claude_loop/` task files, child-thread delegate calls, and validation commands are allowed.
- To disable loop mode, explicitly ask Codex to "disable codex-claude-loop loop mode" or "exit loop mode".

## Installation

This repository is intended to be distributed as a Codex plugin marketplace. The marketplace file lives at `.agents/plugins/marketplace.json`, and the actual plugin lives under `plugins/codex-claude-loop/`.

The steps below explicitly say where each command or prompt should be entered. Do not paste PowerShell commands into the Codex chat box, and do not paste natural-language requests for Codex AI into PowerShell.

### Where to Run Things

- `PowerShell terminal`: Windows Terminal, PowerShell 7, or regular PowerShell. Run commands like `codex --version`, `codex plugin marketplace add ...`, `codex plugin marketplace upgrade ...`, and `pwsh -File ...` here.
- `Codex Desktop chat box`: Send natural-language requests to Codex AI when you want Codex to inspect, install, or troubleshoot for you.
- `Codex CLI interactive interface`: Run `codex` from PowerShell first, then type into the interactive Codex interface. Slash commands such as `/plugin install ...` may belong here; they are not PowerShell commands.
- `Codex Desktop plugin list`: View, install, enable, or disable plugins. The exact entry name may vary slightly across Codex versions.

### Quick Start

1. Check Codex CLI in a `PowerShell terminal`.
2. Run the installation doctor in a `PowerShell terminal`.
3. Add the marketplace in a `PowerShell terminal`.
4. Install the plugin from the `Codex Desktop plugin list` or the `Codex CLI interactive interface`.
5. Restart Codex Desktop or open a new session.
6. Verify that the plugin is present in the new Codex session context from a `PowerShell terminal`.

### Method 1: Ask Codex AI to Install It

If you do not want to install it manually, send this one-line prompt to the `Codex Desktop chat box` or the `Codex CLI interactive interface`. Codex AI should follow [AI_INSTALL.md](./AI_INSTALL.md) from this repository. Do not paste this prompt into PowerShell.

```text
Please install or update https://github.com/zhbCloud/codex-claude-loop as a Windows-only Codex plugin in the current Codex environment, following the repository AI_INSTALL.md.
```

Codex may ask for confirmation before it changes `~/.codex/config.toml`, downloads marketplace data, or writes plugin cache files. Before approving, check whether Codex is about to run a PowerShell command, use a Codex plugin command, or modify files.
### Method 2: Manual Installation

#### Requirements

- Codex CLI is installed.
- Codex is logged in.
- The machine can access GitHub.
- Windows is required, and PowerShell 7+ is recommended.
- Claude CLI must be installed and logged in if you want the delegate runtime to actually call Claude.

#### 0. Check Codex CLI

Run this in a `PowerShell terminal`:

```powershell
codex --version
```

If Codex CLI is not installed, install it from a `PowerShell terminal`:

```powershell
npm i -g @openai/codex
```

#### 1. Run the Installation Doctor

Run this in a `PowerShell terminal`, with the current directory set to the repository root:

```powershell
cd D:\Desktop\codex-claude-loop
pwsh -NoProfile -File .\scripts\doctor.ps1
```

The doctor checks the Windows requirement, Codex CLI availability, marketplace JSON, plugin layout, manifest path, skill path, README stale paths, and whether Codex can read the plugin through `plugin/read`.

For CI or repository-only validation, skip machine-specific Codex checks from a `PowerShell terminal`:

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1 -SkipCodexCli -SkipCodexRead
```

#### 2. Add the Plugin Marketplace

Run this in a `PowerShell terminal`:

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

If you already added the marketplace, Codex may say it already exists. That is usually not an error; continue with installation or update.

#### 3. Install the Plugin

Recommended location: `Codex Desktop plugin list`.

Open Codex Desktop, open the plugin list, find `Codex Claude Loop` or `codex-claude-loop@codex-claude-loop`, then install and enable it with user scope. After installation, restart Codex Desktop or at least open a new session.

Optional location: `Codex CLI interactive interface`.

If your Codex CLI build exposes plugin slash commands, first run this in a `PowerShell terminal`:

```powershell
codex
```

After entering the `Codex CLI interactive interface`, type this slash command:

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

Important: `/plugin install ...` is not a PowerShell command. Do not run it directly in a PowerShell terminal. If your Codex build does not expose this slash command, use the Codex Desktop plugin list instead.

#### 4. Restart or Refresh Codex

Location: `Codex Desktop`.

After installation, restart Codex Desktop. Even if the plugin is installed correctly, currently open sessions may still use an older skill context; a new session is better for verification.

#### 5. Verify the Plugin

Run this in a `PowerShell terminal`:

```powershell
codex debug prompt-input "verify codex-claude-loop is active" | Select-String "codex-claude-loop:codex-claude-loop"
```

If the output includes something like this, the plugin is present in the new Codex session context:

```text
codex-claude-loop:codex-claude-loop
file: r3/codex-claude-loop/<version>/skills/codex-claude-loop/SKILL.md
```

You can also send this prompt in the `Codex Desktop chat box` or a newly opened `Codex CLI interactive interface`:

```text
Use codex-claude-loop so Codex drafts and approves the plan first, then delegates only the implementation work to Claude Code through a child agent.
```

If the plugin is active, Codex should recognize the `codex-claude-loop` skill and follow this chain:

```text
Codex main thread -> Codex child agent -> codex-claude-loop delegate runtime -> Claude CLI
```

## Updating the Plugin

If you already installed `codex-claude-loop`, update the local marketplace and installed plugin cache after this repository changes.

### Recommended Update Flow

1. Close Codex Desktop so plugin cache files are not in use.
2. Open a new `PowerShell terminal`.
3. Run the marketplace upgrade command.
4. Restart Codex Desktop or open a new session.
5. Verify that the plugin is present in the new session context.

Run this in a `PowerShell terminal`:

```powershell
codex plugin marketplace upgrade codex-claude-loop
```

If you see this, the marketplace is already up to date:

```text
Marketplace `codex-claude-loop` is already up to date.
```

It is also normal for Codex to report that the marketplace was upgraded. Restart Codex Desktop after upgrading.

### Verify the Update

Run this in a `PowerShell terminal`:

```powershell
(codex debug prompt-input "verify codex-claude-loop is updated" | Select-String -Pattern "codex-claude-loop/[0-9]+\.[0-9]+\.[0-9]+" -AllMatches).Matches.Value
```

If the output looks like `codex-claude-loop/<version>`, that version is present in the Codex session context.

## Troubleshooting

### Codex Claude Loop Does Not Appear in the Plugin List

First confirm that you added the marketplace from a `PowerShell terminal`:

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

Then restart Codex Desktop. If it still does not appear, run:

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1
```

### Local Plugin Path Format Errors

If installation or update reports an error like one of these:

```text
local plugin source path must start with `./`
local plugin source path must not be empty
local plugin source path must stay within the marketplace root
```

Check the marketplace file:

```text
.agents/plugins/marketplace.json
```

The correct path must point to the plugin subdirectory inside this marketplace:

```json
"path": "./plugins/codex-claude-loop"
```

Do not use `"path": "./"` for this repository. Codex treats the marketplace root and the plugin root as separate concepts, so the plugin must live in a non-empty child directory such as `plugins/codex-claude-loop/`.

### Update Fails with `Access is denied. (os error 5)`

If `codex plugin marketplace upgrade codex-claude-loop` reports something like this:

```text
failed to back up plugin cache entry: Access is denied. (os error 5)
```

Codex Desktop or another Codex process is usually holding plugin cache files open, or the cache directory has abnormal permissions.

Try this order:

1. Close all Codex Desktop windows.
2. Close running Codex CLI sessions.
3. Open a new `PowerShell terminal`.
4. Run the upgrade again:

```powershell
codex plugin marketplace upgrade codex-claude-loop
```

If it still fails, inspect cache permissions:

```powershell
Get-Acl "$env:USERPROFILE\.codex\plugins\cache\codex-claude-loop" | Format-List Owner,AccessToString
```

Do not fall back to manually copying the `skills` directory. That bypasses Codex plugin cache, version, and enablement management, which makes future troubleshooting harder.

### `codex debug prompt-input` Prints Too Much

Run this in a `PowerShell terminal` and search only for the skill name:

```powershell
codex debug prompt-input "verify codex-claude-loop" | Select-String "codex-claude-loop:codex-claude-loop"
```

Seeing `codex-claude-loop:codex-claude-loop` usually means the plugin skill is present in the new session context.

## Usage

Copy a prompt and replace the `<...>` placeholders with your real task details.

### Use in Codex App

Location: `Codex Desktop/App chat box`.

Codex App has a visual plugin menu. Click `Plugins` near the lower-left area of the chat box, choose `Codex Claude Loop`, then type your task prompt in the chat box.

Example:

```text
Use codex-claude-loop to fix this bug: <describe the bug>

Requirements:
- Codex analyzes the issue and approves the repair plan.
- Claude Code only implements the approved fix.
- Codex reviews the final diff and validation result.
```

Even if you selected `Codex Claude Loop` from the plugin menu, it is still helpful to keep `Use codex-claude-loop` in the prompt so Codex clearly knows this task should follow the plugin workflow.

### Use in Codex CLI

Codex CLI usually does not have the same visual plugin menu as Codex App. In CLI, use the plugin by explicitly writing `Use codex-claude-loop ...` in your prompt so the new Codex session can load and trigger the installed skill.

Do not run `Codex Claude Loop`, `codex-claude-loop`, or `/plugin install ...` in PowerShell to “run the plugin”. `/plugin install ...` is an installation command, not a usage command, and it only belongs inside the Codex CLI interactive interface if your Codex build supports it.

#### CLI Interactive Usage

First enter your target project from a `PowerShell terminal`, then start Codex CLI:

```powershell
cd D:\your-project
codex
```

After entering the `Codex CLI interactive interface`, type a natural-language task:

```text
Use codex-claude-loop to implement this feature: <describe the feature>

Requirements:
- Codex defines scope and acceptance criteria first.
- Claude Code only writes approved code changes.
- Codex reviews the final diff, validation result, and risks.
```

#### CLI One-Shot Prompt Usage

Run this in a `PowerShell terminal`:

```powershell
codex -C D:\your-project "Use codex-claude-loop to fix this bug: <describe the bug>"
```

This starts one Codex task with a single prompt. For complex work, the interactive CLI or Codex App is usually better because Codex can clarify requirements, propose a plan, and wait for confirmation.

#### Verify That CLI Loaded the Plugin

Run this in a `PowerShell terminal`:

```powershell
codex debug prompt-input "Use codex-claude-loop to test plugin loading" | Select-String "codex-claude-loop:codex-claude-loop"
```

If the output includes `codex-claude-loop:codex-claude-loop`, the Codex CLI new-session context can see the plugin skill.

### Common Prompts

Fix a bug:

```text
Use codex-claude-loop to fix this bug: <describe the bug>
```

Build a feature:

```text
Use codex-claude-loop to implement this feature: <describe the feature>
```

Work within a file scope:

```text
Use codex-claude-loop for this task: <describe the task>. Only modify these files: <file-list>.
```

Rework a previous attempt:

```text
Use codex-claude-loop to rework the previous implementation: <describe what must be fixed>
```

Most users do not need to run the internal delegate script directly. Trigger the plugin from Codex App, the Codex CLI interactive interface, or a natural-language command such as `codex -C ... "Use codex-claude-loop ..."`.

## Development

### Automatic Plugin Version Bump

When changing plugin capability files, enable the repository git hook once:

```powershell
pwsh -NoProfile -File .\scripts\install-git-hooks.ps1
```

The pre-commit hook runs `scripts/bump-plugin-version.ps1`. If files under `plugins/codex-claude-loop/skills/`, `plugins/codex-claude-loop/hooks/`, or `plugins/codex-claude-loop/.codex-plugin/plugin.json` changed and the manifest version was not already edited, it bumps the plugin manifest patch version and stages it.

For CI or manual checks without editing files, run:

```powershell
pwsh -NoProfile -File .\scripts\bump-plugin-version.ps1 -CheckOnly
```
