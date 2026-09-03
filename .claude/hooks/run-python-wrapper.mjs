#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";


const WRAPPERS = new Map([
  ["block-dangerous", "block-dangerous.py"],
  ["guard-submit", "guard-submit.py"],
]);


function forward(result) {
  if (result.stdout?.length) process.stdout.write(result.stdout);
  if (result.stderr?.length) process.stderr.write(result.stderr);
  process.exitCode = Number.isInteger(result.status) ? result.status : 1;
}


const mode = process.argv[2];
if (!WRAPPERS.has(mode)) {
  process.stderr.write("unknown Claude compatibility wrapper\n");
  process.exitCode = 2;
} else {
  const adapterDirectory = path.dirname(fileURLToPath(import.meta.url));
  const repositoryRoot = path.resolve(
    process.env.CLAUDE_PROJECT_DIR || path.join(adapterDirectory, "..", ".."),
  );
  const wrapper = path.join(adapterDirectory, WRAPPERS.get(mode));
  const input = fs.readFileSync(0);
  const candidates = [
    ["python3", []],
    ["python", []],
    ["py", ["-3"]],
  ];
  let completed = false;
  for (const [command, prefix] of candidates) {
    const result = spawnSync(command, [...prefix, wrapper], {
      input,
      timeout: 10_000,
      windowsHide: true,
    });
    if (result.error?.code === "ENOENT") continue;
    if (result.error) break;
    forward(result);
    completed = true;
    break;
  }
  if (!completed) {
    const sharedHook = path.join(repositoryRoot, "scripts", "hooks", "pre_tool_use.mjs");
    forward(spawnSync(process.execPath, [sharedHook, "claude"], {
      input,
      timeout: 10_000,
      windowsHide: true,
    }));
  }
}
