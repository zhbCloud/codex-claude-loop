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

function testPatchPathsAreResolvedAgainstWorkspace() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const allowedPaths = [
      "./.codex/codex_claude_loop/tasks/../task.md",
      path.join(root, ".codex", "codex_claude_loop", "tasks", "absolute.md")
    ];
    const deniedPaths = [
      ".codex/codex_claude_loop/../../src/App.vue",
      ".codex/codex_claude_loop/tasks/../../../src/App.vue",
      ".codex/codex_claude_loop_other/task.md",
      path.join(root, "src", "App.vue"),
      path.join(root, "..", "outside-workspace", ".codex", "codex_claude_loop", "task.md")
    ];
    if (process.platform === "win32") {
      allowedPaths.push(".CODEX\\CODEX_CLAUDE_LOOP\\tasks\\windows.md");
      deniedPaths.push(".codex\\codex_claude_loop\\..\\..\\src\\App.vue");
    } else {
      deniedPaths.push(".CODEX/codex_claude_loop/task.md");
    }
    for (const [paths, expected] of [[allowedPaths, ""], [deniedPaths, "deny"]]) {
      for (const filePath of paths) {
        const output = runHook(
          {
            hook_event_name: "PreToolUse",
            tool_name: "apply_patch",
            cwd: root,
            tool_input: `*** Begin Patch\n*** Add File: ${filePath}\n+task\n*** End Patch\n`
          },
          root
        );
        assert.equal(permission(output), expected, filePath);
      }
    }
  });
}

function testPatchMoveChecksBothSourceAndDestination() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const cases = [
      [".codex/codex_claude_loop/tasks/old.md", ".codex/codex_claude_loop/tasks/new.md", ""],
      [".codex/codex_claude_loop/tasks/old.md", "src/App.vue", "deny"],
      [".codex/codex_claude_loop/tasks/old.md", path.join(root, "src", "App.vue"), "deny"],
      [".codex/codex_claude_loop/tasks/old.md", ".codex/codex_claude_loop/../../src/App.vue", "deny"],
      ["src/App.vue", ".codex/codex_claude_loop/tasks/new.md", "deny"]
    ];
    for (const [source, destination, expected] of cases) {
      const output = runHook(
        {
          hook_event_name: "PreToolUse",
          tool_name: "apply_patch",
          cwd: root,
          tool_input: `*** Begin Patch\n*** Update File: ${source}\n*** Move to: ${destination}\n@@\n-old\n+new\n*** End Patch\n`
        },
        root
      );
      assert.equal(permission(output), expected, `${source} -> ${destination}`);
    }
  });
}

function testPatchDelegateTextDoesNotBypassPathChecks() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const output = runHook(
      {
        hook_event_name: "PreToolUse",
        tool_name: "apply_patch",
        cwd: root,
        tool_input: "*** Begin Patch\n*** Add File: src/delegate.txt\n+CODEX_CLAUDE_LOOP_CHILD_THREAD=1 delegate_to_claude.ps1\n*** End Patch\n"
      },
      root
    );
    assert.equal(permission(output), "deny");
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

function testValidationPrefixCannotHideShellWrites() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const commands = [
      "git status; Set-Content -LiteralPath src/App.vue -Value changed",
      "rg pattern src && rm src/App.vue",
      "npm run build | tee src/build.log",
      "git status\nRemove-Item -LiteralPath src/App.vue",
      "git diff > src/snapshot.txt",
      "npm run build >> src/build.log",
      "git status 2> src/errors.txt",
      "git diff > 'src/quoted snapshot.txt'"
    ];
    for (const command of commands) {
      const output = runHook(
        { hook_event_name: "PreToolUse", tool_name: "shell_command", cwd: root, tool_input: { command } },
        root
      );
      assert.equal(permission(output), "deny", command);
    }
  });
}

function testReadOnlyCommandsAndQuotedOperatorsRemainAllowed() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const commands = [
      "git status; git diff",
      "rg 'rm|Set-Content|a>b' src",
      'rg "a>b" src',
      "node --check scripts/test_loop_mode_guard.mjs",
      "python -B scripts/test_task_contract.py",
      "npm run build",
      "pnpm run build",
      "yarn build",
      "pwsh -NoProfile -File scripts/verify_artifacts.ps1"
    ];
    for (const command of commands) {
      const output = runHook(
        { hook_event_name: "PreToolUse", tool_name: "shell_command", cwd: root, tool_input: { command } },
        root
      );
      assert.deepEqual(output, {}, command);
    }
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

function testDelegateCommandCannotHideAppendedWrites() {
  withTempWorkspace((root) => {
    runHook({ hook_event_name: "UserPromptSubmit", cwd: root, prompt: "codex-claude-loop 执行" }, root);
    const delegate = "$env:CODEX_CLAUDE_LOOP_CHILD_THREAD='1'; pwsh -File .\\delegate_to_claude.ps1 -TaskFile .\\.codex\\codex_claude_loop\\tasks\\a.md -WorkflowId wf -TaskId task -Role implementer -SessionKey task";
    for (const suffix of ["; Set-Content -LiteralPath src/App.vue -Value changed", " > src/delegate.log"]) {
      const output = runHook(
        { hook_event_name: "PreToolUse", tool_name: "shell_command", cwd: root, tool_input: { command: delegate + suffix } },
        root
      );
      assert.equal(permission(output), "deny", suffix);
    }
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
testPatchPathsAreResolvedAgainstWorkspace();
testPatchMoveChecksBothSourceAndDestination();
testPatchDelegateTextDoesNotBypassPathChecks();
testShellWriteIsDeniedButValidationAllowed();
testValidationPrefixCannotHideShellWrites();
testReadOnlyCommandsAndQuotedOperatorsRemainAllowed();
testDelegateCommandIsAllowed();
testDelegateCommandCannotHideAppendedWrites();
testDelegateCommandRequiresSessionKey();
console.log("ok");
