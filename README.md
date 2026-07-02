# Codex Claude Loop

[English Documentation](./README.en.md)

Codex Claude Loop 是一个 **面向 Windows 和 macOS 的 Codex 插件**，用于实现严格的 Codex 主导规划、委派、实现、返工和验收工作流：

```text
Codex 主线程 -> Codex 子代理 -> 插件委派运行时 -> Claude CLI
```

Codex 负责需求理解、计划制定、任务拆解、调度、风险判断、代码复核和最终验收。Claude Code 只作为 Codex 子代理中的实现层，负责执行 Codex 已批准的具体实现任务，例如写代码、修改文件、运行指定验证命令和按 Codex 反馈进行返工。

当用户明确要求使用 Codex Claude Loop 时，Codex 主线程不应直接修改生产源码来兜底实现。委派失败时，Codex 应调整任务、scope、会话或验证命令后继续委派返工，或者向用户报告阻塞。

## 重要限制

- Windows 使用 PowerShell 7+ 包装器，位于 `plugins/codex-claude-loop/skills/codex-claude-loop/windows_scripts/`。
- macOS 使用系统 `zsh` 和 Python 3.10+ 包装器，位于 `plugins/codex-claude-loop/skills/codex-claude-loop/macos_scripts/`。
- 委派入口分别是 `windows_scripts/delegate_to_claude.ps1` 和 `macos_scripts/delegate_to_claude.sh`。
- 当前不提供或验证 Linux 委派脚本。
- 如需实际调用 Claude，需要提前安装并登录 Claude CLI。
- macOS 上 Codex Desktop 可能以较短的 GUI `PATH` 启动；运行时会先查 `PATH`，再尝试 `/opt/homebrew/bin/claude`、`/usr/local/bin/claude` 等常见 Claude CLI 路径。

## 它提供什么

- 固定工作流状态：`DraftPlan`、`Approved`、`Implement`、`CodexReview`、`Rework`、`Accepted`、`Rejected`。
- 强制子线程标记：`CODEX_CLAUDE_LOOP_CHILD_THREAD=1`。
- 拒绝 Codex 主线程直接调用委派入口。
- 支持 Claude 会话复用：`PrimaryReuse`、`PrimaryAnchor`、`ParallelPool`。
- 使用会话租约避免多个任务同时写入同一个 Claude 会话。
- 审计产物默认写入 `.codex/codex_claude_loop/`。
- 使用 artifact schema v3 记录 run gate、workflow、reviewer 证据和 final-verifier 验收信息。
- 支持 fast/strict 双模式：fast 面向个人高频小任务，strict 面向复杂项目，带任务契约、reviewer 证据和 final-verifier gate。
- Claude 报告必须包含固定标题。
- strict 任务文件可通过 `windows_scripts/validate_delegate_task.ps1` 或 `macos_scripts/validate_delegate_task.sh` 预校验。
- 当目标项目是 Git 仓库时，支持按允许路径检查 diff；Windows 使用 `-AllowedPath .`，macOS 使用 `--allowed-path .` 表示允许当前仓库范围。
- 默认有界循环：实现返工最多 2 轮。

## 运行注意事项

- PowerShell 中多条验证命令必须用数组形式传给同一个参数：`-ValidationCommand @("node --check src/a.js", "node --check src/b.js")`。不要重复写多个 `-ValidationCommand` 参数。
- macOS `zsh` 中，每个值重复一次长参数，例如 `--validation-command "node --check src/a.js" --validation-command "node --check src/b.js"`。
- 简单、边界清晰的个人高频任务用 `-WorkMode fast`；复杂、并行、迁移、reviewer 或 final-verifier 工作流用 `-WorkMode strict`。默认 `auto` 会在任务形态需要证据链时自动进入 strict，否则保持 fast。
- 当前仍保持单一插件 skill 入口，但文档把工作流拆成 planning、dispatching、reviewing、finishing 四个阶段职责。Windows 和 macOS 共享同一套 Python Runtime 与 artifact 契约；Linux 不在当前支持边界内。
- strict 模式任务文件必须包含 `Goal`、`Allowed Scope`、`Forbidden Actions`、`Acceptance Criteria`、`Verification`、`Report Requirements`。派发前使用对应平台脚本校验。
- 如果 delegate 返回 `status=failed`，Codex 主线程不能直接把工作树中的改动视为通过；应创建明确的 rework 任务交给 Claude，或停止并让用户决定是否离开 loop 工作流。
- 当用户提示中触发 `codex-claude-loop`、委派、多代理、Claude Code 等关键词时，hook 会写入 `.codex/codex_claude_loop/loop_mode.json` 并启用 loop 模式。loop 模式下，主线程的 `apply_patch`、shell 写文件命令、安装依赖等生产源码写入会被拒绝；`.codex/codex_claude_loop/` 任务文件、子线程 delegate 调用和验证命令会被放行。
- 如需关闭 loop 模式，可以在 Codex 中明确说“关闭 codex-claude-loop loop 模式”或“退出 loop 模式”。

