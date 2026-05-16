#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REQUIRED_MODEL = "gpt-5.3-codex";
const REQUIRED_EFFORT = "medium";
const ALLOWED_ROLES = new Set(["planner", "implementer", "researcher", "reviewer", "final-verifier"]);
const TRIGGER_PATTERNS = [
  /child[- ]?agent/i,
  /sub[- ]?agent/i,
  /child[- ]?thread/i,
  /sub[- ]?thread/i,
  /delegat(?:e|ion|ing)/i,
  /worker[- ]?execution/i,
  /子代理|子线程|多代理|委派|派工|执行层/
];
const SPAWN_TOOL_NAMES = new Set(["spawn_agent", "task", "subagent", "agent", "worker"]);

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

  if (toolName === "bash") {
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
  if (containsTrigger(getPrompt(input))) writeJson(additionalContext("UserPromptSubmit"));
} else if (eventName === "PreToolUse") {
  handlePreToolUse(input);
}
