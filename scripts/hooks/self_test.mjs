import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { evaluateToolUse } from "./policy.mjs";

const hookPath = fileURLToPath(new URL("./pre_tool_use.mjs", import.meta.url));
const contextHookPath = fileURLToPath(new URL("./project_context.mjs", import.meta.url));

function runHook(surface, payload) {
  return spawnSync(process.execPath, [hookPath, surface], {
    input: typeof payload === "string" ? payload : JSON.stringify(payload),
    encoding: "utf8",
  });
}

const shellBlock = evaluateToolUse({
  tool_name: "Bash",
  tool_input: { command: "rm -rf projects/demo" },
});
assert.match(shellBlock ?? "", /rm -rf/);

const longRmBlock = evaluateToolUse({
  tool_name: "Shell",
  tool_input: { command: "rm --recursive --force tmp/generated" },
});
assert.match(longRmBlock ?? "", /rm -rf/);

const forcePushBlock = evaluateToolUse({
  tool_name: "exec_command",
  tool_input: { command: "git push --force origin main" },
});
assert.match(forcePushBlock ?? "", /force push/);

const powershellDeleteBlock = evaluateToolUse({
  tool_name: "exec_command",
  tool_input: { command: "Remove-Item -Recurse -Force projects/demo" },
});
assert.match(powershellDeleteBlock ?? "", /再帰削除/);

for (const command of [
  "rmdir /s /q projects\\demo",
  "find projects/demo -delete",
]) {
  const result = evaluateToolUse({
    tool_name: "exec_command",
    tool_input: { command },
  });
  assert.match(result ?? "", /禁止|削除/);
}

const fileDeleteBlock = evaluateToolUse({
  tool_name: "Delete",
  tool_input: { path: "projects/demo/SESSION.md" },
});
assert.match(fileDeleteBlock ?? "", /projects/);

const reviewBlock = evaluateToolUse({
  tool_name: "mcp__browser__click",
  tool_input: { url: "https://creator.line.me/", element: "審査をリクエスト" },
});
assert.match(reviewBlock ?? "", /不可逆操作/);

const consentBlock = evaluateToolUse({
  tool_name: "mcp__browser__click",
  tool_input: { url: "https://creator.line.me/", element: "同意します" },
});
assert.match(consentBlock ?? "", /法的同意/);

for (const tool_name of [
  "mcp__line_creators__release",
  "mcp__line_creators__delete_sticker",
]) {
  const result = evaluateToolUse({ tool_name, tool_input: { item_id: "123" } });
  assert.match(result ?? "", /不可逆操作/);
}

const credentialBlock = evaluateToolUse({
  tool_name: "browser_type",
  tool_input: { field: "password", text: "dummy" },
});
assert.match(credentialBlock ?? "", /ログイン情報/);

const envReadBlock = evaluateToolUse({
  tool_name: "Read",
  tool_input: { path: ".env" },
});
assert.match(envReadBlock ?? "", /個人用設定/);

const localSettingsBlock = evaluateToolUse({
  tool_name: "Read",
  tool_input: { path: ".adapter/settings.local.json" },
});
assert.match(localSettingsBlock ?? "", /個人用設定/);

const envShellBlock = evaluateToolUse({
  tool_name: "exec_command",
  tool_input: { command: "Get-Content -Raw .env" },
});
assert.match(envShellBlock ?? "", /読み書きしません/);

const envShellWriteBlock = evaluateToolUse({
  tool_name: "exec_command",
  tool_input: { command: "Set-Content -LiteralPath .env -Value secret" },
});
assert.match(envShellWriteBlock ?? "", /読み書きしません/);

const envPatchBlock = evaluateToolUse({
  tool_name: "apply_patch",
  tool_input: { patch: "*** Begin Patch\n*** Update File: .env\n@@\n-old\n+new\n*** End Patch" },
});
assert.match(envPatchBlock ?? "", /読み書きしません/);