## 安装方式

这个仓库设计为 Codex 插件 marketplace。marketplace 文件位于 `.agents/plugins/marketplace.json`，实际插件位于 `plugins/codex-claude-loop/`。

下面的步骤会明确标注命令应该在哪里执行。请不要把终端命令发到 Codex 聊天框里，也不要把给 Codex AI 的自然语言请求复制到终端里执行。

### 命令应该在哪里执行

- `PowerShell 终端`：Windows Terminal、PowerShell 7、普通 PowerShell 窗口都可以。示例中的 `codex --version`、`codex plugin marketplace add ...`、`codex plugin marketplace upgrade ...`、`pwsh -File ...` 都在这里执行。
- `macOS 终端`：使用 Terminal 或其他运行 `zsh` 的终端。`codex`、`python3`、marketplace 命令和 `macos_scripts/*.sh` 都在这里执行。
- `Codex Desktop 聊天框`：把自然语言请求发给 Codex AI，让它帮你检查、安装或排障。
- `Codex CLI 交互界面`：在 PowerShell 中运行 `codex` 后打开的交互式界面。只有这里才可能输入 `/plugin install ...` 这类斜杠命令；它不是 PowerShell 命令。
- `Codex Desktop 插件列表`：用于查看、安装、启用或禁用插件。不同版本的入口名称可能略有不同。

### 快速开始

1. 在当前平台终端中检查 Codex CLI。
2. 使用仓库克隆开发时，运行对应平台仓库检查。
3. 在当前平台终端中添加 marketplace。
4. 在 `Codex Desktop 插件列表` 或 `Codex CLI 交互界面` 中安装插件。
5. 重启 Codex Desktop 或开启一个新会话。
6. 在当前平台终端中验证插件是否进入 Codex 上下文。

### 方式一：直接交给 Codex AI 自动安装

如果不想手动安装，可以把下面这一句话发送到 `Codex Desktop 聊天框` 或 `Codex CLI 交互界面`，让 Codex AI 按仓库里的 [AI_INSTALL.md](./AI_INSTALL.md) 执行安装或更新。不要把这句话粘贴到 PowerShell 里。

```text
请把 https://github.com/zhbCloud/codex-claude-loop 这个支持 Windows 和 macOS 的 Codex 插件安装或更新到当前 Codex 环境，并按仓库 AI_INSTALL.md 执行。
```

Codex 可能会在修改 `~/.codex/config.toml`、下载 marketplace 数据或写入插件缓存前请求确认。确认前请看清它准备执行的是 PowerShell 命令、Codex 插件命令，还是文件修改。
### 方式二：手动安装

#### 前置要求

- 已安装 Codex CLI。
- 已登录 Codex。
- 当前机器可以访问 GitHub。
- Windows 环境需要 PowerShell 7+；macOS 环境需要 `zsh` 和 Python 3.10+。
- 如果需要实际委派给 Claude，需要提前安装并登录 Claude CLI。

#### 0. 检查 Codex CLI

执行位置：`PowerShell 终端`。

```powershell
codex --version
```

如果尚未安装 Codex CLI，请先在 `PowerShell 终端` 中安装：

```powershell
npm i -g @openai/codex
```

#### 1. 运行安装前自检

执行位置：`PowerShell 终端`，并且当前目录应为本仓库根目录。

```powershell
cd D:\Desktop\codex-claude-loop
pwsh -NoProfile -File .\scripts\doctor.ps1
```

PowerShell doctor 会检查 Windows 环境、Codex CLI 是否可用、marketplace JSON、插件目录布局、manifest 路径、skill 路径、README 旧路径残留，以及 Codex 是否能通过 `plugin/read` 读取插件。

