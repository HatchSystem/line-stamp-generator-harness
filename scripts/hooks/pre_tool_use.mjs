import { evaluateToolUse } from "./policy.mjs";


async function readStdin() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  return input;
}


function decision(surface, reason) {
  if (surface === "cursor") {
    return reason
      ? { permission: "deny", user_message: reason, agent_message: reason }
      : { permission: "allow" };
  }
  if (surface === "claude" || surface === "codex") {
    if (!reason) return null;
    return {
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: `[line-stamp-policy] ${reason}`,
      },
    };
  }
  throw new Error(`unsupported hook surface: ${surface}`);
}


async function main() {
  const surface = process.argv[2];
  let payload;
  try {
    payload = JSON.parse(await readStdin());
  } catch {
    const result = decision(surface, "安全フックの入力を解析できなかったため操作を停止しました。");
    if (result) process.stdout.write(`${JSON.stringify(result)}\n`);
    return;
  }

  const result = decision(surface, evaluateToolUse(payload));
  if (result) process.stdout.write(`${JSON.stringify(result)}\n`);
}


main().catch((error) => {
  process.stderr.write(`[line-stamp-policy] ${error.message}\n`);
  process.exitCode = 2;
});
