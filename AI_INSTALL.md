# AI 安装说明

本文件是 `codex-claude-loop` 的 AI 安装与更新契约，供 Codex AI 在用户要求安装、启用或更新本插件时读取并执行。

README 面向人类用户，保持简短提示；详细执行规则以本文件为准。

## 用户可使用的短提示

用户可能只发送类似一句话：

```text
请把 https://github.com/zhbCloud/codex-claude-loop 这个 Windows-only Codex 插件安装或更新到当前 Codex 环境，并按仓库 AI_INSTALL.md 执行。
```

收到这类请求后，AI 必须按本文档执行。

## 默认交互策略

1. 默认执行安装或更新，不把安装流程变成问答。
2. 如果需要修改用户级 Codex 配置、下载 marketplace、写入插件缓存或执行提权命令，按当前 Codex 宿主的确认机制请求用户批准。
3. 如果任何关键步骤失败，立即停止并说明失败原因。
4. 不要通过复制 `skills` 目录、复制插件目录、手写缓存目录等方式兜底安装。
5. 不要修改用户项目业务代码。
6. 安装或更新完成后，说明是否需要重启 Codex Desktop 或开启新会话。

## 执行位置约定

- `PowerShell 终端`：运行 `codex --version`、`codex plugin marketplace add ...`、`codex plugin marketplace upgrade ...`、`pwsh -File ...` 等命令。
- `Codex Desktop 聊天框`：用户给 Codex AI 发自然语言请求的位置。
- `Codex CLI 交互界面`：用户在 PowerShell 中运行 `codex` 后进入的交互界面。`/plugin install ...` 如果可用，只能在这里输入，不能在 PowerShell 里直接执行。
- `Codex Desktop 插件列表`：用户手动安装、启用、禁用插件的位置。

## 目标

把 GitHub 仓库：

```text
https://github.com/zhbCloud/codex-claude-loop.git
```

安装或更新为当前 Codex 环境中的用户级插件：

```text
codex-claude-loop@codex-claude-loop
```

该插件只面向 Windows。非 Windows 环境必须停止并说明原因。

## 必须检查的仓库结构

仓库必须是 Codex plugin marketplace，并满足：

```text
.agents/plugins/marketplace.json
plugins/codex-claude-loop/.codex-plugin/plugin.json
plugins/codex-claude-loop/skills/codex-claude-loop/SKILL.md
```

`.agents/plugins/marketplace.json` 中必须包含：

```json
"path": "./plugins/codex-claude-loop"
```

不要使用：

```json
"path": "./"
```

Codex marketplace 要求 local plugin source 指向 marketplace 内部的非空插件子目录。

## 安装或更新流程

### 1. 检查系统

在 `PowerShell 终端` 中确认当前系统是 Windows。

如果不是 Windows，停止并说明：本插件当前只支持 Windows。

### 2. 检查 Codex CLI

在 `PowerShell 终端` 中检查：

```powershell
codex --version
```

如果 `codex` 不存在，提示用户安装 Codex CLI，例如：

```powershell
npm i -g @openai/codex
```

如果 Codex CLI 不可用，不要继续安装。

### 3. 检查当前 Codex 配置状态

在 `PowerShell 终端` 中检查用户级 Codex 配置：

```powershell
$config = Join-Path $env:USERPROFILE ".codex\config.toml"
Test-Path $config
if (Test-Path $config) { Select-String -Path $config -Pattern "marketplaces.codex-claude-loop", 'plugins."codex-claude-loop@codex-claude-loop"' }
```

如果存在：

```toml
[marketplaces.codex-claude-loop]
```

说明 marketplace 已经添加过。

如果存在并启用：

```toml
[plugins."codex-claude-loop@codex-claude-loop"]
enabled = true
```

说明插件可能已经安装或启用。仍可继续执行 marketplace upgrade 来同步最新版本。

Codex 当前 CLI 版本可能没有公开的 marketplace list 或 plugin install 子命令，不要因为缺少这些子命令就误判插件不可安装；应结合 `config.toml`、Codex Desktop 插件列表、Codex app-server 官方接口和 `codex debug prompt-input` 验证。

### 4. 检查旧版或非 marketplace 残留

检查用户是否存在旧式手动 skill 安装残留：

```powershell
$legacySkill = Join-Path $env:USERPROFILE ".codex\skills\codex-claude-loop"
Test-Path $legacySkill
```

如果存在，说明用户可能曾经用复制 skill 目录的方式安装过旧版。不要静默删除；应告知用户该残留可能与 marketplace 插件混淆，并在获得明确确认后再处理。

检查当前项目是否存在旧式本地 `.codex/skills/codex-claude-loop`：

```powershell
Test-Path ".\.codex\skills\codex-claude-loop"
```

如果存在，同样不要静默删除。先说明影响并等待用户确认。

### 5. 检查或运行 doctor

