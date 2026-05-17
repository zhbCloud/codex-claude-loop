#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REQUIRED_MODEL = "gpt-5.3-codex";
const REQUIRED_EFFORT = "medium";
const LOOP_MODE_TTL_MS = 6 * 60 * 60 * 1000;
const LOOP_MODE_RELATIVE_PATH = path.join(".codex", "codex_claude_loop", "loop_mode.json");
const ALLOWED_ROLES = new Set(["planner", "implementer", "researcher", "reviewer", "final-verifier"]);
const TRIGGER_PATTERNS = [
  /codex[-_\s]?claude[-_\s]?loop/i,
  /Claude\s+Code/i,
  /child[- ]?agent/i,
  /sub[- ]?agent/i,
  /child[- ]?thread/i,
  /sub[- ]?thread/i,
  /delegat(?:e|ion|ing)/i,
  /worker[- ]?execution/i,
  /子代理|子线程|多代理|委派|派工|执行层/
];
const SPAWN_TOOL_NAMES = new Set(["spawn_agent", "task", "subagent", "agent", "worker"]);
const SHELL_TOOL_NAMES = new Set(["bash", "shell_command", "functions.shell_command"]);
const PATCH_TOOL_NAMES = new Set(["apply_patch", "functions.apply_patch"]);
const PARALLEL_TOOL_NAMES = new Set(["multi_tool_use.parallel", "parallel"]);
const LOOP_MODE_ALLOWED_PREFIXES = [
  ".codex/codex_claude_loop/",
  ".codex\\codex_claude_loop\\"
];

const FALLBACK_CONTEXT = [
  "codex-claude-loop subagent gate:",
  "- Any child-agent/subagent delegation request must use codex-claude-loop workflow.",
  "- Required chain: Codex main thread -> spawn_agent child thread -> delegate_to_claude.ps1 -> Claude CLI.",
  "- Do not use default subagent flow, direct claude execution, or direct main-thread delegate execution.",
  "- Child spawn metadata should use model gpt-5.3-codex and reasoning_effort medium.",
  "- Child must set CODEX_CLAUDE_LOOP_CHILD_THREAD=1 and invoke delegate_to_claude.ps1 with TaskFile/WorkflowId/TaskId/Role."
].join("\n");

function pluginRoot() {
  if (process.env.CODEX_PLUGIN_ROOT) return process.env.CODEX_PLUGIN_ROOT;
  if (process.env.CLAUDE_PLUGIN_ROOT) return process.env.CLAUDE_PLUGIN_ROOT;
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function readOptionalText(filePath) {
  try {
    return fs.readFileSync(filePath, "utf8");
  } catch {
    return "";
  }
}

function bootstrapContext() {
  const root = pluginRoot();
  const skillText = readOptionalText(path.join(root, "skills", "codex-claude-loop", "SKILL.md"));
  const contractText = readOptionalText(path.join(root, "skills", "codex-claude-loop", "CODEX_CLAUDE_LOOP.md"));
  if (!skillText.trim() || !contractText.trim()) return FALLBACK_CONTEXT;
  return [
    "You have codex-claude-loop routing.",
    "",
    "## codex-claude-loop SKILL.md",
    skillText.trim(),
    "",
    "## codex-claude-loop CODEX_CLAUDE_LOOP.md",
    contractText.trim()
  ].join("\n");
}

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
  });
}

