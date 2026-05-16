# Codex Claude Loop

[English Documentation](./README.md)

Codex Claude Loop 是一个 **仅面向 Windows 的 Codex 插件**，用于实现严格的 Codex 主导规划、委派、实现、返工和验收工作流：

```text
Codex 主线程 -> Codex 子代理 -> 插件委派运行时 -> Claude CLI
```

Codex 负责需求理解、计划制定、任务拆解、调度、风险判断、代码复核和最终验收。Claude Code 只作为 Codex 子代理中的实现层，负责执行 Codex 已批准的具体实现任务，例如写代码、修改文件、运行指定验证命令和按 Codex 反馈进行返工。

## 重要限制

- 这个插件目前只针对 Windows。
- 推荐使用 PowerShell 7+。
- 插件委派脚本位于 `plugins/codex-claude-loop/skills/codex-claude-loop/windows_scripts/`。
- 当前不提供 macOS 或 Linux 委派脚本。
- 如需实际调用 Claude，需要提前安装并登录 Claude CLI。

## 它提供什么

- 固定工作流状态：`DraftPlan`、`Approved`、`Implement`、`CodexReview`、`Rework`、`Accepted`、`Rejected`。
- 强制子线程标记：`CODEX_CLAUDE_LOOP_CHILD_THREAD=1`。
- 拒绝 Codex 主线程直接调用委派入口。
- 支持 Claude 会话复用：`PrimaryReuse`、`PrimaryAnchor`、`ParallelPool`。
- 使用会话租约避免多个任务同时写入同一个 Claude 会话。
- 审计产物默认写入 `.codex/codex_claude_loop/`。
- Claude 报告必须包含固定标题。
- 当目标项目是 Git 仓库时，支持按允许路径检查 diff。
- 默认有界循环：实现返工最多 2 轮。

## Windows 委派示例

委派入口应由 Codex 子代理调用，不应由 Codex 主线程直接调用：

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
pwsh -NoProfile -File .\plugins\codex-claude-loop\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1 -RunId <run_id>
```

检查最近一次运行：

```powershell
pwsh -NoProfile -File .\plugins\codex-claude-loop\skills\codex-claude-loop\windows_scripts\verify_artifacts.ps1
```

## 安装方式

这个仓库设计为 Codex 插件 marketplace。marketplace 文件位于 `.agents/plugins/marketplace.json`，实际插件位于 `plugins/codex-claude-loop/`。推荐优先把仓库地址交给 Codex AI，让 Codex AI 检查并执行安装；也可以按下面的手动步骤安装。

### 方式一：直接交给 Codex AI 自动安装

如果不想手动安装，可以直接把下面这段话丢给 Codex：

```text
请安装并启用这个仅面向 Windows 的 Codex 插件：

GitHub 仓库：
https://github.com/zhbCloud/codex-claude-loop.git

要求：
1. 先检查我本机是否已安装 Codex CLI。
2. 如果没有安装 Codex CLI，请提示我安装 Codex CLI。
3. 确认当前系统是 Windows；如果不是 Windows，请停止安装并说明原因。
4. 检查这个仓库是否是有效 Codex marketplace，确认存在 plugins/codex-claude-loop/.codex-plugin/plugin.json。
5. 将该仓库作为 Codex plugin marketplace 添加。
6. 安装 codex-claude-loop 插件到 user scope。
7. 安装完成后告诉我是否需要重启 Codex。
8. 不要修改我的项目业务代码。
9. 如果任何步骤失败，请停止并说明原因，不要使用复制 skill 目录的方式兜底安装。
```

Codex 可能会在修改 `~/.codex/config.toml`、下载 marketplace 数据或写入插件缓存前请求确认。

### 方式二：手动安装

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

#### 0. 运行安装前自检

添加 marketplace 前，先在仓库根目录运行本地 doctor 脚本：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1
```

doctor 会检查 Windows 要求、Codex CLI 是否可用、marketplace JSON、插件目录布局、manifest 路径、skill 路径、README 旧路径残留，以及 Codex 是否能通过 `plugin/read` 读取插件。

