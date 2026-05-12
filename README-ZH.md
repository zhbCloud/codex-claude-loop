# Codex Claude Loop

[English Documentation](./README.md)

Codex Claude Loop 是一个 **仅面向 Windows 的 Codex 插件**，用于实现严格的规划、委派、执行、复核工作流：

```text
Codex 主线程 -> Codex 子代理 -> 插件委派运行时 -> Claude CLI
```

Codex 负责需求理解、计划制定、最终复核、风险判断和验收。Claude 只负责计划审查和实现，并且必须由 Codex 子代理调用插件委派运行时之后才能执行。

## 重要限制

- 这个插件目前只针对 Windows。
- 推荐使用 PowerShell 7+。
- 插件委派脚本位于 `skills/codex-claude-loop/windows_scripts/`。
- 当前不提供 macOS 或 Linux 委派脚本。
- 如需实际调用 Claude，需要提前安装并登录 Claude CLI。

## 它提供什么

- 固定工作流状态：`DraftPlan`、`ReviewPlan`、`RevisePlan`、`Approved`、`Implement`、`CodexReview`、`Rework`、`Accepted`、`Rejected`。
- 强制子线程标记：`CODEX_CLAUDE_LOOP_CHILD_THREAD=1`。
- 拒绝 Codex 主线程直接调用委派入口。
- 支持 Claude 会话复用：`PrimaryReuse`、`PrimaryAnchor`、`ParallelPool`。
- 使用会话租约避免多个任务同时写入同一个 Claude 会话。
- 审计产物默认写入 `.codex/codex_claude_loop/`。
- Claude 报告必须包含固定标题。
- 当目标项目是 Git 仓库时，支持按允许路径检查 diff。
- 默认有界循环：计划审查最多 3 轮，实现返工最多 2 轮。

## Windows 委派示例

委派入口应由 Codex 子代理调用，不应由 Codex 主线程直接调用：

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

可以使用 `-DryRun` 生成产物并验证路由，不实际调用 Claude。

## 产物目录

默认产物目录：

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

## 验证

检查指定运行：

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1 -RunId <run_id>
```

检查最近一次运行：

```powershell
pwsh -NoProfile -File .\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1
```

## 安装方式

这个仓库设计为 Codex 插件。用户可以手动安装，也可以把仓库地址交给 Codex AI，让 Codex AI 检查并执行安装。

### 方式一：手动安装

#### 前置要求

- 已安装 Codex CLI。
- 已登录 Codex。
- 当前机器可以访问 GitHub。
- Windows 环境，建议安装 PowerShell 7+。
- 如果需要实际委派给 Claude，需要提前安装并登录 Claude CLI。

检查 Codex CLI：

```powershell
codex --version
```

如果尚未安装 Codex CLI，请先安装：

```powershell
npm i -g @openai/codex
```

#### 1. 添加插件 Marketplace

```powershell
codex plugin marketplace add <你的 GitHub 仓库地址>
```

示例：

```powershell
codex plugin marketplace add https://github.com/<owner>/codex-claude-loop
```

#### 2. 在 Codex 中安装插件

打开 Codex 后执行：

```text
/plugin install codex-claude-loop@<marketplace-name> --scope user
```

如果 marketplace 名称与仓库名一致，通常可以使用：

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

#### 3. 重启或刷新 Codex

安装后建议重启 Codex，或刷新插件列表。

#### 4. 验证插件是否生效

在 Codex 中发送类似请求：

```text
使用 codex-claude-loop，让 Codex 先制定计划，再通过子代理委派 Claude 执行。
```

如果插件已生效，Codex 应该会识别 `codex-claude-loop` skill，并按以下链路工作：

```text
Codex 主线程 -> Codex 子代理 -> codex-claude-loop 委派运行时 -> Claude CLI
```

### 方式二：直接交给 Codex AI 自动安装

如果不想手动安装，可以直接把下面这段话丢给 Codex：

```text
请安装并启用这个仅面向 Windows 的 Codex 插件：

GitHub 仓库：
https://github.com/<owner>/codex-claude-loop

要求：
1. 先检查我本机是否已安装 Codex CLI。
2. 如果没有安装 Codex CLI，请提示我安装 Codex CLI。
3. 确认当前系统是 Windows；如果不是 Windows，请停止安装并说明原因。
4. 检查这个仓库是否是有效 Codex 插件，确认存在 .codex-plugin/plugin.json。
5. 将该仓库作为 Codex plugin marketplace 添加。
6. 安装 codex-claude-loop 插件到 user scope。
7. 安装完成后告诉我是否需要重启 Codex。
8. 不要修改我的项目业务代码。
9. 如果任何步骤失败，请停止并说明原因，不要使用复制 skill 目录的方式兜底安装。
```

Codex 可能会在修改 `~/.codex/config.toml`、下载 marketplace 数据或写入插件缓存前请求确认。

## 使用方式

安装完成后，可以这样触发工作流：

```text
使用 codex-claude-loop 工作流处理这个任务：Codex 先制定方案，Claude 审查方案，方案通过后 Claude 再实现，最后由 Codex 复核。
```

修复 Bug 时可以更具体：

```text
用 codex-claude-loop 修复这个 Bug。

要求：
1. Codex 先分析问题并写出修复计划。
2. Claude 只负责审查计划和执行实现。
3. Codex 最后检查 diff、验证结果和风险点。
4. 未通过复核时进入 rework。
```

## Marketplace 注意事项

开源发布前，请确保仓库包含 marketplace 索引，例如：

```text
.agents/plugins/marketplace.json
```

如果没有 marketplace 索引，用户可能可以克隆源码，但 `codex plugin marketplace add <repo>` 可能无法发现 `codex-claude-loop` 这个可安装插件。