function parseInput(text) {
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function writeJson(value) {
  process.stdout.write(JSON.stringify(value));
}

function workspaceRoot(input, toolInput = {}) {
  const candidates = [
    prop(input, "cwd", "cwd"),
    prop(input, "workspace_root", "workspaceRoot"),
    prop(input, "workspace", "workspace"),
    prop(toolInput, "cwd", "cwd"),
    process.env.CODEX_WORKSPACE_ROOT,
    process.env.PWD,
    process.cwd()
  ].filter(Boolean);
  return path.resolve(String(candidates[0]));
}

function loopModePath(root) {
  return path.join(root, LOOP_MODE_RELATIVE_PATH);
}

function nowMs() {
  return Date.now();
}

function safeReadJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function writeLoopMode(root, active, reason, promptText = "") {
  const filePath = loopModePath(root);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const timestamp = new Date().toISOString();
  fs.writeFileSync(
    filePath,
    JSON.stringify(
      {
        active,
        reason,
        updatedAt: timestamp,
        expiresAt: new Date(nowMs() + LOOP_MODE_TTL_MS).toISOString(),
        promptPreview: promptText.slice(0, 500)
      },
      null,
      2
    ),
    "utf8"
  );
}

function loopModeState(root) {
  const state = safeReadJson(loopModePath(root));
  if (!state || !state.active) return { active: false };
  const expiresAt = Date.parse(String(state.expiresAt || ""));
  if (Number.isFinite(expiresAt) && expiresAt < nowMs()) return { active: false, expired: true };
  return { ...state, active: true };
}

function containsLoopDisable(text) {
  return /(?:disable|stop|exit|leave)\s+codex[-_\s]?claude[-_\s]?loop/i.test(text)
    || /退出|关闭|停止/.test(text) && /codex[-_\s]?claude[-_\s]?loop|loop\s*模式|循环模式/i.test(text);
}

function getEventName(input) {
  return input.hook_event_name || input.hookEventName || input.eventName || "";
}

function getToolName(input) {
  return input.tool_name || input.toolName || "";
}

function getToolInput(input) {
  return input.tool_input || input.toolInput || {};
}

function getPrompt(input) {
  return input.prompt || input.user_prompt || input.userPrompt || "";
}

function stringify(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function containsTrigger(text) {
  return TRIGGER_PATTERNS.some((pattern) => pattern.test(text));
}

function additionalContext(eventName) {
  return {
    hookSpecificOutput: {
      hookEventName: eventName,
      additionalContext: bootstrapContext()
    }
  };
}

function deny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason
    }
  };
}