如果只想在 CI 或仓库校验中检查结构，不检查本机 Codex 环境，可以在 `PowerShell 终端` 中运行：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1 -SkipCodexCli -SkipCodexRead
```

macOS 不需要运行 PowerShell doctor。从仓库克隆进行验证时，执行：

```zsh
python3 ./scripts/test_macos_compatibility.py
python3 ./scripts/test_documentation_contract.py
```

#### 2. 添加插件 Marketplace

执行位置：`PowerShell 终端`。

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

如果已经添加过，Codex 可能提示 marketplace 已存在。这通常不是错误，可以继续安装或更新插件。

#### 3. 安装插件

推荐执行位置：`Codex Desktop 插件列表`。

在 Codex Desktop 中打开插件列表，找到 `Codex Claude Loop` 或 `codex-claude-loop@codex-claude-loop`，然后安装并启用到 user scope。安装后建议重启 Codex Desktop，或者至少新建一个会话。

可选执行位置：`Codex CLI 交互界面`。

如果你的 Codex CLI 版本支持插件斜杠命令，可以先在 `PowerShell 终端` 中运行：

```powershell
codex
```

进入 `Codex CLI 交互界面` 后，再输入下面的斜杠命令：

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

注意：`/plugin install ...` 不是 PowerShell 命令，不能直接在 PowerShell 终端里运行。如果你的 Codex 版本不提供这个斜杠命令，请改用 Codex Desktop 插件列表安装。

#### 4. 重启或刷新 Codex

执行位置：`Codex Desktop`。

安装完成后建议重启 Codex Desktop。即使插件已经安装成功，当前已打开的会话也可能仍使用旧的技能上下文；新会话更适合验证插件是否生效。

#### 5. 验证插件是否生效

执行位置：`PowerShell 终端`。

```powershell
codex debug prompt-input "验证 codex-claude-loop 是否生效" | Select-String "codex-claude-loop:codex-claude-loop"
```

macOS 等价命令：

```zsh
codex debug prompt-input "验证 codex-claude-loop 是否生效" | grep -F "codex-claude-loop:codex-claude-loop"
```

如果输出中出现类似下面的内容，说明插件已经进入 Codex 新会话上下文：

```text
codex-claude-loop:codex-claude-loop
file: r3/codex-claude-loop/<version>/skills/codex-claude-loop/SKILL.md
```

也可以在 `Codex Desktop 聊天框` 或新开的 `Codex CLI 交互界面` 中发送：

```text
使用 codex-claude-loop，让 Codex 先理解需求、制定并批准计划，再通过子代理只把实现工作委派给 Claude Code。
```

如果插件已生效，Codex 应该会识别 `codex-claude-loop` skill，并按以下链路工作：

```text
Codex 主线程 -> Codex 子代理 -> codex-claude-loop 委派运行时 -> Claude CLI
```

## 更新插件

如果你之前已经安装过 `codex-claude-loop`，后续仓库更新后，需要更新本机 marketplace 和已安装插件缓存。

### 推荐更新流程

1. 关闭 Codex Desktop，避免插件缓存文件被占用。
2. 打开新的当前平台终端。
3. 执行 marketplace 更新命令。
4. 重启 Codex Desktop 或新建会话。
5. 验证插件是否进入新会话上下文。

执行位置：当前平台终端。

```powershell
codex plugin marketplace upgrade codex-claude-loop
```

如果输出类似下面内容，说明 marketplace 已经是最新：

```text
Marketplace `codex-claude-loop` is already up to date.
```

如果输出显示已升级，也属于正常情况。升级后建议重启 Codex Desktop。

### 缓存刷新要求

仓库变更不会自动刷新已经运行中的 Codex 会话，也不会自动替换已经安装但未重新加载的插件缓存。执行 marketplace 更新后，必须重启 Codex Desktop 或开启新的 Codex 会话，再依赖新的插件行为。对于 `0.4.1` 及更新版本尤其重要，因为 schema v3 产物只有在新会话加载到更新后的插件运行时时才会生成。

macOS 包装器从 `0.4.2` 开始提供。已有安装必须先执行 marketplace upgrade，再重启 Codex Desktop 或开启新会话，`macos_scripts/*.sh` 才会进入实际加载的插件缓存。

### 验证是否已更新

执行位置：`PowerShell 终端`。

```powershell
(codex debug prompt-input "验证 codex-claude-loop 是否更新" | Select-String -Pattern "codex-claude-loop/[0-9]+\.[0-9]+\.[0-9]+" -AllMatches).Matches.Value
```

macOS 等价命令：

```zsh
codex debug prompt-input "验证 codex-claude-loop 是否更新" | grep -Eo 'codex-claude-loop/[0-9]+\.[0-9]+\.[0-9]+' | head -n 1
```

如果输出类似 `codex-claude-loop/<version>`，说明该版本已经进入 Codex 会话上下文。

对于 schema v3 契约版本，请确认加载到的版本是 `codex-claude-loop/0.4.1` 或更新版本。该版本会把新生成的 workflow gate、reviewer 证据和 final-verifier 验收产物升级到 schema v3，因此升级后需要重启 Codex Desktop 或开启新会话，再依赖新的契约行为。

如需使用 macOS 支持，请确认加载到的版本是 `codex-claude-loop/0.4.2` 或更新版本。

如果命令输出的是整段很长的 prompt，而不是单独的版本号，通常是少了最后的 `.Matches.Value`。请使用上面的完整命令，只打印匹配到的版本字符串。

如果怀疑当前终端调用了另一个 Codex 安装入口，可以检查 `codex` 命令实际来自哪里：

```powershell
where.exe codex
```

这个命令只用于排查路径问题。它会列出当前 `PowerShell 终端` 中可执行的 `codex` 文件路径，可帮助判断是否存在多个 Codex 安装入口导致的版本或缓存不一致。

## 常见问题与排障

### 插件列表里看不到 Codex Claude Loop

先确认你已经在 `PowerShell 终端` 中添加 marketplace：

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

然后重启 Codex Desktop。如果仍看不到，运行：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1
```

### marketplace 路径格式错误

如果安装或更新时看到类似错误：

```text
local plugin source path must start with `./`
local plugin source path must not be empty
local plugin source path must stay within the marketplace root
```

请检查 marketplace 文件：

```text
.agents/plugins/marketplace.json
```

正确写法必须指向 marketplace 内部的插件子目录：

```json
"path": "./plugins/codex-claude-loop"
```

不要在这个仓库中使用 `"path": "./"`。Codex 会区分 marketplace 根目录和插件根目录，因此插件必须位于非空子目录，例如 `plugins/codex-claude-loop/`。

### 更新时报 `拒绝访问。 (os error 5)`

如果执行 `codex plugin marketplace upgrade codex-claude-loop` 时看到类似错误：

```text
failed to back up plugin cache entry: 拒绝访问。 (os error 5)
```

通常是 Codex Desktop 或其他 Codex 进程正在占用插件缓存，或者缓存目录权限异常。

建议按顺序处理：

1. 关闭 Codex Desktop 所有窗口。
2. 关闭正在运行的 Codex CLI 会话。
3. 重新打开 `PowerShell 终端`。
4. 再次执行：

```powershell
codex plugin marketplace upgrade codex-claude-loop
```

如果仍失败，再检查缓存目录权限：

```powershell
Get-Acl "$env:USERPROFILE\.codex\plugins\cache\codex-claude-loop" | Format-List Owner,AccessToString
```

不要通过手动复制 `skills` 目录来兜底安装或更新插件。这样可能绕过 Codex 插件缓存、版本和启用状态管理，后续更难排查。

### `codex debug prompt-input` 输出太多，看不懂

执行位置：`PowerShell 终端`。

建议只搜索插件 skill 名称：

```powershell
codex debug prompt-input "验证 codex-claude-loop" | Select-String "codex-claude-loop:codex-claude-loop"
```

看到 `codex-claude-loop:codex-claude-loop` 通常说明插件 skill 已进入新会话上下文。

如果要检查具体插件版本，建议使用“验证是否已更新”小节中的 `.Matches.Value` 命令，否则 PowerShell 可能会打印整段匹配行，看起来像输出了完整 prompt。

## 使用方式

复制提示词后，把 `<...>` 占位内容替换成你的真实任务。

### 在 Codex App 中使用

执行位置：`Codex Desktop/App 聊天框`。

Codex App 有可视化插件菜单。可以点击聊天框左下角的 `插件`，选择 `Codex Claude Loop`，然后在聊天框里输入任务提示词。

示例：

```text
使用 codex-claude-loop 修复这个 Bug：<描述 Bug>

要求：
- Codex 先分析问题并批准方案。
- Claude Code 只实现已批准的修改。
- Codex 最后复核 diff 和验证结果。
```

如果已经在插件菜单中选择了 `Codex Claude Loop`，也建议在提示词里保留 `使用 codex-claude-loop`，这样更清楚地告诉 Codex 这次任务要走该插件的工作流。

### 在 Codex CLI 中使用

Codex CLI 通常没有 Codex App 那样的可视化插件菜单。CLI 中使用插件的方式是：在提示词里明确写 `使用 codex-claude-loop ...`，让 Codex 新会话自动加载并触发已安装的 skill。

不要在 PowerShell 中执行 `Codex Claude Loop`、`codex-claude-loop` 或 `/plugin install ...` 来“运行插件”。`/plugin install ...` 是安装命令，不是使用插件的命令，而且只能在 Codex CLI 交互界面中输入。

#### CLI 交互式用法

先在 `PowerShell 终端` 进入目标项目目录，然后启动 Codex CLI：

```powershell
cd D:\你的项目目录
codex
```

macOS：

```zsh
cd ~/your-project
codex
```

进入 `Codex CLI 交互界面` 后，输入自然语言任务：

```text
使用 codex-claude-loop 实现这个功能：<描述功能需求>

要求：
- Codex 先明确修改范围和验收标准。
- Claude Code 只编写已批准的代码改动。
- Codex 最后检查 diff、验证结果和风险点。
```

#### CLI 一次性 prompt 用法

执行位置：`PowerShell 终端`。

```powershell
codex -C D:\你的项目目录 "使用 codex-claude-loop 修复这个 Bug：<描述 Bug>"
```

macOS：

```zsh
codex -C ~/your-project "使用 codex-claude-loop 修复这个 Bug：<描述 Bug>"
```

这种方式会用这一条 prompt 启动一次 Codex 任务。任务较复杂时，更推荐使用交互式 CLI 或 Codex App，方便 Codex 先澄清需求、给出计划并等待确认。

#### 验证 CLI 是否加载了插件

执行位置：`PowerShell 终端`。

```powershell
codex debug prompt-input "使用 codex-claude-loop 测试插件触发" | Select-String "codex-claude-loop:codex-claude-loop"
```

macOS：

```zsh
codex debug prompt-input "使用 codex-claude-loop 测试插件触发" | grep -F "codex-claude-loop:codex-claude-loop"
```

如果输出中出现 `codex-claude-loop:codex-claude-loop`，说明 Codex CLI 新会话已经能看到该插件 skill。

### 常用提示词

修复 Bug：

```text
使用 codex-claude-loop 修复这个 Bug：<描述 Bug>
```

实现功能：

```text
使用 codex-claude-loop 实现这个功能：<描述功能需求>
```

限定文件范围：

```text
使用 codex-claude-loop 处理这个任务：<描述任务>。只允许修改这些文件：<文件列表>。
```

返工上一次实现：

```text
使用 codex-claude-loop 返工上一次实现：<描述需要修复的问题>
```

普通用户不需要直接运行内部委派脚本；从 Codex App、Codex CLI 交互界面，或 `codex -C ... "使用 codex-claude-loop ..."` 这类自然语言提示词触发即可。

## 开发

### 插件版本号自动更新

修改插件能力文件前，可以先启用仓库 git hook：

```powershell
pwsh -NoProfile -File .\scripts\install-git-hooks.ps1
```

pre-commit hook 会执行 `scripts/bump-plugin-version.ps1`。当 `plugins/codex-claude-loop/skills/`、`plugins/codex-claude-loop/hooks/` 或 `plugins/codex-claude-loop/.codex-plugin/plugin.json` 下的文件发生变化，并且 manifest 版本号没有被手动修改时，它会自动递增插件 manifest 的 patch 版本并加入暂存区。

如果只想在 CI 或本地检查中验证版本号是否遗漏，不改文件，可以执行：

```powershell
pwsh -NoProfile -File .\scripts\bump-plugin-version.ps1 -CheckOnly
```
