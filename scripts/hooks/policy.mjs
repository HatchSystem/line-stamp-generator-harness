const COMMAND_DENY_RULES = [
  {
    pattern: /\brm\b(?=[^\r\n]*(?:--recursive\b|-[a-z]*r[a-z]*\b))(?=[^\r\n]*(?:--force\b|-[a-z]*f[a-z]*\b))/i,
    reason: "rm -rf は禁止です。対象を確認してリポジトリ内の tmp/ へ移動してください。",
  },
  {
    pattern: /\brm\b(?=[^\r\n]*(?:--recursive\b|-[a-z]*r[a-z]*\b))(?=[^\r\n]*\b(?:projects|submit)\b)/i,
    reason: "projects/ または submit/ の再帰削除は禁止です。",
  },
  {
    pattern: /\b(?:remove-item|ri)\b(?=[^\r\n]*(?:-recurse|-r\b))(?=[^\r\n]*\b(?:projects|submit)\b)/i,
    reason: "projects/ または submit/ の再帰削除は禁止です。",
  },
  {
    pattern: /\b(?:rmdir|rd)\b(?=[^\r\n]*(?:\/s\b|-recurse\b|-r\b))(?=[^\r\n]*\b(?:projects|submit)\b)/i,
    reason: "projects/ または submit/ の再帰削除は禁止です。",
  },
  {
    pattern: /\bdel\b(?=[^\r\n]*\/s\b)(?=[^\r\n]*\b(?:projects|submit)\b)/i,
    reason: "projects/ または submit/ の再帰削除は禁止です。",
  },
  {
    pattern: /\bfind\b[^\r\n]*\b(?:projects|submit)\b[^\r\n]*-delete\b/i,
    reason: "projects/ または submit/ の find -delete は禁止です。",
  },
  {
    pattern: /\bgit\s+push\b[^\r\n]*(?:--force(?:-with-lease)?\b|-f\b)/i,
    reason: "force push は禁止です。",
  },
  {
    pattern: /\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)/i,
    reason: "git reset --hard と git clean -f は禁止です。",
  },
  {
    pattern: /\b(?:mkfs|format\s+[a-z]:|dd\s+if=)/i,
    reason: "ディスクを破壊し得るコマンドは禁止です。",
  },
  {
    pattern: /\b(?:zip|compress-archive)\b[^\r\n]*\b(?:raw|refs|review|SESSION\.md|three-view|meta|plan\.md)\b/i,
    reason: "提出 ZIP に写真、三面図、確認一覧、SESSION、メタを含めないでください。",
  },
  {
    pattern: /\bchmod\s+-R\s+777\b/i,
    reason: "chmod -R 777 は禁止です。",
  },
];

const IRREVERSIBLE = [
  /\u540c\u610f\u3057\u307e\u3059/i,
  /\bi\s+agree\b/i,
  /\bagree\s+to\s+(?:the\s+)?terms\b/i,
  /\u5be9\u67fb\u3092\u30ea\u30af\u30a8\u30b9\u30c8/i,
  /\u5be9\u67fb\u30ea\u30af\u30a8\u30b9\u30c8/i,
  /request\s*(?:a\s*)?review/i,
  /submit\s*for\s*review/i,
  /\u30ea\u30ea\u30fc\u30b9/i,
  /\brelease\b/i,
  /\u8ca9\u58f2\u958b\u59cb/i,
  /start\s*sales/i,
  /\u524a\u9664/i,
  /\bdelete\b/i,
  /\u8ca9\u58f2\u505c\u6b62/i,
  /\u516c\u958b\u505c\u6b62/i,
];

const CREDENTIALS = [
  /password/i,
  /\u30d1\u30b9\u30ef\u30fc\u30c9/i,
  /passcode/i,
  /\u8a8d\u8a3c\u30b3\u30fc\u30c9/i,
  /verification\s*code/i,
  /\botp\b/i,
  /\bpin\b/i,
];