assert.equal(
  evaluateToolUse({ tool_name: "Read", tool_input: { path: "README.md" } }),
  null,
);
assert.equal(
  evaluateToolUse({ tool_name: "Read", tool_input: { path: ".env.example" } }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "apply_patch",
    tool_input: { command: "Document why rm -rf projects is prohibited." },
  }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "web_search",
    tool_input: { query: "LINE sticker delete guidelines" },
  }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "web_search",
    tool_input: { query: "password manager best practices" },
  }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "browser_open",
    tool_input: { url: "https://creator.line.me/docs/release-notes" },
  }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "Read",
    tool_input: { path: "docs/password-policy.md" },
  }),
  null,
);
assert.equal(
  evaluateToolUse({
    tool_name: "Bash",
    tool_input: { command: "python scripts/line_stamp.py project --root . list" },
  }),
  null,
);

const destructivePayload = {
  tool_name: "Bash",
  tool_input: { command: "rm -rf projects/demo" },
};

for (const surface of ["claude", "codex"]) {
  const result = runHook(surface, destructivePayload);
  assert.equal(result.status, 0);
  const output = JSON.parse(result.stdout);
  assert.equal(output.hookSpecificOutput.hookEventName, "PreToolUse");
  assert.equal(output.hookSpecificOutput.permissionDecision, "deny");
}

const cursorDeny = runHook("cursor", destructivePayload);
assert.equal(cursorDeny.status, 0);
assert.equal(JSON.parse(cursorDeny.stdout).permission, "deny");

const safePayload = {
  tool_name: "Bash",
  tool_input: { command: "python scripts/line_stamp.py project --root . list" },
};
assert.equal(runHook("claude", safePayload).stdout, "");
assert.equal(JSON.parse(runHook("cursor", safePayload).stdout).permission, "allow");

for (const surface of ["claude", "codex", "cursor"]) {
  const malformed = runHook(surface, "{");
  assert.equal(malformed.status, 0);
  const output = JSON.parse(malformed.stdout);
  const permission = output.permission ?? output.hookSpecificOutput?.permissionDecision;
  assert.equal(permission, "deny");
}

const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "line-stamp-hook-"));
try {
  const projectRoot = path.join(fixtureRoot, "projects", "demo");
  fs.mkdirSync(projectRoot, { recursive: true });
  fs.writeFileSync(path.join(fixtureRoot, "projects", "ACTIVE"), "demo\n", "utf8");
  fs.writeFileSync(
    path.join(projectRoot, "SESSION.md"),
    "- gate: P4\n- count: 16\n- submission: draft\n",
    "utf8",
  );

  const context = spawnSync(
    process.execPath,
    [contextHookPath, "cursor", "session"],
    { input: JSON.stringify({ cwd: fixtureRoot }), encoding: "utf8" },
  );
  assert.equal(context.status, 0);
  assert.match(JSON.parse(context.stdout).additional_context, /ACTIVE=demo/);
  assert.match(JSON.parse(context.stdout).additional_context, /gate=P4/);

  const reminder = spawnSync(
    process.execPath,
    [contextHookPath, "claude", "prompt"],
    { input: JSON.stringify({ cwd: fixtureRoot }), encoding: "utf8" },
  );
  assert.equal(reminder.status, 0);
  assert.match(reminder.stdout, /project=demo gate=P4/);

  fs.writeFileSync(path.join(fixtureRoot, "projects", "ACTIVE"), "../../sensitive\n", "utf8");
  const invalidActive = spawnSync(
    process.execPath,
    [contextHookPath, "claude", "prompt"],
    { input: JSON.stringify({ cwd: fixtureRoot }), encoding: "utf8" },
  );
  assert.equal(invalidActive.status, 0);
  assert.match(invalidActive.stdout, /slug が不正/);
  assert.doesNotMatch(invalidActive.stdout, /sensitive/);
} finally {
  const expectedPrefix = path.join(os.tmpdir(), "line-stamp-hook-");
  assert.ok(fixtureRoot.startsWith(expectedPrefix));
  fs.rmSync(fixtureRoot, { recursive: true, force: true });
}

console.log("PASS agent-hook-policy");