如果只想在 CI 或仓库校验中检查结构，不检查本机 Codex 环境，可以跳过机器相关检查：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1 -SkipCodexCli -SkipCodexRead
```

#### 1. 添加插件 Marketplace

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

#### 2. 在 Codex 中安装插件

打开 Codex Desktop，通过插件列表或插件安装流程，将 `codex-claude-loop@codex-claude-loop` 安装到 user scope。

如果你的 Codex CLI 版本提供插件斜杠命令，也可以先在终端执行下面的 PowerShell 命令，进入 Codex CLI 交互式界面：

```powershell
codex
```

然后在打开的 Codex CLI 界面中输入下面这个斜杠命令：

```text
/plugin install codex-claude-loop@<marketplace-name> --scope user
```

`/plugin install ...` 不是 PowerShell 命令，必须输入到 `codex` 打开的 Codex CLI 交互式界面中。如果你的 Codex 版本不提供这个斜杠命令，请改用 Codex Desktop 的插件安装流程。

如果 marketplace 名称与仓库名一致，通常可以使用：

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

#### 故障排查：本地插件路径格式错误

如果安装时看到类似错误：

```text
local plugin source path must start with `./`
local plugin source path must not be empty
local plugin source path must stay within the marketplace root
```

请检查 marketplace 文件：

```text
.agents/plugins/marketplace.json
```

本地插件源路径必须指向 marketplace 内部的插件子目录：

```json
"path": "./plugins/codex-claude-loop"
```

不要在这个仓库中使用 `"path": "./"`。Codex 会区分 marketplace 根目录和插件根目录，因此插件必须位于非空子目录，例如 `plugins/codex-claude-loop/`。

#### 3. 重启或刷新 Codex

安装后建议重启 Codex，或刷新插件列表。

#### 4. 验证插件是否生效

在 Codex 中发送类似请求：

```text
使用 codex-claude-loop，让 Codex 先理解需求、制定并批准计划，再通过子代理只把实现工作委派给 Claude Code。
```

如果插件已生效，Codex 应该会识别 `codex-claude-loop` skill，并按以下链路工作：

```text
Codex 主线程 -> Codex 子代理 -> codex-claude-loop 委派运行时 -> Claude CLI
```

## 使用方式

复制提示词后，把 `<...>` 占位内容替换成你的真实任务。

### 修复 Bug

最短写法：

```text
使用 codex-claude-loop 修复这个 Bug：<描述 Bug>
```

带约束写法：

```text
使用 codex-claude-loop 修复这个 Bug：<描述 Bug>

要求：
- Codex 先分析问题并批准修复方案。
- Claude Code 只实现已批准的修复。
- Codex 最后检查 diff 和验证结果。
```

### 实现新功能

最短写法：

```text
使用 codex-claude-loop 实现这个功能：<描述功能需求>
```

带约束写法：

```text
使用 codex-claude-loop 实现这个功能：<描述功能需求>

要求：
- Codex 先明确修改范围和验收标准。
- Claude Code 只编写已批准的代码改动。
- Codex 最后检查 diff、验证结果和风险点。
```

### 重构指定模块

最短写法：

```text
使用 codex-claude-loop 重构这个模块：<模块或文件路径>
```

带约束写法：

```text
使用 codex-claude-loop 重构这个模块：<模块或文件路径>

要求：
- 保持现有行为不变。
- 只修改指定模块或文件。
- Codex 验收前必须检查最终 diff。
```

### 修复构建或测试失败

最短写法：

```text
使用 codex-claude-loop 修复这些构建或测试失败：<粘贴报错或失败命令>
```

带约束写法：

```text
使用 codex-claude-loop 修复这些构建或测试失败：<粘贴报错或失败命令>

要求：
- Codex 先判断可能原因。
- Claude Code 只实现已批准的修复。
- Codex 检查指定验证命令是否通过。
```

### 限定文件范围

最短写法：

```text
使用 codex-claude-loop 处理这个任务：<描述任务>。只允许修改这些文件：<文件列表>。
```

带约束写法：

```text
使用 codex-claude-loop 处理这个任务：<描述任务>

允许修改的文件：
- <文件路径 1>
- <文件路径 2>

要求：
- Claude Code 必须保持在允许文件范围内。
- Codex 拒绝范围外改动。
```

### 返工上一次实现

最短写法：

```text
使用 codex-claude-loop 返工上一次实现：<描述需要修复的问题>
```

带约束写法：

```text
使用 codex-claude-loop 返工上一次实现：<描述需要修复的问题>

要求：
- Codex 先列出拒绝原因。
- Claude Code 只修复这些问题。
- Codex 复核返工结果后再决定是否验收。
```

## Marketplace 注意事项

本仓库已包含 marketplace 索引：

```text
.agents/plugins/marketplace.json
```

marketplace 条目会指向插件子目录：

```text
plugins/codex-claude-loop/
```

插件清单位于：

```text
plugins/codex-claude-loop/.codex-plugin/plugin.json
```

本仓库还包含一个 CI 工作流，会在 push 和 pull request 时运行 `scripts/doctor.ps1 -SkipCodexCli -SkipCodexRead`，用于在发布前发现 marketplace 布局回退问题。