如果当前工作区是本仓库，优先运行：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1
```

如果只是做仓库结构校验，运行：

```powershell
pwsh -NoProfile -File .\scripts\doctor.ps1 -SkipCodexCli -SkipCodexRead
```

doctor 失败时停止并说明原因。

### 6. 添加 marketplace

在 `PowerShell 终端` 中执行：

```powershell
codex plugin marketplace add https://github.com/zhbCloud/codex-claude-loop.git
```

如果 marketplace 已存在，不视为失败，可以继续更新或安装。

### 7. 更新 marketplace

如果用户请求“更新”，或 marketplace 已添加过，执行：

```powershell
codex plugin marketplace upgrade codex-claude-loop
```

如果输出 `already up to date`，说明 marketplace 已是最新，不视为失败。

如果出现：

```text
failed to back up plugin cache entry: 拒绝访问。 (os error 5)
```

优先提示用户关闭 Codex Desktop 和所有 Codex CLI 会话，再重新执行 upgrade。不要删除缓存目录，不要复制 skill 目录兜底。

### 8. 安装插件到 user scope

目标插件：

```text
codex-claude-loop@codex-claude-loop
```

优先使用当前 Codex 环境提供的官方插件安装能力。

如果 Codex Desktop 插件列表可用，指导用户在插件列表中安装并启用 `Codex Claude Loop`。

如果 Codex CLI 交互界面支持插件斜杠命令，可在 `Codex CLI 交互界面` 中输入：

```text
/plugin install codex-claude-loop@codex-claude-loop --scope user
```

注意：这不是 PowerShell 命令。

如果需要通过 Codex app-server 官方接口安装，必须使用 `plugin/install`，不要手动复制插件文件或 skill 目录。

### 9. 定位已安装插件缓存

安装后可检查插件缓存根目录：

```powershell
$cacheRoot = Join-Path $env:USERPROFILE ".codex\plugins\cache\codex-claude-loop"
Get-ChildItem -Force $cacheRoot -Recurse -Depth 4 -ErrorAction SilentlyContinue |
  Select-Object FullName,Mode,Length |
  Select-Object -First 80
```

常见 skill 路径类似：

```text
$env:USERPROFILE\.codex\plugins\cache\codex-claude-loop\codex-claude-loop\<version>\skills\codex-claude-loop\SKILL.md
```

不要把 `<version>` 包根目录误当成 skill 根目录；真正的 skill 根目录是 `skills/codex-claude-loop`。

### 10. 验证插件进入上下文

安装或更新后，建议重启 Codex Desktop 或开启新会话。

在 `PowerShell 终端` 中验证：

```powershell
codex debug prompt-input "验证 codex-claude-loop 是否生效" | Select-String "codex-claude-loop:codex-claude-loop"
```

看到 `codex-claude-loop:codex-claude-loop`，说明插件 skill 已进入新会话上下文。

如果用户要求验证“是否更新到最新”，还应说明：如果本次只修改 README、CI 或 doctor 脚本，插件 skill 版本可能仍显示 `0.1.0`；只有修改插件 manifest 中的 `version` 后，缓存路径中的版本才会变化。

### 11. 不要绕过插件工作流

如果用户明确要求使用 `codex-claude-loop`，不要用 Codex 默认普通子代理、直接运行 Claude CLI、或主线程直接调用 `delegate_to_claude.ps1` 作为替代。

普通使用入口是：

- Codex Desktop 插件菜单选择 `Codex Claude Loop` 后发送任务。
- Codex CLI 交互界面中发送 `使用 codex-claude-loop ...`。
- PowerShell 中使用一次性 prompt：`codex -C <project> "使用 codex-claude-loop ..."`。

## 失败处理

- 系统不是 Windows：停止。
- Codex CLI 不存在或不可用：停止。
- marketplace 文件或插件 manifest 不存在：停止。
- marketplace path 是 `"./"`、 `"."` 或其他非法路径：停止并说明必须是 `"./plugins/codex-claude-loop"`。
- marketplace 添加失败：停止。
- marketplace 更新失败：停止。
- 插件安装失败：停止。
- 验证失败：说明插件可能未进入当前新会话上下文，并建议重启 Codex 后重试。

禁止：

- 复制 `skills` 目录到用户目录作为兜底。
- 复制仓库插件目录到 Codex 缓存目录作为兜底。
- 修改用户项目业务代码。
- 删除用户缓存目录，除非用户明确要求并确认影响范围。

## 完成后回复用户

最终回复必须说明：

1. 是否检测到 Codex CLI。
2. 是否确认系统是 Windows。
3. marketplace 是否已添加或已存在。
4. 是否在 `config.toml` 中发现旧配置或已启用插件配置。
5. 是否发现旧式 skill 安装残留；如果发现，是否已征得用户确认后处理。
6. 插件是否已安装或更新到 user scope。
7. 已安装插件缓存路径或 skill 路径是什么。
8. 是否验证到 `codex-claude-loop:codex-claude-loop`。
9. 是否需要重启 Codex Desktop 或开启新会话。
10. 如果有步骤没执行，说明阻塞原因。
11. 如果失败，说明失败在哪一步以及下一步建议。

不要只回复“好了”或“已完成”。必须把实际执行过的动作、未执行的动作、验证结果和用户还需要做的事情说清楚。
