import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const hookPath = path.join(repoRoot, "plugins", "codex-claude-loop", "hooks", "subagent-gate-hook.mjs");

function runHook(input, cwd) {
  const result = spawnSync(process.execPath, [hookPath], {
    cwd,
    input: JSON.stringify(input),
    encoding: "utf8",
    env: {
      ...process.env,
      CODEX_PLUGIN_ROOT: path.join(repoRoot, "plugins", "codex-claude-loop")
    }
  });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim() ? JSON.parse(result.stdout) : {};
}

function withTempWorkspace(fn) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "loop-guard-"));
  try {
    return fn(root);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function permission(output) {
  return output?.hookSpecificOutput?.permissionDecision || "";
}

function testPromptActivatesLoopMode() {
  withTempWorkspace((root) => {
    const output = runHook(
      {
        hook_event_name: "UserPromptSubmit",
        cwd: root,
        prompt: "使用 codex-claude-loop 多代理执行这个迁移"
      },
      root
    );
    assert.match(output.hookSpecificOutput.additionalContext, /codex-claude-loop/);
    const statePath = path.join(root, ".codex", "codex_claude_loop", "loop_mode.json");
    const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
    assert.equal(state.active, true);
  });
}

function testApplyPatchToSourceIsDenied() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const output = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "apply_patch",
        cwd: root,
        tool_input: "*** Begin Patch\n*** Update File: src/App.vue\n@@\n-old\n+new\n*** End Patch\n"
      },
      root
    );
    assert.equal(permission(output), "deny");
    assert.match(output.hookSpecificOutput.permissionDecisionReason, /cannot directly edit production files/);
  });
}

function testTaskFilePatchIsAllowed() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const output = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "apply_patch",
        cwd: root,
        tool_input: "*** Begin Patch\n*** Add File: .codex/codex_claude_loop/tasks/task.md\n+do it\n*** End Patch\n"
      },
      root
    );
    assert.deepEqual(output, {});
  });
}

function testShellWriteIsDeniedButValidationAllowed() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const denied = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "shell_command",
        cwd: root,
        tool_input: { command: "Set-Content -LiteralPath src\\App.vue -Value test" }
      },
      root
    );
    assert.equal(permission(denied), "deny");

    const allowed = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "shell_command",
        cwd: root,
        tool_input: { command: "npm run build" }
      },
      root
    );
    assert.deepEqual(allowed, {});
  });
}

function testDelegateCommandIsAllowed() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const output = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "shell_command",
        cwd: root,
        tool_input: {
          command: "$env:CODEX_CLAUDE_LOOP_CHILD_THREAD='1'; pwsh -File .\\delegate_to_claude.ps1 -TaskFile .\\.codex\\codex_claude_loop\\tasks\\a.md -WorkflowId wf -TaskId task -Role implementer -SessionKey task"
        }
      },
      root
    );
    assert.deepEqual(output, {});
  });
}

function testDelegateCommandRequiresSessionKey() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const output = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "shell_command",
        cwd: root,
        tool_input: {
          command: "$env:CODEX_CLAUDE_LOOP_CHILD_THREAD='1'; pwsh -File .\\delegate_to_claude.ps1 -TaskFile .\\.codex\\codex_claude_loop\\tasks\\a.md -WorkflowId wf -TaskId task -Role implementer"
        }
      },
      root
    );
    assert.equal(permission(output), "deny");
    assert.match(output.hookSpecificOutput.permissionDecisionReason, /SessionKey/);
  });
}

testPromptActivatesLoopMode();
testApplyPatchToSourceIsDenied();
testTaskFilePatchIsAllowed();
testShellWriteIsDeniedButValidationAllowed();
testDelegateCommandIsAllowed();
testDelegateCommandRequiresSessionKey();
console.log("ok");