const LINE_CONTEXT = /creator(?:\.|\s+)line(?:\.|\s+)me|line\s+creators|creators\s+market|\bsticker\b|\u30b9\u30bf\u30f3\u30d7/i;
const LOCAL_FILE_TOOL_NAMES = new Set([
  "read",
  "write",
  "edit",
  "glob",
  "grep",
  "apply_patch",
  "view_image",
  "read_file",
  "write_file",
  "edit_file",
  "search_files",
]);
const SHELL_TOOL_NAMES = new Set([
  "bash",
  "shell",
  "terminal",
  "execcommand",
  "runcommand",
  "executecommand",
  "shellcommand",
]);
const PATH_KEYS = new Set([
  "path",
  "paths",
  "file",
  "files",
  "filepath",
  "filename",
  "target",
  "targetpath",
]);
const DESCRIPTOR_KEYS = new Set(["field", "name", "label", "selector", "element", "target", "placeholder"]);
const ENTRY_KEYS = new Set(["text", "value", "input", "chars", "keystrokes", "data"]);

function compactToolName(toolName) {
  return toolName.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function toolWords(toolName) {
  return toolName.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function isLocalFileTool(toolName) {
  const normalized = toolName.toLowerCase().replace(/^functions[._]{1,2}/, "");
  if (LOCAL_FILE_TOOL_NAMES.has(normalized)) return true;
  return /^mcp__filesystem__(?:read_file|write_file|edit_file|search_files)$/.test(normalized);
}

function isShellTool(toolName) {
  const compact = compactToolName(toolName).replace(/^functions/, "");
  if (SHELL_TOOL_NAMES.has(compact)) return true;
  return [...SHELL_TOOL_NAMES].some((name) => compact.endsWith(name));
}

function isDeletionTool(toolName) {
  const words = toolWords(toolName);
  return /(?:^|\s)(?:delete|remove|unlink|rmdir)(?:\s|$)/.test(words);
}

function isReadOnlyExternalTool(toolName) {
  const words = toolWords(toolName);
  const readOnly = /(?:^|\s)(?:search|query|find|open|navigate|screenshot|snapshot|read|get|list|view|fetch)(?:\s|$)/;
  const mutating = /(?:^|\s)(?:click|type|fill|input|submit|press|select|upload|create|update|delete|remove|release|write|edit|execute|call)(?:\s|$)/;
  return readOnly.test(words) && !mutating.test(words);
}

function matchesAny(patterns, text) {
  return patterns.some((pattern) => pattern.test(text));
}

function collectExplicitPaths(value, key = "", results = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectExplicitPaths(item, key, results);
    return results;
  }
  if (!value || typeof value !== "object") {
    if (PATH_KEYS.has(key.toLowerCase().replace(/[^a-z]/g, "")) && typeof value === "string") {
      results.push(value);
    }
    return results;
  }
  for (const [childKey, childValue] of Object.entries(value)) {
    collectExplicitPaths(childValue, childKey, results);
  }
  return results;
}

function collectPatchPaths(value, results = []) {
  if (typeof value === "string") {
    for (const match of value.matchAll(/^\*\*\* (?:Add|Update|Delete) File:\s*(.+)$/gm)) {
      results.push(match[1].trim());
    }
    return results;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectPatchPaths(item, results);
    return results;
  }
  if (!value || typeof value !== "object") return results;
  for (const [key, child] of Object.entries(value)) {
    if (typeof child === "string" && /patch/i.test(key)) {
      collectPatchPaths(child, results);
    } else {
      collectPatchPaths(child, results);
    }
  }
  return results;
}

function normalizePathValue(value) {
  return String(value).trim().replace(/^["']|["']$/g, "").replaceAll("\\", "/").replace(/\/+$/, "");
}

function isSensitivePath(value) {
  const normalized = normalizePathValue(value).toLowerCase();
  const basename = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (basename === ".env.example") return false;
  if (basename === ".env" || basename.startsWith(".env.")) return true;
  return basename === "settings.local.json";
}

function isProtectedProjectPath(value) {
  return /(?:^|\/)(?:projects|submit)(?:\/|$)/i.test(normalizePathValue(value));
}

function commandAccessesSensitivePath(command) {
  if (!/\b(?:cat|type|more|get-content|gc|grep|rg|select-string|findstr|head|tail|set-content|sc|add-content|out-file|tee|copy-item|cp|move-item|mv|writealltext|writeallbytes)\b/i.test(command)) {
    return false;
  }
  const tokens = command.match(/"[^"]*"|'[^']*'|[^\s]+/g) ?? [];
  return tokens.some(isSensitivePath);
}

function hasCredentialEntry(toolName, value) {
  let descriptorMentionsCredential = matchesAny(CREDENTIALS, toolName);
  let hasEntryValue = false;
  let directCredentialValue = false;

  function visit(current) {
    if (Array.isArray(current)) {
      for (const item of current) visit(item);
      return;
    }
    if (!current || typeof current !== "object") return;
    for (const [key, child] of Object.entries(current)) {
      const normalizedKey = key.toLowerCase().replace(/[^a-z]/g, "");
      const childText = typeof child === "string" ? child : "";
      if (matchesAny(CREDENTIALS, key) && child !== null && String(child).length > 0) {
        directCredentialValue = true;
      }
      if (DESCRIPTOR_KEYS.has(normalizedKey) && matchesAny(CREDENTIALS, childText)) {
        descriptorMentionsCredential = true;
      }
      if (ENTRY_KEYS.has(normalizedKey) && child !== null && String(child).length > 0) {
        hasEntryValue = true;
      }
      visit(child);
    }
  }

  visit(value);
  return directCredentialValue || (descriptorMentionsCredential && hasEntryValue);
}

function getToolInput(payload) {
  return payload?.tool_input ?? payload?.toolInput ?? {};
}

function getCommand(toolInput) {
  if (!toolInput || typeof toolInput !== "object") return "";
  return String(toolInput.command ?? toolInput.cmd ?? "");
}

export function evaluateToolUse(payload) {
  const toolInput = getToolInput(payload);
  const toolName = String(payload?.tool_name ?? payload?.toolName ?? "");
  const explicitPaths = [...collectExplicitPaths(toolInput), ...collectPatchPaths(toolInput)];

  if (explicitPaths.some(isSensitivePath)) {
    return ".env や個人用設定はエージェントが読み書きしません。";
  }

  if (isDeletionTool(toolName) && explicitPaths.some(isProtectedProjectPath)) {
    return "projects/ または submit/ の削除はエージェントが実行しません。";
  }

  const command = isShellTool(toolName) ? getCommand(toolInput) : "";
  if (command) {
    for (const rule of COMMAND_DENY_RULES) {
      if (rule.pattern.test(command)) {
        return `${rule.reason} command=${command.slice(0, 160)}`;
      }
    }
    if (commandAccessesSensitivePath(command)) {
      return ".env や個人用設定はエージェントが読み書きしません。";
    }
  }

  if (isLocalFileTool(toolName)) return null;

  let blob;
  try {
    blob = JSON.stringify(toolInput);
  } catch {
    return "ツール入力を安全に検査できませんでした。";
  }

  if (hasCredentialEntry(toolName, toolInput)) {
    return "ログイン情報・パスワード・認証コードの入力はユーザー本人だけが行います。";
  }

  const semanticAction = `${toolName} ${blob}`.replace(/[_./:-]+/g, " ");
  if (
    !isReadOnlyExternalTool(toolName)
    && LINE_CONTEXT.test(semanticAction)
    && matchesAny(IRREVERSIBLE, semanticAction)
  ) {
    return "審査時の法的同意と、審査リクエスト、リリース、削除などの不可逆操作はユーザー本人だけが実行します。";
  }
  return null;
}