function isAllowedLoopModePath(filePath) {
  const normalized = String(filePath).replaceAll("\\", "/").replace(/^["']|["']$/g, "").replace(/^\.\//, "");
  return LOOP_MODE_ALLOWED_PREFIXES.some((prefix) => normalized.toLowerCase().startsWith(prefix.replaceAll("\\", "/").toLowerCase()));
}

function prop(input, snakeName, camelName) {
  if (input && Object.prototype.hasOwnProperty.call(input, snakeName)) return input[snakeName];
  if (input && Object.prototype.hasOwnProperty.call(input, camelName)) return input[camelName];
  return undefined;
}

function roleValue(serialized) {
  const match = serialized.match(/(?:^|[\s"'])(?:-Role|--role)\s+["']?([A-Za-z-]+)/i);
  return match ? match[1].toLowerCase() : "";
}

function has(pattern, serialized) {
  return pattern.test(serialized);
}

function hasDirectClaudeCommand(serialized) {
  return /(?:^|[\s;&|"'`])(?:\.\/|\.\\|[\w:/\\.-]*[/\\])?claude(?:\.cmd|\.exe)?(?=$|[\s;&|"'`])/i.test(serialized);
}

function isDelegateCommand(serialized) {
  return has(/delegate_to_claude(?:\.(?:ps1|sh|cmd|bat))?/i, serialized)
    && has(/CODEX_CLAUDE_LOOP_CHILD_THREAD\s*(?:=|:)\s*["']?1["']?/i, serialized);
}

function isKnownReadOnlyOrValidationCommand(serialized) {
  const text = String(serialized).trim();
  return /^(?:rg|git\s+(?:status|diff|show|log|ls-files)|node\s+--check|python(?:\s+-B)?\s+scripts[\\/].*test|npm\s+run\s+build|pnpm\s+run\s+build|yarn\s+build|pwsh\s+-NoProfile\s+-File\s+.*verify_)/i.test(text);
}

function shellLooksLikeWrite(serialized) {
  const text = String(serialized);
  return /(?:^|[\s;&|"'`])(?:Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Move-Item|Copy-Item|Rename-Item|rm|del|mv|cp|tee|npm\s+install|pnpm\s+install|yarn\s+install)\b/i.test(text)
    || /(?:^|[\s;&|])(?:cat|echo|printf)\b[\s\S]*(?:^|[^=])>{1,2}(?![>&])/m.test(text)
    || /(?:^|[\s;&|"'`])sed\s+-i\b/i.test(text);
}

function extractPatchPaths(payload) {
  const serialized = stringify(payload);
  const paths = [];
  for (const match of serialized.matchAll(/\*\*\* (?:Add|Update|Delete) File:\s*([^\r\n]+)/g)) {
    paths.push(match[1].trim());
  }
  return paths;
}

function extractParallelCalls(toolInput) {
  const calls = prop(toolInput, "tool_uses", "toolUses");
  return Array.isArray(calls) ? calls : [];
}

function loopModeWriteProblem(input, toolName, toolInput) {
  const root = workspaceRoot(input, toolInput);
  if (!loopModeState(root).active) return "";
  const serialized = stringify(toolInput);

  if (SPAWN_TOOL_NAMES.has(toolName)) return "";
  if (isDelegateCommand(serialized)) return "";

  if (PATCH_TOOL_NAMES.has(toolName)) {
    const paths = extractPatchPaths(toolInput);
    const blocked = paths.filter((item) => !isAllowedLoopModePath(item));
    if (blocked.length > 0) {
      return `loop mode is active: main thread cannot directly edit production files (${blocked.join(", ")}). Delegate implementation or rework to Claude.`;
    }
    return "";
  }

  if (SHELL_TOOL_NAMES.has(toolName)) {
    if (isKnownReadOnlyOrValidationCommand(String(prop(toolInput, "command", "command") || serialized))) return "";
    if (shellLooksLikeWrite(serialized)) {
      return "loop mode is active: main thread shell write commands are blocked. Write task files under .codex/codex_claude_loop or delegate implementation to Claude.";
    }
    return "";
  }

  if (PARALLEL_TOOL_NAMES.has(toolName)) {
    const blocked = [];
    for (const call of extractParallelCalls(toolInput)) {
      const childName = String(prop(call, "recipient_name", "recipientName") || prop(call, "tool_name", "toolName") || "").toLowerCase();
      const childInput = prop(call, "parameters", "parameters") || getToolInput(call);
      const problem = loopModeWriteProblem(input, childName, childInput);
      if (problem) blocked.push(problem);
    }
    return blocked[0] || "";
  }

  if (/write|edit|multi.?edit/i.test(toolName)) {
    return "loop mode is active: main thread edit tools are blocked. Delegate implementation or rework to Claude.";
  }
  return "";
}

function validateWorkflowPayload(payload) {
  const serialized = stringify(payload);
  const problems = [];

  if (prop(payload, "model", "model") !== REQUIRED_MODEL) problems.push(`model must be ${REQUIRED_MODEL}`);
  if (prop(payload, "reasoning_effort", "reasoningEffort") !== REQUIRED_EFFORT) problems.push(`reasoning_effort must be ${REQUIRED_EFFORT}`);
  if (prop(payload, "fork_context", "forkContext") !== false) problems.push("fork_context must be false");

  if (hasDirectClaudeCommand(serialized)) problems.push("direct Claude CLI execution is forbidden");
  if (!has(/CODEX_CLAUDE_LOOP_CHILD_THREAD\s*(?:=|:)\s*["']?1["']?/i, serialized)) problems.push("CODEX_CLAUDE_LOOP_CHILD_THREAD=1 is required");
  if (!has(/delegate_to_claude(?:\.(?:ps1|sh|cmd|bat))?/i, serialized)) problems.push("delegate_to_claude entrypoint is required");
  if (!has(/(?:^|[\s"'])(?:-TaskFile|--task-file)\b/i, serialized)) problems.push("-TaskFile is required");
  if (!has(/(?:^|[\s"'])(?:-WorkflowId|--workflow-id)\b/i, serialized) && !prop(payload, "workflow_id", "workflowId")) problems.push("-WorkflowId is required");
  if (!has(/(?:^|[\s"'])(?:-TaskId|--task-id)\b/i, serialized) && !prop(payload, "task_id", "taskId")) problems.push("-TaskId is required");

  const role = String(prop(payload, "role", "role") || roleValue(serialized) || "").toLowerCase();
  if (!role) problems.push("-Role is required");
  else if (!ALLOWED_ROLES.has(role)) problems.push(`-Role must be one of ${Array.from(ALLOWED_ROLES).join(", ")}`);

  const hasAllowParallel = has(/(?:^|[\s"'])-(?:AllowParallel)\b|(?:^|[\s"'])--allow-parallel\b/i, serialized);
  const hasScope = has(/(?:^|[\s"'])(?:-Scope|--scope)\b/i, serialized);
  if (hasAllowParallel && !hasScope) problems.push("-Scope is required when -AllowParallel is used");

  return problems;
}

function handlePreToolUse(input) {
  const toolName = String(getToolName(input) || "").toLowerCase();
  const toolInput = getToolInput(input);
  const serialized = stringify(toolInput);
  const loopProblem = loopModeWriteProblem(input, toolName, toolInput);
  if (loopProblem) {
    writeJson(deny(`codex-claude-loop guard blocked ${toolName}: ${loopProblem}`));
    return;
  }

  if (SHELL_TOOL_NAMES.has(toolName)) {
    const problems = [];
    if (hasDirectClaudeCommand(serialized)) problems.push("direct Claude CLI execution is forbidden");
    if (has(/delegate_to_claude(?:\.(?:ps1|sh|cmd|bat))?/i, serialized)) {
      if (!has(/CODEX_CLAUDE_LOOP_CHILD_THREAD\s*(?:=|:)\s*["']?1["']?/i, serialized)) problems.push("CODEX_CLAUDE_LOOP_CHILD_THREAD=1 is required");
      if (!has(/(?:^|[\s"'])(?:-TaskFile|--task-file)\b/i, serialized)) problems.push("-TaskFile is required");
      if (!has(/(?:^|[\s"'])(?:-WorkflowId|--workflow-id)\b/i, serialized)) problems.push("-WorkflowId is required");
      if (!has(/(?:^|[\s"'])(?:-TaskId|--task-id)\b/i, serialized)) problems.push("-TaskId is required");
      const role = roleValue(serialized);
      if (!role) problems.push("-Role is required");
      else if (!ALLOWED_ROLES.has(role)) problems.push(`-Role must be one of ${Array.from(ALLOWED_ROLES).join(", ")}`);
      const hasAllowParallel = has(/(?:^|[\s"'])-(?:AllowParallel)\b|(?:^|[\s"'])--allow-parallel\b/i, serialized);
      const hasScope = has(/(?:^|[\s"'])(?:-Scope|--scope)\b/i, serialized);
      if (hasAllowParallel && !hasScope) problems.push("-Scope is required when -AllowParallel is used");
    }
    if (problems.length > 0) writeJson(deny(`codex-claude-loop gate blocked Bash: ${problems.join("; ")}.`));
    return;
  }

  if (!SPAWN_TOOL_NAMES.has(toolName)) return;
  const problems = validateWorkflowPayload(toolInput);
  if (problems.length > 0) writeJson(deny(`codex-claude-loop gate blocked ${toolName}: ${problems.join("; ")}.`));
}

const input = parseInput(await readStdin());
const eventName = getEventName(input);
if (eventName === "SessionStart") {
  writeJson(additionalContext("SessionStart"));
} else if (eventName === "UserPromptSubmit") {
  const prompt = getPrompt(input);
  const root = workspaceRoot(input);
  if (containsLoopDisable(prompt)) {
    writeLoopMode(root, false, "disabled-by-user", prompt);
  } else if (containsTrigger(prompt)) {
    writeLoopMode(root, true, "triggered-by-user-prompt", prompt);
    writeJson(additionalContext("UserPromptSubmit"));
  }
} else if (eventName === "PreToolUse") {
  handlePreToolUse(input);
}
