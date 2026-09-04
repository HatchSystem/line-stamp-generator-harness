#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const EXPECTED_ROLES = [
  "character-designer",
  "pack-validator",
  "publisher",
  "stamp-producer",
];
const EXPECTED_SKILLS = ["line-stamp-generator", "plan", "review"];
const FACADE_FILE = "scripts/line_stamp.py";
const SKILL_SCRIPT_DIRECTORY = ".agents/skills/line-stamp-generator/scripts";
const PROJECT_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/project.py`;
const PUBLISH_CHECK_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/check_publish_ready.py`;
const COMPOSE_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/compose_static.py`;
const CONTACT_SHEET_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/make_contact_sheet.py`;
const PACK_VALIDATOR_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/validate_pack.py`;
const PACKAGER_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/package_static.py`;
const PREPROCESS_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/preprocess_character.py`;
const TRANSACTION_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/transaction_utils.py`;
const VERIFY_TEXT_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/verify_text.py`;
const SESSION_CONTRACT_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/session_contract.py`;
const METADATA_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/metadata_utils.py`;
const PROJECT_CONTEXT_IMPLEMENTATION = `${SKILL_SCRIPT_DIRECTORY}/project_context.py`;
const PYTHON_SELF_TEST = `${SKILL_SCRIPT_DIRECTORY}/self_test.py`;
const SUBMISSION_EXAMPLE = ".agents/skills/line-stamp-generator/assets/submission.example.json";
const EXPECTED_PROJECT_ACTIONS = ["confirm-p0", "list", "migrate", "new", "status", "use"];
const PROJECT_COMMAND_DOCS = [
  "README.md",
  ".agents/skills/line-stamp-generator/references/commands.md",
];
const SCHEMA_GUIDE_DOCS = [
  ".agents/skills/line-stamp-generator/references/application.md",
  ".agents/skills/line-stamp-generator/references/gates.md",
];
const CURRENT_SCHEMA_VERSION = 3;
const EXPECTED_FACADE_COMMANDS = new Map([
  ["check-publish-ready", "check_publish_ready.py"],
  ["compose-static", "compose_static.py"],
  ["make-contact-sheet", "make_contact_sheet.py"],
  ["package-static", "package_static.py"],
  ["preprocess-character", "preprocess_character.py"],
  ["project", "project.py"],
  ["self-test", "self_test.py"],
  ["validate-pack", "validate_pack.py"],
  ["verify-text", "verify_text.py"],
]);
const PYTHON_EXTERNAL_MODULES = new Set([
  "PIL",
  "__future__",
  "argparse",
  "collections",
  "contextlib",
  "datetime",
  "difflib",
  "fcntl",
  "hashlib",
  "io",
  "importlib",
  "json",
  "math",
  "msvcrt",
  "numpy",
  "os",
  "pathlib",
  "pytesseract",
  "re",
  "runpy",
  "shutil",
  "stat",
  "subprocess",
  "sys",
  "tempfile",
  "typing",
  "unicodedata",
  "zipfile",
]);
const VENDORS = ["claude", "codex", "cursor"];
const TEXT_EXTENSIONS = new Set([
  ".cjs",
  ".js",
  ".json",
  ".md",
  ".mdc",
  ".mjs",
  ".py",
  ".sh",
  ".toml",
  ".txt",
  ".yaml",
  ".yml",
]);
const SCAN_EXCLUDED_DIRS = new Set([
  ".git",
  ".venv",
  "__pycache__",
  "node_modules",
  "tmp",
]);
const SKILL_FRONTMATTER_FIELDS = new Set([
  "allowed-tools",
  "compatibility",
  "description",
  "license",
  "metadata",
  "name",
]);
const HOOK_CONFIGS = new Map([
  [".claude/settings.json", "claude"],
  [".codex/hooks.json", "codex"],
  [".cursor/hooks.json", "cursor"],
]);
const COMMON_HOOKS = [
  "scripts/hooks/policy.mjs",
  "scripts/hooks/pre_tool_use.mjs",
  "scripts/hooks/project_context.mjs",
  "scripts/hooks/self_test.mjs",
];
const LEGACY_CLAUDE_HOOKS = new Map([
  [".claude/hooks/block-dangerous.py", "scripts/hooks/pre_tool_use.mjs"],
  [".claude/hooks/guard-submit.py", "scripts/hooks/pre_tool_use.mjs"],
  [".claude/hooks/session-start.sh", "scripts/hooks/project_context.mjs"],
  [".claude/hooks/gate-reminder.sh", "scripts/hooks/project_context.mjs"],
]);
const LEGACY_CLAUDE_RUNNER = ".claude/hooks/run-python-wrapper.mjs";

const diagnostics = [];
const textCache = new Map();
const jsonCache = new Map();
const tomlCache = new Map();
const frontmatterCache = new Map();
const frontmatterPresent = new Set();
const missingFrontmatterReported = new Set();
let checks = 0;


function posix(relativePath) {
  return relativePath.split(path.sep).join("/");
}


function absolute(relativePath) {
  return path.join(ROOT, ...relativePath.split("/"));
}


function addError(code, file, line, message) {
  diagnostics.push({ code, file: posix(file), line: line ?? 0, message });
}


function check(condition, code, file, line, message) {
  checks += 1;
  if (!condition) addError(code, file, line, message);
  return condition;
}


function lineAt(text, index) {
  return text.slice(0, index).split("\n").length;
}


function readText(relativePath) {
  const normalized = posix(relativePath);
  if (textCache.has(normalized)) return textCache.get(normalized);
  let text = "";
  try {
    text = fs.readFileSync(absolute(normalized), "utf8");
  } catch (error) {
    addError("READ", normalized, 0, `読み込めません: ${error.message}`);
    textCache.set(normalized, text);
    return text;
  }
  if (text.startsWith("\uFEFF")) {
    addError("UTF8_BOM", normalized, 1, "UTF-8 BOM を除去してください");
    text = text.slice(1);
  }
  if (text.includes("\uFFFD")) {
    addError("UTF8", normalized, 0, "UTF-8 として不正なバイト列があります");
  }
  textCache.set(normalized, text);
  return text;
}


function walk(relativeDirectory = "") {
  const results = [];
  const start = absolute(relativeDirectory);
  if (!fs.existsSync(start)) return results;

  function visit(currentAbsolute, currentRelative) {
    let entries;
    try {
      entries = fs.readdirSync(currentAbsolute, { withFileTypes: true });
    } catch (error) {
      addError("READ_DIR", currentRelative || ".", 0, `列挙できません: ${error.message}`);
      return;
    }
    entries.sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const childRelative = currentRelative
        ? `${currentRelative}/${entry.name}`
        : entry.name;
      const childAbsolute = path.join(currentAbsolute, entry.name);
      let stat;
      try {
        stat = fs.lstatSync(childAbsolute);
      } catch (error) {
        addError("LSTAT", childRelative, 0, `状態を取得できません: ${error.message}`);
        continue;
      }
      if (stat.isSymbolicLink()) {
        addError("SYMLINK", childRelative, 0, "シンボリックリンクは禁止です");
        continue;
      }
      if (stat.isDirectory()) {
        if (SCAN_EXCLUDED_DIRS.has(entry.name)) continue;
        if (childRelative === "projects") {
          const readme = `${childRelative}/README.md`;
          if (fs.existsSync(absolute(readme))) results.push(readme);
          continue;
        }
        visit(childAbsolute, childRelative);
      } else if (stat.isFile()) {
        results.push(childRelative);
      }
    }
  }

  visit(start, posix(relativeDirectory).replace(/\/$/, ""));
  return results;
}


function stripComment(line, marker = "#") {
  let quote = null;
  let escaped = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote === '"' && char === "\\") {
      escaped = true;
      continue;
    }
    if ((char === '"' || char === "'") && (!quote || quote === char)) {
      quote = quote ? null : char;
      continue;
    }
    if (!quote && char === marker) return line.slice(0, index);
  }
  return line;
}


function parseYamlScalar(raw, file, line) {
  const value = raw.trim();
  if (!value) return "";
  if (value.startsWith('"')) {
    try {
      return JSON.parse(value);
    } catch {
      addError("YAML_STRING", file, line, "二重引用符文字列が不正です");
      return value;
    }
  }
  if (value.startsWith("'")) {
    if (!value.endsWith("'") || value.length === 1) {
      addError("YAML_STRING", file, line, "単一引用符文字列が閉じていません");
      return value;
    }
    return value.slice(1, -1).replaceAll("''", "'");
  }
  if (value === "true") return true;
  if (value === "false") return false;
  if (value === "null" || value === "~") return null;
  if (/^[+-]?(?:\d+|\d+\.\d+)$/.test(value)) return Number(value);
  if (/:\s/.test(value)) {
    addError(
      "YAML_PLAIN_SCALAR",
      file,
      line,
      "未引用の値に ': ' を含められません",
    );
  }
  return value;
}


function parseYamlMapping(lines, file, firstLine = 1) {
  const root = {};
  const stack = [{ indent: -1, object: root }];
  let block = null;

  for (let index = 0; index < lines.length; index += 1) {
    const sourceLine = lines[index];
    const lineNumber = firstLine + index;
    if (sourceLine.includes("\t")) {
      addError("YAML_TAB", file, lineNumber, "YAML のインデントにタブは使えません");
    }
    const indent = sourceLine.match(/^ */)?.[0].length ?? 0;
    if (block && (sourceLine.trim() === "" || indent > block.indent)) {
      if (sourceLine.trim()) block.parts.push(sourceLine.slice(block.indent + 1));
      continue;
    }
    if (block) {
      block.parent[block.key] = block.parts.join(block.folded ? " " : "\n");
      block = null;
    }

    const uncommented = stripComment(sourceLine).trimEnd();
    if (!uncommented.trim()) continue;
    const match = uncommented.match(/^\s*([A-Za-z0-9_.-]+)\s*:\s*(.*)$/);
    if (!match) {
      addError("YAML_SYNTAX", file, lineNumber, "key: value 形式ではありません");
      continue;
    }

    while (stack.length > 1 && indent <= stack.at(-1).indent) stack.pop();
    const parent = stack.at(-1).object;
    const key = match[1];
    const rawValue = match[2].trim();
    if (Object.hasOwn(parent, key)) {
      addError("YAML_DUPLICATE_KEY", file, lineNumber, `キー '${key}' が重複しています`);
      continue;
    }
    if (/^[|>][+-]?$/.test(rawValue)) {
      parent[key] = "";
      block = {
        folded: rawValue.startsWith(">"),
        indent,
        key,
        parent,
        parts: [],
      };
    } else if (!rawValue) {
      parent[key] = {};
      stack.push({ indent, object: parent[key] });
    } else {
      parent[key] = parseYamlScalar(rawValue, file, lineNumber);
    }
  }
  if (block) block.parent[block.key] = block.parts.join(block.folded ? " " : "\n");
  return root;
}


function parseFrontmatter(relativePath, required = false) {
  if (frontmatterCache.has(relativePath)) {
    const cached = frontmatterCache.get(relativePath);
    if (required && !cached && !frontmatterPresent.has(relativePath) && !missingFrontmatterReported.has(relativePath)) {
      addError("FRONTMATTER_MISSING", relativePath, 1, "YAML frontmatter が必要です");
      missingFrontmatterReported.add(relativePath);
    }
    return cached;
  }
  const text = readText(relativePath);
  const lines = text.split(/\r?\n/);
  if (lines[0] !== "---") {
    if (required) {
      addError("FRONTMATTER_MISSING", relativePath, 1, "YAML frontmatter が必要です");
      missingFrontmatterReported.add(relativePath);
    }
    frontmatterCache.set(relativePath, null);
    return null;
  }
  frontmatterPresent.add(relativePath);
  const end = lines.indexOf("---", 1);
  if (end < 0) {
    addError("FRONTMATTER_UNCLOSED", relativePath, 1, "YAML frontmatter が閉じていません");
    frontmatterCache.set(relativePath, null);
    return null;
  }
  const data = parseYamlMapping(lines.slice(1, end), relativePath, 2);
  const result = { body: lines.slice(end + 1).join("\n"), data, endLine: end + 1 };
  frontmatterCache.set(relativePath, result);
  return result;
}


function validateBasicYaml(relativePath) {
  const text = readText(relativePath);
  const lines = text.split(/\r?\n/);
  let inBlock = false;
  let blockIndent = -1;
  for (let index = 0; index < lines.length; index += 1) {
    const sourceLine = lines[index];
    const lineNumber = index + 1;
    const indent = sourceLine.match(/^ */)?.[0].length ?? 0;
    if (sourceLine.includes("\t")) {
      addError("YAML_TAB", relativePath, lineNumber, "YAML のインデントにタブは使えません");
    }
    if (inBlock && (sourceLine.trim() === "" || indent > blockIndent)) continue;
    inBlock = false;
    const line = stripComment(sourceLine).trim();
    if (!line || line === "---" || line === "...") continue;
    if (/^(?:-\s+)?[A-Za-z0-9_.-]+\s*:\s*/.test(line)) {
      if (/[|>][+-]?\s*$/.test(line)) {
        inBlock = true;
        blockIndent = indent;
      }
      continue;
    }
    if (/^-\s+(?:[^:]+|[A-Za-z0-9_.-]+\s*:\s*.*)$/.test(line)) continue;
    if (/^[\[\]{}]/.test(line)) continue;
    addError("YAML_SYNTAX", relativePath, lineNumber, "基本的な YAML 構文として解釈できません");
  }
}


function parseTomlString(value, file, line) {
  if (value.startsWith('"')) {
    try {
      return JSON.parse(value);
    } catch {
      addError("TOML_STRING", file, line, "二重引用符文字列が不正です");
      return value;
    }
  }
  if (value.startsWith("'")) {
    if (!value.endsWith("'") || value.length === 1) {
      addError("TOML_STRING", file, line, "単一引用符文字列が閉じていません");
      return value;
    }
    return value.slice(1, -1);
  }
  return null;
}


function balancedTomlValue(value) {
  const pairs = { "[": "]", "{": "}" };
  const stack = [];
  let quote = null;
  let escaped = false;
  for (const char of value) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quote === '"' && char === "\\") {
      escaped = true;
      continue;
    }
    if ((char === '"' || char === "'") && (!quote || quote === char)) {
      quote = quote ? null : char;
      continue;
    }
    if (quote) continue;
    if (pairs[char]) stack.push(pairs[char]);
    else if (char === "]" || char === "}") {
      if (stack.pop() !== char) return false;
    }
  }
  return !quote && stack.length === 0;
}


function parseBasicToml(relativePath) {
  if (tomlCache.has(relativePath)) return tomlCache.get(relativePath);
  const values = {};
  const seen = new Set();
  const lines = readText(relativePath).split(/\r?\n/);
  let section = "";
  let multiline = null;

  function save(key, value, lineNumber) {
    const fullKey = section ? `${section}.${key}` : key;
    if (seen.has(fullKey)) {
      addError("TOML_DUPLICATE_KEY", relativePath, lineNumber, `キー '${fullKey}' が重複しています`);
      return;
    }
    seen.add(fullKey);
    values[fullKey] = value;
  }

  for (let index = 0; index < lines.length; index += 1) {
    const sourceLine = lines[index];
    const lineNumber = index + 1;
    if (multiline) {
      const close = sourceLine.indexOf(multiline.delimiter);
      if (close < 0) {
        multiline.parts.push(sourceLine);
        continue;
      }
      multiline.parts.push(sourceLine.slice(0, close));
      if (stripComment(sourceLine.slice(close + 3)).trim()) {
        addError("TOML_SYNTAX", relativePath, lineNumber, "複数行文字列の後に不正な文字があります");
      }
      save(multiline.key, multiline.parts.join("\n"), multiline.line);
      multiline = null;
      continue;
    }

    const line = stripComment(sourceLine).trim();
    if (!line) continue;
    const table = line.match(/^\[([A-Za-z0-9_.-]+)\]$/);
    if (table) {
      section = table[1];
      continue;
    }
    const assignment = line.match(/^([A-Za-z0-9_.-]+)\s*=\s*(.+)$/);
    if (!assignment) {
      addError("TOML_SYNTAX", relativePath, lineNumber, "key = value 形式ではありません");
      continue;
    }
    const key = assignment[1];
    const rawValue = assignment[2].trim();
    const delimiter = rawValue.startsWith('"""')
      ? '"""'
      : rawValue.startsWith("'''")
        ? "'''"
        : null;
    if (delimiter) {
      const remainder = rawValue.slice(3);
      const close = remainder.indexOf(delimiter);
      if (close >= 0) {
        if (stripComment(remainder.slice(close + 3)).trim()) {
          addError("TOML_SYNTAX", relativePath, lineNumber, "複数行文字列の後に不正な文字があります");
        }
        save(key, remainder.slice(0, close), lineNumber);
      } else {
        multiline = { delimiter, key, line: lineNumber, parts: [remainder] };
      }
      continue;
    }
    const stringValue = parseTomlString(rawValue, relativePath, lineNumber);
    if (stringValue !== null) {
      save(key, stringValue, lineNumber);
      continue;
    }
    if (!balancedTomlValue(rawValue)) {
      addError("TOML_VALUE", relativePath, lineNumber, "値の引用符または括弧が閉じていません");
      continue;
    }
    if (!/^(?:true|false|[+-]?(?:\d[\d_]*)(?:\.\d[\d_]*)?|\[.*\]|\{.*\}|\d{4}-\d{2}-\d{2}.*)$/.test(rawValue)) {
      addError("TOML_VALUE", relativePath, lineNumber, "基本的な TOML 値として解釈できません");
      continue;
    }
    save(key, rawValue, lineNumber);
  }
  if (multiline) {
    addError("TOML_STRING", relativePath, multiline.line, "複数行文字列が閉じていません");
  }
  tomlCache.set(relativePath, values);
  return values;
}


function parseJson(relativePath) {
  if (jsonCache.has(relativePath)) return jsonCache.get(relativePath);
  let value = null;
  try {
    value = JSON.parse(readText(relativePath));
  } catch (error) {
    addError("JSON_SYNTAX", relativePath, 0, error.message);
  }
  jsonCache.set(relativePath, value);
  return value;
}


function validateMarkdownSyntax(relativePath) {
  const text = readText(relativePath);
  if (text.startsWith("---")) parseFrontmatter(relativePath);
  let fence = null;
  let fenceLine = 0;
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    const match = line.match(/^[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$/);
    if (!match) continue;
    const marker = match[1];
    if (!fence) {
      fence = marker;
      fenceLine = index + 1;
    } else if (marker[0] === fence[0] && marker.length >= fence.length && !match[2].trim()) {
      fence = null;
      fenceLine = 0;
    }
  }
  if (fence) addError("MARKDOWN_FENCE", relativePath, fenceLine, "コードフェンスが閉じていません");
}


function hasTodoPlaceholderOutsideFence(body) {
  let fence = null;
  for (const line of body.split(/\r?\n/)) {
    const markerMatch = line.match(/^[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$/);
    if (markerMatch) {
      const marker = markerMatch[1];
      if (!fence) fence = marker;
      else if (marker[0] === fence[0] && marker.length >= fence.length && !markerMatch[2].trim()) fence = null;
      continue;
    }
    if (!fence && /^ {0,3}\[TODO:[^\n]*\]\s*$/.test(line)) return true;
  }
  return false;
}


function isExternalReference(target) {
  return (
    /^#/.test(target) ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(target) ||
    /^\\\\/.test(target)
  );
}


function cleanReference(target) {
  let cleaned = target.trim();
  if (cleaned.startsWith("<") && cleaned.endsWith(">")) cleaned = cleaned.slice(1, -1);
  cleaned = cleaned.split("#", 1)[0].split("?", 1)[0];
  try {
    cleaned = decodeURIComponent(cleaned);
  } catch {
    // The existence check below reports the malformed/unresolved target.
  }
  return cleaned.replaceAll("\\", "/");
}


function validateLocalReference(relativePath, target, line, kind) {
  const cleaned = cleanReference(target);
  if (!cleaned || isExternalReference(cleaned)) return;
  if (/[<>{}*]/.test(cleaned)) return;
  let resolved;
  if (kind === "import" || cleaned.startsWith("/")) {
    resolved = path.resolve(ROOT, cleaned.replace(/^\/+/, ""));
  } else {
    resolved = path.resolve(path.dirname(absolute(relativePath)), cleaned);
  }
  const relative = path.relative(ROOT, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    addError("REF_ESCAPE", relativePath, line, `参照がリポジトリ外へ出ます: ${target}`);
    return;
  }
  checks += 1;
  if (!fs.existsSync(resolved)) {
    addError("REF_MISSING", relativePath, line, `${kind} の参照先がありません: ${target}`);
  }
}


function validateMarkdownReferences(relativePath) {
  const text = readText(relativePath);
  const linkPattern = /!?\[[^\]\r\n]*\]\(\s*(?:<([^>\r\n]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)/g;
  for (const match of text.matchAll(linkPattern)) {
    validateLocalReference(relativePath, match[1] ?? match[2], lineAt(text, match.index), "link");
  }
  for (const reference of markdownImports(text)) {
    validateLocalReference(relativePath, reference.target, reference.line, "import");
  }
}


function markdownImports(text) {
  const imports = [];
  const pattern = /(?<![A-Za-z0-9_@])@((?:\.{0,2}\/)?(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+\.(?:json|md|mdc|toml|yaml|yml))(?![A-Za-z0-9_.-])/g;
  for (const match of text.matchAll(pattern)) {
    imports.push({ line: lineAt(text, match.index), target: cleanReference(match[1]) });
  }
  return imports;
}


function validateSkill(relativePath) {
  const parentName = path.posix.basename(path.posix.dirname(relativePath));
  const frontmatter = parseFrontmatter(relativePath, true);
  if (!frontmatter) return null;
  const { data, body } = frontmatter;
  for (const key of Object.keys(data)) {
    if (!SKILL_FRONTMATTER_FIELDS.has(key)) {
      addError("SKILL_FIELD", relativePath, 2, `未対応の frontmatter キーです: ${key}`);
    }
  }
  const name = data.name;
  const description = data.description;
  check(typeof name === "string" && name.length > 0, "SKILL_NAME", relativePath, 2, "name は空でない文字列が必要です");
  if (typeof name === "string") {
    check(name.length <= 64, "SKILL_NAME_LENGTH", relativePath, 2, "name は64文字以内です");
    check(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name), "SKILL_NAME_FORMAT", relativePath, 2, "name は小文字・数字・単一ハイフンだけを使います");
    check(name === parentName, "SKILL_NAME_DIR", relativePath, 2, `name は親ディレクトリ名 '${parentName}' と一致させます`);
  }
  check(typeof description === "string" && description.length > 0, "SKILL_DESCRIPTION", relativePath, 3, "description は空でない文字列が必要です");
  if (typeof description === "string") {
    check(description.length <= 1024, "SKILL_DESCRIPTION_LENGTH", relativePath, 3, "description は1024文字以内です");
    check(!/[<>]/.test(description), "SKILL_DESCRIPTION_XML", relativePath, 3, "description に山括弧は使えません");
  }
  if (Object.hasOwn(data, "compatibility")) {
    check(typeof data.compatibility === "string" && data.compatibility.length > 0 && data.compatibility.length <= 500, "SKILL_COMPATIBILITY", relativePath, 0, "compatibility は1〜500文字の文字列です");
  }
  if (Object.hasOwn(data, "metadata")) {
    const validMetadata = data.metadata && typeof data.metadata === "object" && !Array.isArray(data.metadata)
      && Object.values(data.metadata).every((value) => typeof value === "string");
    check(validMetadata, "SKILL_METADATA", relativePath, 0, "metadata は文字列値のマッピングです");
  }
  for (const optionalString of ["allowed-tools", "license"]) {
    if (Object.hasOwn(data, optionalString)) {
      check(typeof data[optionalString] === "string" && data[optionalString].length > 0, "SKILL_OPTIONAL_FIELD", relativePath, 0, `${optionalString} は空でない文字列です`);
    }
  }
  check(body.trim().length > 0, "SKILL_BODY", relativePath, frontmatter.endLine + 1, "スキル本文が空です");
  if (hasTodoPlaceholderOutsideFence(body)) {
    addError("SKILL_TODO", relativePath, frontmatter.endLine + 1, "未完了の TODO プレースホルダーがあります");
  }
  return { description, name };
}


function immediateFileStems(relativeDirectory, extension) {
  const directory = absolute(relativeDirectory);
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .map((entry) => entry.name.slice(0, -extension.length))
    .sort();
}


function compareSet(actual, expected, label, file) {
  const actualSorted = [...actual].sort();
  const expectedSorted = [...expected].sort();
  check(
    JSON.stringify(actualSorted) === JSON.stringify(expectedSorted),
    "ADAPTER_SET",
    file,
    0,
    `${label}: expected=${expectedSorted.join(",")} actual=${actualSorted.join(",")}`,
  );
}


function validateClaudeCommands(canonicalSkills) {
  const commandDirectory = ".claude/commands";
  const commands = immediateFileStems(commandDirectory, ".md");
  compareSet(commands, canonicalSkills, "claude commands", commandDirectory);
  if (fs.existsSync(absolute(commandDirectory))) {
    for (const entry of fs.readdirSync(absolute(commandDirectory), { withFileTypes: true })) {
      if (entry.isDirectory() || (entry.isFile() && !entry.name.endsWith(".md"))) {
        addError(
          "COMMAND_LAYOUT",
          `${commandDirectory}/${entry.name}`,
          0,
          "Claude command ディレクトリには canonical skill と同名の Markdown だけを置いてください",
        );
      }
    }
  }
  for (const name of canonicalSkills) {
    const file = `${commandDirectory}/${name}.md`;
    if (!fs.existsSync(absolute(file))) continue;
    const frontmatter = parseFrontmatter(file, true);
    if (frontmatter) {
      check(
        typeof frontmatter.data.description === "string" && frontmatter.data.description.length > 0,
        "COMMAND_DESCRIPTION",
        file,
        2,
        "Claude command には空でない description が必要です",
      );
    }
    const expectedImport = `.agents/skills/${name}/SKILL.md`;
    const imports = markdownImports(readText(file)).map((entry) => entry.target);
    check(
      imports.length === 1 && imports[0] === expectedImport,
      "COMMAND_IMPORT",
      file,
      0,
      `@${expectedImport} だけを import してください`,
    );
  }
}


function validateRolesAndAdapters() {
  const canonicalFiles = immediateFileStems(".agents/roles", ".md");
  compareSet(canonicalFiles, EXPECTED_ROLES, "canonical roles", ".agents/roles");
  const canonical = new Map();
  for (const name of canonicalFiles) {
    const file = `.agents/roles/${name}.md`;
    const frontmatter = parseFrontmatter(file, true);
    if (!frontmatter) continue;
    const keys = Object.keys(frontmatter.data).sort();
    check(
      JSON.stringify(keys) === JSON.stringify(["description", "name"]),
      "ROLE_FRONTMATTER",
      file,
      1,
      "共通 role の frontmatter は name と description だけにします",
    );
    check(frontmatter.data.name === name, "ROLE_NAME", file, 2, "name はファイル名と一致させます");
    check(typeof frontmatter.data.description === "string" && frontmatter.data.description.length > 0, "ROLE_DESCRIPTION", file, 3, "description は空でない文字列が必要です");
    canonical.set(name, frontmatter.data);
  }

  const adapterSets = new Map([
    ["claude", immediateFileStems(".claude/agents", ".md")],
    ["codex", immediateFileStems(".codex/agents", ".toml")],
    ["cursor", immediateFileStems(".cursor/agents", ".md")],
  ]);
  for (const [vendor, names] of adapterSets) {
    compareSet(names, canonicalFiles, `${vendor} agents`, `.${vendor}/agents`);
  }

  for (const name of canonicalFiles) {
    const metadata = canonical.get(name);
    if (!metadata) continue;
    for (const vendor of ["claude", "cursor"]) {
      const file = `.${vendor}/agents/${name}.md`;
      if (!fs.existsSync(absolute(file))) continue;
      const frontmatter = parseFrontmatter(file, true);
      if (!frontmatter) continue;
      check(frontmatter.data.name === metadata.name, "ADAPTER_NAME", file, 2, "name が canonical role と一致しません");
      check(frontmatter.data.description === metadata.description, "ADAPTER_DESCRIPTION", file, 3, "description が canonical role と一致しません");
      check(frontmatter.body.includes("AGENTS.md"), "ADAPTER_ROOT_REF", file, frontmatter.endLine + 1, "AGENTS.md を読む指示が必要です");
      check(frontmatter.body.includes(`.agents/roles/${name}.md`), "ADAPTER_ROLE_REF", file, frontmatter.endLine + 1, "対応する canonical role を読む指示が必要です");
    }

    const codexFile = `.codex/agents/${name}.toml`;
    if (!fs.existsSync(absolute(codexFile))) continue;
    const values = parseBasicToml(codexFile);
    check(values.name === metadata.name, "ADAPTER_NAME", codexFile, 1, "name が canonical role と一致しません");
    check(values.description === metadata.description, "ADAPTER_DESCRIPTION", codexFile, 2, "description が canonical role と一致しません");
    check(typeof values.developer_instructions === "string" && values.developer_instructions.includes("AGENTS.md"), "ADAPTER_ROOT_REF", codexFile, 0, "developer_instructions で AGENTS.md を読む必要があります");
    check(typeof values.developer_instructions === "string" && values.developer_instructions.includes(`.agents/roles/${name}.md`), "ADAPTER_ROLE_REF", codexFile, 0, "developer_instructions で canonical role を読む必要があります");
    for (const forbidden of ["model", "tools"]) {
      check(!Object.hasOwn(values, forbidden), "ADAPTER_VENDOR_COPY", codexFile, 0, `共通 role 由来の ${forbidden} を固定しないでください`);
    }
  }
}


function validateSkills() {
  const skillsRoot = absolute(".agents/skills");
  const names = fs.existsSync(skillsRoot)
    ? fs.readdirSync(skillsRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()
    : [];
  compareSet(names, EXPECTED_SKILLS, "canonical skills", ".agents/skills");
  const declared = new Set();
  for (const name of names) {
    const file = `.agents/skills/${name}/SKILL.md`;
    if (!check(fs.existsSync(absolute(file)), "SKILL_ENTRYPOINT", file, 0, "SKILL.md がありません")) continue;
    const metadata = validateSkill(file);
    if (!metadata?.name) continue;
    if (declared.has(metadata.name)) {
      addError("SKILL_DUPLICATE_NAME", file, 2, `skill name '${metadata.name}' が重複しています`);
    }
    declared.add(metadata.name);
  }
  for (const vendor of VENDORS) {
    const duplicate = `.${vendor}/skills`;
    check(!fs.existsSync(absolute(duplicate)), "DUPLICATE_SKILLS", duplicate, 0, "skills の正本は .agents/skills/ だけです");
  }
  validateClaudeCommands(names);
}


function isPublicCliPolicyFile(file) {
  if (
    (file.endsWith(".md") || file.endsWith(".mdc")) &&
    file !== "tasks/todo.md" &&
    !file.startsWith("tasks/history/")
  ) return true;
  return VENDORS.some((vendor) =>
    file.startsWith(`.${vendor}/`) &&
    [".json", ".md", ".mdc", ".toml", ".yaml", ".yml"].includes(path.extname(file)));
}


function parseFacadeCommands(relativePath) {
  const commands = new Map();
  const text = readText(relativePath);
  const lines = text.split(/\r?\n/);
  const start = lines.findIndex((line) => /^COMMANDS\s*=\s*\{\s*(?:#.*)?$/.test(line));
  if (start < 0) {
    addError("FACADE_COMMANDS", relativePath, 0, "COMMANDS マッピングがありません");
    return commands;
  }
  let closed = false;
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^\s*}\s*(?:#.*)?$/.test(line)) {
      closed = true;
      break;
    }
    if (!line.trim() || /^\s*#/.test(line)) continue;
    const entry = line.match(/^\s*["']([a-z0-9]+(?:-[a-z0-9]+)*)["']\s*:\s*["']([A-Za-z0-9_]+\.py)["']\s*,?\s*(?:#.*)?$/);
    if (!entry) {
      addError("FACADE_COMMAND_ENTRY", relativePath, index + 1, "command: implementation.py 形式ではありません");
      continue;
    }
    if (commands.has(entry[1])) {
      addError("FACADE_COMMAND_DUPLICATE", relativePath, index + 1, `サブコマンド '${entry[1]}' が重複しています`);
      continue;
    }
    commands.set(entry[1], entry[2]);
  }
  if (!closed) addError("FACADE_COMMANDS", relativePath, start + 1, "COMMANDS マッピングが閉じていません");
  return commands;
}


function sortedMapEntries(mapping) {
  return [...mapping.entries()].sort(([left], [right]) => left.localeCompare(right, "en"));
}


function pythonImports(relativePath) {
  const imports = [];
  for (const [index, sourceLine] of readText(relativePath).split(/\r?\n/).entries()) {
    const line = stripComment(sourceLine).trim();
    const from = line.match(/^from\s+(\.*[A-Za-z_][A-Za-z0-9_.]*|\.+)\s+import\s+(.+)$/);
    if (from) {
      if (/^\.+$/.test(from[1])) {
        for (const imported of from[2].replace(/[()]/g, "").split(",")) {
          const name = imported.trim().split(/\s+as\s+|\s+/)[0];
          if (name && name !== "*") imports.push({ line: index + 1, module: `${from[1]}${name}` });
        }
      } else {
        imports.push({ line: index + 1, module: from[1] });
      }
      continue;
    }
    const direct = line.match(/^import\s+(.+)$/);
    if (!direct) continue;
    for (const imported of direct[1].split(",")) {
      const name = imported.trim().split(/\s+as\s+|\s+/)[0];
      if (name) imports.push({ line: index + 1, module: name });
    }
  }
  return imports;
}


function localPythonModuleTargets(sourceFile, module) {
  const leadingDots = module.match(/^\.+/)?.[0].length ?? 0;
  const moduleName = module.slice(leadingDots);
  let baseDirectory = path.dirname(absolute(sourceFile));
  for (let level = 1; level < leadingDots; level += 1) baseDirectory = path.dirname(baseDirectory);
  const parts = moduleName ? moduleName.split(".") : [];
  const moduleBase = path.join(baseDirectory, ...parts);
  return [`${moduleBase}.py`, path.join(moduleBase, "__init__.py")];
}


function validatePythonImports(relativePath, localModules) {
  for (const imported of pythonImports(relativePath)) {
    const leadingDots = imported.module.match(/^\.+/)?.[0].length ?? 0;
    const rootModule = imported.module.slice(leadingDots).split(".", 1)[0];
    const isKnownLocal = leadingDots > 0 || localModules.has(rootModule);
    if (!isKnownLocal) {
      check(
        PYTHON_EXTERNAL_MODULES.has(rootModule),
        "PYTHON_IMPORT_UNKNOWN",
        relativePath,
        imported.line,
        `Python なしでは import '${imported.module}' を標準/外部依存と判定できません。依存表またはローカル実装を更新してください`,
      );
      continue;
    }
    const targets = localPythonModuleTargets(relativePath, imported.module);
    check(
      targets.some((target) => fs.existsSync(target)),
      "PYTHON_LOCAL_IMPORT",
      relativePath,
      imported.line,
      `ローカル import '${imported.module}' の ${targets.map((target) => posix(path.relative(ROOT, target))).join(" または ")} がありません`,
    );
  }
}


function validateFacade(files) {
  if (!check(fs.existsSync(absolute(FACADE_FILE)), "FACADE_MISSING", FACADE_FILE, 0, "公開 CLI facade がありません")) return;
  const facadeText = readText(FACADE_FILE);
  const commands = parseFacadeCommands(FACADE_FILE);
  check(
    JSON.stringify(sortedMapEntries(commands)) === JSON.stringify(sortedMapEntries(EXPECTED_FACADE_COMMANDS)),
    "FACADE_COMMAND_MAP",
    FACADE_FILE,
    0,
    `9サブコマンドの対応が不正です: expected=${JSON.stringify(sortedMapEntries(EXPECTED_FACADE_COMMANDS))} actual=${JSON.stringify(sortedMapEntries(commands))}`,
  );
  check(/^def\s+main\s*\(/m.test(facadeText), "FACADE_MAIN", FACADE_FILE, 0, "facade に main() がありません");
  check(
    /script_dir\s*=\s*repo_root\s*\/\s*["']\.agents["']\s*\/\s*["']skills["']\s*\/\s*["']line-stamp-generator["']\s*\/\s*["']scripts["']/.test(facadeText) &&
      /script_path\s*=\s*script_dir\s*\/\s*script_name/.test(facadeText),
    "FACADE_SCRIPT_DIR",
    FACADE_FILE,
    0,
    `facade は ${SKILL_SCRIPT_DIRECTORY}/ の COMMANDS 対応先だけを実行してください`,
  );
  check(
    /\b(?:importlib_util|importlib\.util)\.spec_from_file_location\s*\(/.test(facadeText) &&
      /\b(?:importlib_util|importlib\.util)\.module_from_spec\s*\(/.test(facadeText) &&
      /\.loader\.exec_module\s*\(/.test(facadeText),
    "FACADE_IMPORTLIB",
    FACADE_FILE,
    0,
    "facade は importlib の spec/module/exec_module 経由で実装を読み込んでください",
  );
  check(!/\brunpy\b/.test(facadeText), "FACADE_RUNPY", FACADE_FILE, 0, "facade では runpy を使用できません");
  check(
    /sys\.path\.insert\(\s*0\s*,\s*str\(script_dir\)\s*\)/.test(facadeText) &&
      /finally\s*:[\s\S]*?sys\.path\s*\[\s*:\s*\]\s*=\s*original_path/.test(facadeText),
    "FACADE_IMPORT_PATH",
    FACADE_FILE,
    0,
    "importlib 実装は同階層 import 用の sys.path を追加し、finally で復元してください",
  );
  check(
    /entrypoint\s*=\s*getattr\(\s*module\s*,\s*["']main["']\s*,\s*None\s*\)/.test(facadeText) &&
      /callable\(entrypoint\)/.test(facadeText) &&
      /\bentrypoint\s*\(\s*\)/.test(facadeText),
    "FACADE_ENTRYPOINT",
    FACADE_FILE,
    0,
    "importlib で読み込んだ module の callable main() を呼び出してください",
  );

  const implementationFiles = files.filter((file) =>
    file.startsWith(`${SKILL_SCRIPT_DIRECTORY}/`) && file.endsWith(".py"));
  const localModules = new Set(implementationFiles.map((file) => path.posix.basename(file, ".py")));
  const mappedImplementations = new Set(EXPECTED_FACADE_COMMANDS.values());
  for (const [command, implementation] of EXPECTED_FACADE_COMMANDS) {
    const file = `${SKILL_SCRIPT_DIRECTORY}/${implementation}`;
    if (!check(fs.existsSync(absolute(file)), "FACADE_IMPLEMENTATION", file, 0, `サブコマンド '${command}' の実装がありません`)) continue;
    check(/^def\s+main\s*\(/m.test(readText(file)), "FACADE_IMPLEMENTATION_MAIN", file, 0, `サブコマンド '${command}' の callable main() が見つかりません`);
  }
  for (const file of implementationFiles) {
    if (/^def\s+main\s*\(/m.test(readText(file))) {
      check(
        mappedImplementations.has(path.posix.basename(file)),
        "FACADE_UNMAPPED_MAIN",
        file,
        0,
        "main() を持つ実装には公開サブコマンドの対応が必要です",
      );
    }
    validatePythonImports(file, localModules);
  }
  validatePythonImports(FACADE_FILE, localModules);
}


function cleanShellToken(token) {
  return token
    .replace(/^[`"'({\\]+/, "")
    .replace(/[`"'),}:\\]+$/, "");
}


function pythonScriptInvocations(text) {
  const invocations = [];
  const lines = text.split(/\r?\n/);
  const interpreterPattern = /(?<![A-Za-z0-9_.-])(?:python(?:3(?:\.\d+)?)?(?:\.exe)?|py(?:\.exe)?(?:\s+-3)?|uv\s+run)\b/g;
  const tokenPattern = /"(?:\\.|[^"])*"|'[^']*'|[^\s]+/g;
  for (const [index, line] of lines.entries()) {
    for (const interpreter of line.matchAll(interpreterPattern)) {
      const tail = line.slice(interpreter.index + interpreter[0].length).split(/[|;&]/, 1)[0];
      const tokens = [...tail.matchAll(tokenPattern)].map((match) => cleanShellToken(match[0]));
      const scriptIndex = tokens.findIndex((token) => /\.py$/i.test(token));
      if (scriptIndex < 0) continue;
      invocations.push({
        args: tokens.slice(scriptIndex + 1),
        command: tokens[scriptIndex + 1] ?? "",
        line: index + 1,
        target: tokens[scriptIndex].replaceAll("\\", "/"),
      });
    }
  }
  return invocations;
}


function projectAction(args) {
  for (let index = 1; index < args.length; index += 1) {
    const token = args[index].replace(/[,:]+$/, "");
    if (token === "--root") {
      index += 1;
      continue;
    }
    if (token.startsWith("--root=")) continue;
    if (!token) continue;
    return token;
  }
  return "";
}


function facadeInvocation(invocation) {
  return invocation.target.replace(/^\.\//, "").endsWith(FACADE_FILE);
}


function validatePublicCliPolicy(files) {
  const internalScriptNames = new Set([
    ...EXPECTED_FACADE_COMMANDS.values(),
    ...files
      .filter((file) => /^\.agents\/skills\/[^/]+\/scripts\/[^/]+\.py$/.test(file))
      .map((file) => path.posix.basename(file)),
  ]);
  const publicCommands = new Set(EXPECTED_FACADE_COMMANDS.keys());
  const placeholders = new Set(["*", "$command", "${command}", "--help", "-h", "<command>", "[command]"]);
  const projectPlaceholders = new Set(["$action", "${action}", "--help", "-h", "<action>", "[action]"]);
  const projectActions = new Set(EXPECTED_PROJECT_ACTIONS);
  for (const file of files.filter(isPublicCliPolicyFile)) {
    const text = readText(file);
    for (const invocation of pythonScriptInvocations(text)) {
      const basename = path.posix.basename(invocation.target);
      if (internalScriptNames.has(basename)) {
        addError(
          "PUBLIC_CLI_BYPASS",
          file,
          invocation.line,
          `skill 内部の ${basename} を直接実行せず、python scripts/line_stamp.py <command> を使ってください`,
        );
      }
      if (!facadeInvocation(invocation)) continue;
      const command = invocation.command.replace(/[,:.]+$/, "");
      if (!command || placeholders.has(command)) continue;
      if (!publicCommands.has(command)) {
        addError("PUBLIC_CLI_COMMAND", file, invocation.line, `公開 CLI にサブコマンド '${command}' はありません`);
        continue;
      }
      if (command !== "project") continue;
      const action = projectAction(invocation.args);
      if (!action || projectPlaceholders.has(action) || projectActions.has(action)) continue;
      addError("PUBLIC_CLI_PROJECT_ACTION", file, invocation.line, `公開 CLI の project にアクション '${action}' はありません`);
    }
  }
}


function projectImplementationActions(text) {
  return [...text.matchAll(/\bsub\.add_parser\(\s*["']([a-z0-9]+(?:-[a-z0-9]+)*)["']/g)]
    .map((match) => match[1]);
}


function validateProjectDocs() {
  for (const file of PROJECT_COMMAND_DOCS) {
    if (!check(fs.existsSync(absolute(file)), "PROJECT_DOC", file, 0, "project 公開 CLI の説明文書がありません")) continue;
    const invocations = pythonScriptInvocations(readText(file))
      .filter((invocation) => facadeInvocation(invocation) && invocation.command.replace(/[,:.]+$/, "") === "project");
    const actions = new Set(invocations.map((invocation) => projectAction(invocation.args)).filter(Boolean));
    check(
      JSON.stringify([...actions].sort()) === JSON.stringify([...EXPECTED_PROJECT_ACTIONS].sort()),
      "PROJECT_DOC_ACTIONS",
      file,
      0,
      `project の文書化アクションが実装と不一致です: expected=${[...EXPECTED_PROJECT_ACTIONS].sort().join(",")} actual=${[...actions].sort().join(",")}`,
    );
    const migrations = invocations.filter((invocation) => projectAction(invocation.args) === "migrate");
    check(
      migrations.some((invocation) => !invocation.args.includes("--apply")) &&
        migrations.some((invocation) => invocation.args.includes("--apply")),
      "PROJECT_DOC_MIGRATE",
      file,
      0,
      "project migrate の dry-run と明示的な --apply の両方を文書化してください",
    );
  }
}


function validateSchemaVersionPolicy() {
  if (!check(fs.existsSync(absolute(PROJECT_IMPLEMENTATION)), "PROJECT_IMPLEMENTATION", PROJECT_IMPLEMENTATION, 0, "project 実装がありません")) return;
  const projectText = readText(PROJECT_IMPLEMENTATION);
  const actions = projectImplementationActions(projectText);
  check(
    JSON.stringify([...new Set(actions)].sort()) === JSON.stringify([...EXPECTED_PROJECT_ACTIONS].sort()),
    "PROJECT_IMPLEMENTATION_ACTIONS",
    PROJECT_IMPLEMENTATION,
    0,
    `project argparse アクションが不正です: expected=${[...EXPECTED_PROJECT_ACTIONS].sort().join(",")} actual=${[...new Set(actions)].sort().join(",")}`,
  );
  check(
    new RegExp(`^SESSION_SCHEMA_VERSION\\s*=\\s*${CURRENT_SCHEMA_VERSION}\\s*$`, "m").test(projectText) &&
      new RegExp(`^SUBMISSION_SCHEMA_VERSION\\s*=\\s*${CURRENT_SCHEMA_VERSION}\\s*$`, "m").test(projectText),
    "PROJECT_SCHEMA_CONSTANTS",
    PROJECT_IMPLEMENTATION,
    0,
    `SESSION と submission の現行 schema_version は ${CURRENT_SCHEMA_VERSION} である必要があります`,
  );
  check(
    /f["']- schema_version:\s*\{SESSION_SCHEMA_VERSION\}["']/.test(projectText),
    "PROJECT_SESSION_TEMPLATE_SCHEMA",
    PROJECT_IMPLEMENTATION,
    0,
    "新規 SESSION は SESSION_SCHEMA_VERSION を出力してください",
  );
  check(
    /^def\s+cmd_migrate\s*\(/m.test(projectText) &&
      /session_migration_updates\(\s*session_values\s*,\s*materials_available\s*=\s*materials_available\s*,?\s*\)/.test(projectText) &&
      /migrated_submission\(parsed\)/.test(projectText) &&
      /p_migrate\.add_argument\(\s*["']--apply["']/.test(projectText) &&
      /p_migrate\.set_defaults\(\s*func\s*=\s*cmd_migrate\s*\)/.test(projectText),
    "PROJECT_MIGRATE_WIRING",
    PROJECT_IMPLEMENTATION,
    0,
    "migrate は SESSION/submission の移行を行い、書き込みを --apply で明示する必要があります",
  );

  if (check(fs.existsSync(absolute(PUBLISH_CHECK_IMPLEMENTATION)), "PUBLISH_CHECK", PUBLISH_CHECK_IMPLEMENTATION, 0, "公開前検査の実装がありません")) {
    const publishText = readText(PUBLISH_CHECK_IMPLEMENTATION);
    check(
      new RegExp(`^SESSION_SCHEMA_VERSION\\s*=\\s*["']${CURRENT_SCHEMA_VERSION}["']\\s*$`, "m").test(publishText) &&
        new RegExp(`^SUBMISSION_SCHEMA_VERSION\\s*=\\s*${CURRENT_SCHEMA_VERSION}\\s*$`, "m").test(publishText) &&
        /session\.get\(\s*["']schema_version["']\s*\)\s*!=\s*SESSION_SCHEMA_VERSION/.test(publishText) &&
        /meta\.get\(\s*["']schema_version["']\s*\)\s*!=\s*SUBMISSION_SCHEMA_VERSION/.test(publishText),
      "PUBLISH_SCHEMA_ENFORCEMENT",
      PUBLISH_CHECK_IMPLEMENTATION,
      0,
      `check-publish-ready は SESSION と submission の schema_version ${CURRENT_SCHEMA_VERSION} を検査してください`,
    );
  }

  if (check(fs.existsSync(absolute(SUBMISSION_EXAMPLE)), "SUBMISSION_EXAMPLE", SUBMISSION_EXAMPLE, 0, "submission の正本例がありません")) {
    const example = parseJson(SUBMISSION_EXAMPLE);
    check(
      objectValue(example)?.schema_version === CURRENT_SCHEMA_VERSION,
      "SUBMISSION_EXAMPLE_SCHEMA",
      SUBMISSION_EXAMPLE,
      0,
      `submission.example.json の schema_version は整数 ${CURRENT_SCHEMA_VERSION} である必要があります`,
    );
  }

  for (const file of SCHEMA_GUIDE_DOCS) {
    if (!check(fs.existsSync(absolute(file)), "SCHEMA_GUIDE", file, 0, "schema migration の説明文書がありません")) continue;
    const text = readText(file);
    check(
      new RegExp(`schema_version[^\\n]*\`?${CURRENT_SCHEMA_VERSION}\`?`).test(text) &&
        /project\s+--root\s+\.\s+migrate/.test(text),
      "SCHEMA_GUIDE_CURRENT",
      file,
      0,
      `schema_version ${CURRENT_SCHEMA_VERSION} と公開 CLI の project --root . migrate を説明してください`,
    );
  }

  if (check(fs.existsSync(absolute(PYTHON_SELF_TEST)), "PYTHON_SELF_TEST", PYTHON_SELF_TEST, 0, "Python 自己テストがありません")) {
    const selfTest = readText(PYTHON_SELF_TEST);
    check(
      /cmd_migrate\(Namespace\(root=str\(root\), apply=False\)\)/.test(selfTest) &&
        /cmd_migrate\(Namespace\(root=str\(root\), apply=True\)\)/.test(selfTest) &&
        new RegExp(`["']schema_version["']\\]\\s*==\\s*["']${CURRENT_SCHEMA_VERSION}["']`).test(selfTest) &&
        new RegExp(`["']schema_version["']\\]\\s*==\\s*${CURRENT_SCHEMA_VERSION}\\b`).test(selfTest),
      "PYTHON_MIGRATE_TEST",
      PYTHON_SELF_TEST,
      0,
      `自己テストは migrate の dry-run/apply と SESSION/submission schema v${CURRENT_SCHEMA_VERSION} を検証してください`,
    );
  }
}


function validateWorkflowContracts() {
  const projectText = readText(PROJECT_IMPLEMENTATION);
  check(
    /^def\s+cmd_confirm_p0\s*\(/m.test(projectText) &&
      /p_confirm\.set_defaults\(\s*func\s*=\s*cmd_confirm_p0\s*\)/.test(projectText) &&
      /["']gate["']\s*:\s*["']P1["']/.test(projectText),
    "P0_CONFIRM_WIRING",
    PROJECT_IMPLEMENTATION,
    0,
    "confirm-p0 は専用ハンドラへ接続し、検証済み入力だけを P1 へ進めてください",
  );
  for (const flag of [
    "materials",
    "source",
    "count",
    "text",
    "text-mode",
    "character-name",
    "sample-candidates",
    "publish",
  ]) {
    check(
      new RegExp(`p_confirm\\.add_argument\\(\\s*["']--${flag}["'][^\\n]*required\\s*=\\s*True`).test(projectText),
      "P0_CONFIRM_FIELD",
      PROJECT_IMPLEMENTATION,
      0,
      `confirm-p0 の --${flag} は明示必須にしてください`,
    );
  }
  for (const field of ["adult", "consent", "rights"]) {
    check(
      !new RegExp(`p_confirm\\.add_argument\\(\\s*["']--${field}["']`).test(projectText) &&
        !projectText.includes(`"- ${field}:`) &&
        !new RegExp(`["']${field}["']\\s*:\\s*args\\.`).test(projectText),
      "P0_DEPRECATED_FIELD",
      PROJECT_IMPLEMENTATION,
      0,
      `P0 は廃止済みの ${field} を引数・テンプレート・保存値に含めないでください`,
    );
  }
  check(
    /DEPRECATED_SESSION_KEYS\s*=\s*frozenset/.test(projectText) &&
      /^def\s+remove_session_keys\s*\(/m.test(projectText) &&
      /SESSION remove deprecated field/.test(projectText) &&
      /remove_session_keys\(migrated_session,\s*set\(session_removals\)\)/.test(projectText) &&
      /remove obsolete empty license_proof/.test(projectText) &&
      /run project migrate before confirming P0/.test(projectText),
    "P0_DEPRECATED_MIGRATION",
    PROJECT_IMPLEMENTATION,
    0,
    "v3 migration は adult・consent・rights を SESSION から明示的に除去してください",
  );
  check(
    projectText.includes('"- gate: P0"') &&
      projectText.includes('"- materials: pending"') &&
      projectText.includes('"- publish: unknown"'),
    "P0_INCOMPLETE_TEMPLATE",
    PROJECT_IMPLEMENTATION,
    0,
    "project new は未確定の P0 状態だけを作成してください",
  );
  check(
    /^def\s+reference_material_errors\s*\(/m.test(projectText) &&
      /entry\.is_symlink\(\)/.test(projectText) &&
      /material_count\s*==\s*0/.test(projectText) &&
      /errors\.extend\(reference_material_errors\(project\)\)/.test(projectText),
    "P0_MATERIAL_FILES",
    PROJECT_IMPLEMENTATION,
    0,
    "confirm-p0 は active project の refs/ に通常ファイルがあることを確認してください",
  );

  check(
    /candidate\s*=\s*harness\s*\/\s*["']projects["']/.test(projectText) &&
      /candidate\.is_symlink\(\)/.test(projectText) &&
      /base\s*!=\s*candidate/.test(projectText),
    "PROJECT_ROOT_INDIRECTION",
    PROJECT_IMPLEMENTATION,
    0,
    "projects/ 自体の symlink・junction 等の indirection を解決前後で拒否してください",
  );
  check(
    /tempfile\.mkdtemp\([^\n]*\.new-/.test(projectText) &&
      /os\.replace\(staging,\s*project\)/.test(projectText) &&
      /os\.replace\(project,\s*staging\)/.test(projectText),
    "PROJECT_NEW_TRANSACTION",
    PROJECT_IMPLEMENTATION,
    0,
    "project new は staging から設置し、ACTIVE 更新失敗時に project をロールバックしてください",
  );
  check(
    /post_p0\s*=\s*re\.fullmatch/.test(projectText) &&
      /post_p0\s+and\s+materials\s*==\s*["']pending["']/.test(projectText) &&
      /material_errors\s*=\s*reference_material_errors\(project\)/.test(projectText),
    "MIGRATION_MATERIAL_EVIDENCE",
    PROJECT_IMPLEMENTATION,
    0,
    "P0 後の旧 SESSION は refs/ の実在素材を検証し、materials=pending のまま移行させないでください",
  );
  check(
    /character\.casefold\(\)\s+in\s+\{["']pending["']/.test(projectText) &&
      /character-name must be finalized/.test(projectText),
    "P0_CHARACTER_FINAL",
    PROJECT_IMPLEMENTATION,
    0,
    "confirm-p0 は pending 等の character-name placeholder を拒否してください",
  );

  const metadataText = readText(METADATA_IMPLEMENTATION);
  check(
    /object_pairs_hook\s*=\s*_object_without_duplicates/.test(metadataText) &&
      /parse_constant\s*=\s*_reject_non_finite_number/.test(metadataText) &&
      /parse_float\s*=\s*_parse_finite_float/.test(metadataText) &&
      /parse_int\s*=\s*_parse_bounded_int/.test(metadataText) &&
      /math\.isfinite\(/.test(metadataText),
    "STRICT_JSON_NUMBERS",
    METADATA_IMPLEMENTATION,
    0,
    "共有 JSON parser は重複キー、非有限値、overflow、過大整数を拒否してください",
  );

  const sessionText = readText(SESSION_CONTRACT_IMPLEMENTATION);
  check(
    /values\.get\(["']materials["']\)\s*!=\s*["']received["']/.test(sessionText) &&
      /DEPRECATED_SESSION_KEYS/.test(sessionText) &&
      /SESSION contains deprecated fields/.test(sessionText) &&
      /text_mode\s*==\s*["']ai["']/.test(sessionText) &&
      /require_complete_text_evidence\(project_dir,\s*count\)/.test(sessionText),
    "STATIC_SESSION_CONTRACT",
    SESSION_CONTRACT_IMPLEMENTATION,
    0,
    "P4〜P6 の成果物コマンドは素材受領・文字モード・AI文字検査を共有 SESSION 契約で検証してください",
  );
  check(
    /report\.get\(["']gate["']\)\s*!=\s*["']P5["']/.test(sessionText) &&
      /report\.get\(["']scope["']\)\s*!=\s*["']all["']/.test(sessionText) &&
      /manifest_sha256/.test(sessionText) &&
      /sha256_file\(project_dir\s*\/\s*["']stamps["']\s*\/\s*name\)/.test(sessionText),
    "AI_TEXT_HASH_EVIDENCE",
    SESSION_CONTRACT_IMPLEMENTATION,
    0,
    "P6 の AI 文字承認は P5 全点 report と現行 manifest・stamp の SHA-256 に結び付けてください",
  );

  const publishText = readText(PUBLISH_CHECK_IMPLEMENTATION);
  check(
    /DEPRECATED_SESSION_KEYS/.test(publishText) &&
      /SESSION contains deprecated fields/.test(publishText),
    "PUBLISH_DEPRECATED_SESSION_FIELDS",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "公開前検査は v3 SESSION に残る adult・consent・rights を拒否し、migrate を案内してください",
  );
  check(
    /check_sales_area\(meta,\s*errors\)/.test(publishText) &&
      /area\s+not\s+in\s+\{["']all["']\s*,\s*["']some["']\s*,\s*["']selected["']\}/.test(publishText) &&
      /sales_countries/.test(publishText),
    "PUBLISH_SALES_AREA",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "公開前検査は販売エリア3択と国コード一覧の整合を検証してください",
  );
  check(
    /check_boolean\(meta,\s*["']ai_used["']/.test(publishText) &&
      /check_boolean\(meta,\s*["']photo_used["']/.test(publishText) &&
      /check_boolean\(meta,\s*["']premium_participation["']/.test(publishText),
    "PUBLISH_DECLARATIONS",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "公開前検査はAI・写真・プレミアムの真偽値を明示検証してください",
  );
  check(
    /^def\s+check_license_proof\s*\(/m.test(publishText) &&
      /proof\s*=\s*meta\.get\(["']license_proof["']\)/.test(publishText) &&
      /if\s+proof\s+is\s+None:\s*\n\s*return/.test(publishText) &&
      /check_license_proof\(meta,\s*project_dir,\s*errors\)/.test(publishText),
    "PUBLISH_OPTIONAL_PROOF",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "license_proof は欠落を許容し、提示された場合だけ検証してください",
  );
  check(
    /^def\s+check_ai_provenance\s*\(/m.test(publishText) &&
      /ai_used=true requires project-local meta\/ai-provenance\.md/.test(publishText) &&
      /check_ai_provenance\(\s*project_dir\s*,\s*ai_used\s*,\s*errors\s*,\s*required_ai_scopes\s*\)/.test(publishText),
    "PUBLISH_AI_PROVENANCE",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "ai_used=true ではプロジェクト内のAI来歴ファイルを必須にしてください",
  );
  check(
    /^def\s+check_project_reference\s*\(/m.test(publishText) &&
      /re\.fullmatch\(r["']https:\/\//.test(publishText) &&
      /resolved\.is_relative_to\(resolved_project\)/.test(publishText) &&
      /check_project_reference\(project_dir,\s*reference\.strip\(\)/.test(publishText),
    "PUBLISH_PROOF_REFERENCE",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "license_proof.reference はHTTPS URLまたは存在するプロジェクト内ファイルに限定してください",
  );
  check(
    /loads_no_duplicates\(/.test(publishText),
    "PUBLISH_STRICT_JSON",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "公開前検査は重複キーを拒否する JSON ローダーを使用してください",
  );

  check(
    /invisible_or_control_characters\(/.test(publishText) &&
      /def\s+check_copyright\s*\(/.test(publishText) &&
      /copyright contains text prohibited/.test(publishText),
    "PUBLISH_METADATA_TEXT_SAFETY",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "P7 metadata は不可視・制御文字と copyright の禁止語を正規化後に拒否してください",
  );
  check(
    /resolved_prompt\s*==\s*resolved/.test(publishText) &&
      /metadata fields must appear before the prompt note heading/.test(publishText) &&
      /required_ai_scopes\s*=\s*\{["']text["']\}/.test(publishText),
    "PUBLISH_PROVENANCE_BINDING",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "AI provenance は自己参照・偽の inline note を拒否し、AI文字利用時は text scope を要求してください",
  );
  check(
    /require_complete_text_evidence\(project_dir,\s*evidence_count\)/.test(publishText),
    "PUBLISH_TEXT_EVIDENCE",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "P7 でも現行ファイルに一致する P5 全点文字検査 evidence を再検証してください",
  );

  const example = objectValue(parseJson(SUBMISSION_EXAMPLE));
  check(
    example !== null &&
      ["all", "some", "selected"].includes(example.sales_area) &&
      Array.isArray(example.sales_countries),
    "SUBMISSION_SALES_AREA",
    SUBMISSION_EXAMPLE,
    0,
    "submission 例には sales_area と sales_countries が必要です",
  );
  check(
    example !== null &&
      typeof example.ai_used === "boolean" &&
      typeof example.photo_used === "boolean" &&
      typeof example.premium_participation === "boolean" &&
      typeof example.price_confirmed === "boolean" &&
      !("license_proof" in example),
    "SUBMISSION_DECLARATIONS",
    SUBMISSION_EXAMPLE,
    0,
    "submission 例には真偽値の申告3項目と price_confirmed が必要で、任意の license_proof は既定で含めないでください",
  );

  const validatorText = readText(PACK_VALIDATOR_IMPLEMENTATION);
  check(
    validatorText.includes("stamp_minimum = (80, 80)") &&
      validatorText.includes("stamp_limit = (370, 320)") &&
      validatorText.includes('ALLOWED_PNG_MODES = {"RGB", "RGBA"}') &&
      /image\.width\s*%\s*2\s+or\s+image\.height\s*%\s*2/.test(validatorText),
    "PACK_IMAGE_LIMITS",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "スタンプの最小・最大寸法、元PNGモード、偶数寸法を検証してください",
  );
  check(
    /dpi_is_at_least_72\(image_dpi\)/.test(validatorText) &&
      /getextrema\(\)\[0\]\s*!=\s*0/.test(validatorText) &&
      /if\s+bbox\s+is\s+None/.test(validatorText) &&
      /frame_count\s*!=\s*1/.test(validatorText),
    "PACK_IMAGE_CONTENT",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "PNGは静止画、72dpi以上、透明背景、可視コンテンツを検証してください",
  );
  check(
    /archived_bytes\s*=\s*archive\.read\(info\)/.test(validatorText) &&
      /archived_bytes\s*!=\s*local_bytes/.test(validatorText) &&
      /ZIP is not readable/.test(validatorText),
    "PACK_ZIP_BYTES",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "ZIPは破損を安全に報告し、各memberをローカル提出ファイルとバイト比較してください",
  );

  check(
    /has_exterior_transparent_background\(/.test(validatorText) &&
      /connected exterior transparent background/.test(validatorText),
    "PACK_TRANSPARENT_BOUNDARY",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "透明背景は内部の透明ピンホールではなく、キャンバス境界へ到達する透明領域で確認してください",
  );
  check(
    /stat\.S_IFMT\(info\.external_attr\s*>>\s*16\)/.test(validatorText) &&
      /info\.external_attr\s*&\s*0x10/.test(validatorText) &&
      /file_type\s+not\s+in\s+\{0,\s*stat\.S_IFREG\}/.test(validatorText),
    "PACK_ZIP_REGULAR_MEMBERS",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "ZIP の期待 member は Unix/DOS 属性も含めて通常ファイルだけを許可してください",
  );
  check(
    /def\s+validate_stamp_sources\s*\(/.test(validatorText) &&
      /submitted_bytes\s*!=\s*source_bytes/.test(validatorText) &&
      /validate_stamp_sources\(root\.parent,\s*root,\s*expected_names,\s*errors\)/.test(validatorText) &&
      /validate_stamp_sources\(project_dir,\s*submit_dir,\s*expected,\s*errors\)/.test(publishText),
    "PACK_REVIEWED_SOURCE_BINDING",
    PACK_VALIDATOR_IMPLEMENTATION,
    0,
    "validate-pack と P7 は submit/stampNN.png をレビュー済み stamps/stampNN.png と byte 比較してください",
  );

  const packagerText = readText(PACKAGER_IMPLEMENTATION);
  const transactionText = readText(TRANSACTION_IMPLEMENTATION);
  check(
    /tempfile\.mkdtemp\([^\n]*dir\s*=\s*outdir\)/.test(packagerText) &&
      /zip_name\.split\(["']\.["']\s*,\s*1\)\[0\]/.test(packagerText) &&
      /install_names\s*=\s*\[[^\n]*zip_name\]/.test(packagerText) &&
      /install_files_transaction\(/.test(packagerText) &&
      /except\s+ArtifactRollbackError/.test(packagerText) &&
      /except\s+BaseException\s+as\s+original_error/.test(transactionText) &&
      /backup\.replace\(destination\)/.test(transactionText),
    "PACKAGE_SAFE_INSTALL",
    PACKAGER_IMPLEMENTATION,
    0,
    "パッケージングは同一filesystemでstagingし、予約名を拒否してZIPを最後に置換してください",
  );

  const composeText = readText(COMPOSE_IMPLEMENTATION);
  check(
    /^def\s+text_layer_output\s*\(/m.test(composeText) &&
      /text_mode\s*==\s*["']font["']/.test(composeText) &&
      /requires --text-layer-dir/.test(composeText) &&
      /must not use --text-layer-dir/.test(composeText) &&
      /checked_output_directories\(/.test(composeText) &&
      /args\.text_layer_dir/.test(composeText),
    "COMPOSE_TEXT_LAYER_MODE",
    COMPOSE_IMPLEMENTATION,
    0,
    "文字レイヤー出力はfontで必須、ai/noneで禁止してください",
  );

  const facadeText = readText(FACADE_FILE);
  check(
    /ARTIFACT_COMMANDS\s*=/.test(facadeText) &&
      /\.line-stamp-projects\.lock/.test(facadeText) &&
      /\.line-stamp-project\.lock/.test(facadeText) &&
      /FACADE_PROJECT_ENV/.test(facadeText) &&
      /with\s+exclusive_lock\(/.test(facadeText) &&
      /result\s*=\s*entrypoint\(\)/.test(facadeText),
    "COMMON_ARTIFACT_LOCK",
    FACADE_FILE,
    0,
    "公開CLIはactive project単位の共通lockで全artifact commandを囲んでください",
  );
  check(
    /install_files_transaction\(staging, installs\)/.test(composeText) &&
      /canonical_character_dir\s*=\s*base\s*\/\s*["']characters["']/.test(composeText) &&
      /canonical_character\s*=\s*canonical_character_dir\s*\/\s*f["']stamp\{index:02d\}\.png/.test(composeText) &&
      /character_path\s*!=\s*canonical_character\.resolve\(\)/.test(composeText) &&
      /except\s+ArtifactRollbackError/.test(composeText),
    "COMPOSE_ISOLATED_TRANSACTION",
    COMPOSE_IMPLEMENTATION,
    0,
    "composeは前処理済みcharacters入力だけをstagingからrollback可能に設置してください",
  );

  const contactText = readText(CONTACT_SHEET_IMPLEMENTATION);
  check(
    /REVIEW_NAME_RE/.test(contactText) &&
      /^def\s+write_review_pair\s*\(/m.test(contactText) &&
      /path\.open\(["']xb["']\)/.test(contactText) &&
      /with\s+exclusive_lock\(/.test(contactText) &&
      /write_review_pair\(output,\s*payload,\s*evidence_payload\)/.test(contactText) &&
      /same project's review/.test(contactText) &&
      /load_static_session\(project_dir,\s*\{["']P5["']\}\)/.test(contactText),
    "CONTACT_SHEET_APPEND_ONLY",
    CONTACT_SHEET_IMPLEMENTATION,
    0,
    "確認一覧は同一projectの版付き未使用名へ排他的に作成してください",
  );

  const verifyText = readText(VERIFY_TEXT_IMPLEMENTATION);
  check(
    /write_report_pair\(/.test(verifyText) &&
      /path\.open\(["']xb["']\)/.test(verifyText) &&
      /["']--review-dir["']\s*,\s*required=True/.test(verifyText) &&
      /return\s+1\s+if\s+mismatches\s+or\s+near\s+else\s+0/.test(verifyText) &&
      /load_static_session\(project_dir,\s*\{["']P4["']\s*,\s*["']P5["']\}\)/.test(verifyText) &&
      /manifest_sha256/.test(verifyText) &&
      /["']scope["']\s*:\s*scope/.test(verifyText),
    "VERIFY_TEXT_EVIDENCE",
    VERIFY_TEXT_IMPLEMENTATION,
    0,
    "AI文字検査はnearを成功扱いせず、同一projectへ版付き証跡を排他的に保存してください",
  );

  check(
    /PROVENANCE_REQUIRED_FIELDS/.test(publishText) &&
      /generated_at must be an ISO date/.test(publishText) &&
      /prompt_reference file must not be empty/.test(publishText),
    "PUBLISH_AI_PROVENANCE",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "AI provenanceは必須フィールド、日付、非空のprompt参照を検査してください",
  );
  check(
    /price_confirmed/.test(publishText) &&
      /price_jpy\s*<=\s*0/.test(publishText) &&
      /validate_zip\(zip_path, submit_dir/.test(publishText),
    "PUBLISH_CURRENT_ARTIFACTS",
    PUBLISH_CHECK_IMPLEMENTATION,
    0,
    "P7は価格確認と現在のsubmit/ZIPのバイト一致を再検査してください",
  );

  check(
    /def\s+valid_slug\s*\(/.test(projectText) &&
      /SLUG_RE\.fullmatch\(slug\)/.test(projectText) &&
      /WINDOWS_RESERVED_NAMES/.test(projectText) &&
      /entry\.stat\(\)\.st_size\s*<=\s*0/.test(projectText),
    "PORTABLE_PROJECT_INTAKE",
    PROJECT_IMPLEMENTATION,
    0,
    "project slugはportableに完全一致検査し、P0素材は非空・読取可能にしてください",
  );
}


function validateDependencyBoundaries(files) {
  const vendorPattern = /\.(claude|codex|cursor)(?=[/\\]|\b)/g;
  const commonFiles = files.filter((entry) =>
    (entry.startsWith(".agents/") || entry.startsWith("scripts/")) &&
    entry !== "scripts/check_structure.mjs" &&
    TEXT_EXTENSIONS.has(path.extname(entry)));
  for (const file of commonFiles) {
    const lines = readText(file).split(/\r?\n/);
    for (const [index, line] of lines.entries()) {
      vendorPattern.lastIndex = 0;
      if (vendorPattern.test(line)) {
        addError("COMMON_VENDOR_DEP", file, index + 1, "共通層からベンダー固有層を参照できません");
      }
    }
  }
  for (const vendor of VENDORS) {
    for (const file of files.filter((entry) => entry.startsWith(`.${vendor}/`) && TEXT_EXTENSIONS.has(path.extname(entry)))) {
      const text = readText(file);
      for (const other of VENDORS.filter((entry) => entry !== vendor)) {
        const pattern = new RegExp(`\\.${other}(?=[/\\\\]|\\b)`);
        if (pattern.test(text)) {
          addError("CROSS_VENDOR_DEP", file, 0, `${vendor} adapter から ${other} adapter を参照できません`);
        }
      }
    }
  }
}


function collectHookReferences(text) {
  const references = new Set();
  const pattern = /scripts[\\/]hooks[\\/][A-Za-z0-9_.-]+\.mjs/g;
  for (const match of text.matchAll(pattern)) references.add(match[0].replaceAll("\\", "/"));
  return references;
}


function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}


function nestedHookCommands(config, event, file) {
  const root = objectValue(config);
  const hooks = objectValue(root?.hooks);
  const groups = hooks?.[event];
  if (!check(Array.isArray(groups), "HOOK_EVENT", file, 0, `hooks.${event} は配列である必要があります`)) return [];
  const commands = [];
  for (const [index, group] of groups.entries()) {
    const entries = objectValue(group)?.hooks;
    if (!Array.isArray(entries)) {
      addError("HOOK_GROUP", file, 0, `hooks.${event}[${index}].hooks は配列である必要があります`);
      continue;
    }
    for (const entry of entries) {
      if (objectValue(entry)) commands.push(entry);
      else addError("HOOK_COMMAND", file, 0, `hooks.${event}[${index}] に不正な hook があります`);
    }
  }
  return commands;
}


function commandInvokes(command, script, surface, mode = null) {
  if (typeof command !== "string") return false;
  const normalized = command.replaceAll("\\", "/");
  const scriptIndex = normalized.indexOf(script);
  if (scriptIndex < 0) return false;
  if (!/\bnode(?:\.exe)?\b/i.test(normalized.slice(0, scriptIndex))) return false;
  const tail = normalized.slice(scriptIndex + script.length);
  const tokens = tail.match(/[A-Za-z0-9_-]+/g) ?? [];
  if (tokens[0] !== surface) return false;
  return mode === null || tokens[1] === mode;
}


function validateClaudeHookSemantics(config, file) {
  const expectations = [
    ["SessionStart", "scripts/hooks/project_context.mjs", "session"],
    ["PreToolUse", "scripts/hooks/pre_tool_use.mjs", null],
    ["UserPromptSubmit", "scripts/hooks/project_context.mjs", "prompt"],
  ];
  for (const [event, script, mode] of expectations) {
    const commands = nestedHookCommands(config, event, file);
    const matching = commands.find((entry) =>
      entry.type === "command" && commandInvokes(entry.command, script, "claude", mode));
    check(
      Boolean(matching),
      "HOOK_CLAUDE_SEMANTICS",
      file,
      0,
      `${event} に共通 ${path.posix.basename(script)} の claude${mode ? ` ${mode}` : ""} 呼び出しが必要です`,
    );
  }
}


function validateCodexHookSemantics(config, file) {
  const commands = nestedHookCommands(config, "PreToolUse", file);
  const matching = commands.find((entry) =>
    entry.type === "command" &&
    commandInvokes(entry.command, "scripts/hooks/pre_tool_use.mjs", "codex") &&
    commandInvokes(entry.commandWindows, "scripts/hooks/pre_tool_use.mjs", "codex"));
  check(
    Boolean(matching),
    "HOOK_CODEX_SEMANTICS",
    file,
    0,
    "PreToolUse の同一 hook に command と commandWindows の共通 pre_tool_use.mjs codex 呼び出しが必要です",
  );
}


function validateCursorHookSemantics(config, file) {
  const root = objectValue(config);
  check(root?.version === 1, "HOOK_CURSOR_VERSION", file, 0, "Cursor hook config は version: 1 が必要です");
  const hooks = objectValue(root?.hooks);
  const commands = hooks?.preToolUse;
  if (!check(Array.isArray(commands), "HOOK_EVENT", file, 0, "hooks.preToolUse は配列である必要があります")) return;
  const matching = commands.find((entry) =>
    objectValue(entry) &&
    entry.failClosed === true &&
    commandInvokes(entry.command, "scripts/hooks/pre_tool_use.mjs", "cursor"));
  check(
    Boolean(matching),
    "HOOK_CURSOR_SEMANTICS",
    file,
    0,
    "preToolUse に failClosed=true の共通 pre_tool_use.mjs cursor 呼び出しが必要です",
  );
}


function validateProjectContextSafety() {
  const contextFile = "scripts/hooks/project_context.mjs";
  const selfTestFile = "scripts/hooks/self_test.mjs";
  if (!fs.existsSync(absolute(contextFile)) || !fs.existsSync(absolute(selfTestFile))) return;
  const context = readText(contextFile);
  const selfTest = readText(selfTestFile);
  check(
    context.includes("const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,39}$/;") &&
      /SLUG_PATTERN\.test\(slug\)/.test(context),
    "HOOK_ACTIVE_SLUG",
    contextFile,
    0,
    "ACTIVE は限定された slug 形式を検証してから利用してください",
  );
  check(
    /fs\.lstatSync\(activeFile\)\.isSymbolicLink\(\)/.test(context) &&
      /fs\.lstatSync\(project\)\.isSymbolicLink\(\)/.test(context) &&
      /fs\.lstatSync\(file\)\.isSymbolicLink\(\)/.test(context),
    "HOOK_ACTIVE_SYMLINK",
    contextFile,
    0,
    "ACTIVE、project、SESSION.md のシンボリックリンクを辿らないでください",
  );
  check(
    /path\.resolve\(projects,\s*slug\)/.test(context) &&
      /!isWithin\(projects,\s*project\)/.test(context) &&
      /fs\.realpathSync\(file\)/.test(context) &&
      /isWithin\(project,\s*realFile\)/.test(context),
    "HOOK_ACTIVE_CONTAINMENT",
    contextFile,
    0,
    "ACTIVE から解決する project/SESSION.md が projects 内に留まることを確認してください",
  );
  check(
    !/CLAUDE_PROJECT_DIR|CODEX_HOME|CURSOR_PROJECT_DIR/i.test(context) &&
      /process\.argv\[4\]\s*\|\|\s*payload\?\.cwd\s*\|\|\s*process\.cwd\(\)/.test(context),
    "HOOK_CONTEXT_VENDOR_NEUTRAL_ROOT",
    contextFile,
    0,
    "共通context hookは製品固有環境変数を読まず、adapter引数またはpayload cwdを使ってください",
  );
  check(
    /if\s*\(active\.invalid\)\s*return\s*["'][^"']*ACTIVE[^"']*slug[^"']*["']/.test(context) &&
      /active\.invalid\s*\?\s*["']invalid["']/.test(context),
    "HOOK_ACTIVE_INVALID_CONTEXT",
    contextFile,
    0,
    "不正な ACTIVE は値を表示せず invalid として扱ってください",
  );
  check(
    selfTest.includes('"../../sensitive\\n"') &&
      /const\s+invalidActive\s*=\s*spawnSync\([\s\S]*?\[contextHookPath,\s*["']claude["'],\s*["']prompt["']\]/.test(selfTest) &&
      /assert\.doesNotMatch\(\s*invalidActive\.stdout\s*,\s*\/sensitive\/\s*\)/.test(selfTest),
    "HOOK_ACTIVE_REGRESSION_TEST",
    selfTestFile,
    0,
    "自己テストは traversal を含む不正 ACTIVE を拒否し、その値を出力しないことを検証してください",
  );
}


function validateHooks() {
  for (const file of COMMON_HOOKS) {
    check(fs.existsSync(absolute(file)), "HOOK_SCRIPT", file, 0, "共通 hook script がありません");
  }
  const policyFile = "scripts/hooks/policy.mjs";
  const policyText = readText(policyFile);
  const policySelfTest = readText("scripts/hooks/self_test.mjs");
  check(
    policyText.includes("COMMAND_DENY_RULES") &&
      policyText.includes("git\\s+push") &&
      policyText.includes("git\\s+(?:reset\\s+--hard|clean\\s+-[a-z]*f)"),
    "HOOK_DESTRUCTIVE_POLICY",
    policyFile,
    0,
    "共通hookは再帰削除、force push、reset/cleanを防止してください",
  );
  check(
    policyText.includes("collectPatchPaths") &&
      policyText.includes('basename === "settings.local.json"') &&
      policySelfTest.includes("envShellWriteBlock") &&
      policySelfTest.includes("envPatchBlock"),
    "HOOK_SENSITIVE_POLICY",
    policyFile,
    0,
    "共通hookは個人設定の読み書きとpatch経由の変更を検査してください",
  );
  check(
    policyText.includes("\\u540c\\u610f") &&
      policySelfTest.includes("consentBlock") &&
      policySelfTest.includes("credentialBlock"),
    "HOOK_IRREVERSIBLE_POLICY",
    policyFile,
    0,
    "共通hookは法的同意・不可逆操作・認証情報入力のfixtureを維持してください",
  );
  const allReferences = new Set();
  for (const [config, surface] of HOOK_CONFIGS) {
    if (!check(fs.existsSync(absolute(config)), "HOOK_CONFIG", config, 0, "hook config がありません")) continue;
    const parsed = parseJson(config);
    const text = readText(config);
    const references = collectHookReferences(text);
    check(references.size > 0, "HOOK_COMMON_REF", config, 0, "scripts/hooks/*.mjs を参照していません");
    check(references.has("scripts/hooks/pre_tool_use.mjs"), "HOOK_POLICY_REF", config, 0, "共通 pre_tool_use.mjs を参照していません");
    check(/\bnode(?:\.exe)?\b/i.test(text), "HOOK_RUNTIME", config, 0, "Node で共通 hook を起動する設定が必要です");
    check(new RegExp(`(?:^|[\\s"'])${surface}(?:[\\s"']|$)`, "m").test(text), "HOOK_SURFACE", config, 0, `hook に surface '${surface}' を渡してください`);
    for (const reference of references) {
      allReferences.add(reference);
      check(fs.existsSync(absolute(reference)), "HOOK_REF_MISSING", config, 0, `hook script がありません: ${reference}`);
    }
    if (parsed) {
      if (surface === "claude") validateClaudeHookSemantics(parsed, config);
      else if (surface === "codex") validateCodexHookSemantics(parsed, config);
      else validateCursorHookSemantics(parsed, config);
    }
  }
  check(allReferences.has("scripts/hooks/project_context.mjs"), "HOOK_CONTEXT_REF", "scripts/hooks/project_context.mjs", 0, "少なくとも1つの adapter から project_context.mjs を参照してください");
  for (const [file, sharedHook] of LEGACY_CLAUDE_HOOKS) {
    if (!check(fs.existsSync(absolute(file)), "HOOK_LEGACY_WRAPPER", file, 0, "既存Claude hook互換ラッパーがありません")) continue;
    const text = readText(file);
    check(
      text.includes(path.posix.basename(sharedHook)) &&
        (/scripts[\\/]hooks/.test(text) || /["']scripts["']\s*\/\s*["']hooks["']/.test(text)) &&
        /\bnode\b/.test(text) &&
        /\bclaude\b/.test(text),
      "HOOK_LEGACY_DELEGATION",
      file,
      0,
      `互換ラッパーは共通 ${sharedHook} に委譲してください`,
    );
    check(
      !/(?:rm\s+-rf|git\s+push\s+--force|審査をリクエスト|同意します|リリース)/i.test(text),
      "HOOK_LEGACY_POLICY_COPY",
      file,
      0,
      "互換ラッパーへ安全ポリシーを複製せず、共通hookだけに保持してください",
    );
    if (file.endsWith(".py")) {
      check(
        /raise\s+SystemExit\(1\)\s+from\s+exc/.test(text) &&
          /raise\s+SystemExit\(result\.returncode\)/.test(text),
        "HOOK_LEGACY_EXIT",
        file,
        0,
        "Python互換ラッパーは起動失敗と共通hookの終了コードを伝播してください",
      );
    }
  }
  if (check(fs.existsSync(absolute(LEGACY_CLAUDE_RUNNER)), "HOOK_LEGACY_RUNNER", LEGACY_CLAUDE_RUNNER, 0, "Python選択用のClaude互換ランナーがありません")) {
    const runner = readText(LEGACY_CLAUDE_RUNNER);
    const claudeSettings = readText(".claude/settings.json");
    check(
      /["']python3["']/.test(runner) && /["']python["']/.test(runner) && /["']py["']/.test(runner) &&
        runner.includes('"scripts"') && runner.includes('"hooks"') && runner.includes('"pre_tool_use.mjs"'),
      "HOOK_LEGACY_RUNTIME_FALLBACK",
      LEGACY_CLAUDE_RUNNER,
      0,
      "互換ランナーは利用可能なPythonを選び、なければ共通Node hookへフォールバックしてください",
    );
    check(
      /run-python-wrapper\.mjs\\"\s+block-dangerous/.test(claudeSettings) &&
        /run-python-wrapper\.mjs\\"\s+guard-submit/.test(claudeSettings),
      "HOOK_LEGACY_RUNNER_CONFIG",
      ".claude/settings.json",
      0,
      "Claude settings は両Python互換ラッパーをポータブルなNodeランナー経由で起動してください",
    );
  }
  validateProjectContextSafety();
}


function validateRootAdapter() {
  const file = "CLAUDE.md";
  if (!check(fs.existsSync(absolute(file)), "CLAUDE_ADAPTER", file, 0, "Claude adapter がありません")) return;
  const text = readText(file);
  check(/^@AGENTS\.md\s*$/m.test(text), "CLAUDE_IMPORT", file, 0, "独立した行で @AGENTS.md を import してください");
  for (const adapter of [file, ".claude/commands/line-stamp-generator.md", ".claude/commands/plan.md"]) {
    if (!check(fs.existsSync(absolute(adapter)), "CLAUDE_CHOICE_ADAPTER", adapter, 0, "Claude 選択アダプタがありません")) continue;
    const adapterText = readText(adapter);
    check(
      adapterText.includes("AskUserQuestion") &&
        /最大3問/.test(adapterText) &&
        /推奨案を先頭/.test(adapterText) &&
        /相互排他的/.test(adapterText) &&
        /利用できない(?:環境|場合)[^\n]*番号付き選択肢/.test(adapterText),
      "CLAUDE_STRUCTURED_CHOICES",
      adapter,
      0,
      "Claude の有限選択は AskUserQuestion、最大3問、推奨先頭、相互排他、利用不可時だけ番号付きフォールバックを明記してください",
    );
  }
  for (const shared of [
    "AGENTS.md",
    ".agents/skills/line-stamp-generator/SKILL.md",
    ".agents/skills/line-stamp-generator/references/dialogue.md",
  ]) {
    check(
      !readText(shared).includes("AskUserQuestion"),
      "SHARED_VENDOR_NEUTRAL_CHOICES",
      shared,
      0,
      "共通層では製品固有の選択ツール名を使わず、構造化選択 UI と表現してください",
    );
  }

  for (const policyFile of [
    "AGENTS.md",
    "README.md",
    ".agents/skills/line-stamp-generator/SKILL.md",
    ".agents/skills/line-stamp-generator/references/dialogue.md",
    ".agents/skills/line-stamp-generator/references/security-and-rights.md",
    ".agents/skills/line-stamp-generator/references/character-base.md",
    ".agents/skills/line-stamp-generator/references/line-specs.md",
  ]) {
    const policyText = readText(policyFile);
    check(
      policyText.includes("歴史上の人物") && policyText.includes("確認対象外"),
      "HISTORICAL_FIGURE_RIGHTS_EXCEPTION",
      policyFile,
      0,
      "歴史上の人物は著作権・肖像権等の確認対象外であることを明記してください",
    );
  }
  check(
    readText(".agents/skills/line-stamp-generator/references/line-specs.md")
      .includes("P0〜P8 で確認や証明要求を追加しない") &&
      readText(".agents/skills/line-stamp-generator/references/line-specs.md")
        .includes("LINE 公式審査の免除を意味しない") &&
      readText(".agents/skills/line-stamp-generator/references/line-specs.md")
        .includes("表示内容をユーザーへ報告して停止する"),
    "HISTORICAL_FIGURE_OFFICIAL_REVIEW",
    ".agents/skills/line-stamp-generator/references/line-specs.md",
    0,
    "歴史上の人物の内部チェックをP8まで除外し、LINE側の追加要求はユーザーへ報告して停止してください",
  );
}


function shouldScanDocumentation(file) {
  if (file === "tasks/todo.md" || file.startsWith("tasks/history/")) return false;
  return file.endsWith(".md") || file.endsWith(".mdc");
}


function validateFormatsAndReferences(files) {
  for (const file of files) {
    if (file.endsWith(".json") || file.endsWith(".json.example")) parseJson(file);
    if (file.endsWith(".toml")) parseBasicToml(file);
    if (file.endsWith(".yaml") || file.endsWith(".yml")) validateBasicYaml(file);
    if (shouldScanDocumentation(file)) {
      validateMarkdownSyntax(file);
      validateMarkdownReferences(file);
    }
  }
}


function main() {
  const files = walk();
  validateFormatsAndReferences(files);
  validateSkills();
  validateRolesAndAdapters();
  validateRootAdapter();
  validateFacade(files);
  validatePublicCliPolicy(files);
  validateProjectDocs();
  validateSchemaVersionPolicy();
  validateWorkflowContracts();
  validateDependencyBoundaries(files);
  validateHooks();

  diagnostics.sort((left, right) =>
    left.file.localeCompare(right.file, "en") ||
    left.line - right.line ||
    left.code.localeCompare(right.code, "en") ||
    left.message.localeCompare(right.message, "ja"));
  if (diagnostics.length) {
    for (const item of diagnostics) {
      const location = item.line ? `${item.file}:${item.line}` : item.file;
      process.stdout.write(`ERROR [${item.code}] ${location} - ${item.message}\n`);
    }
    process.stdout.write(`FAIL check-structure: ${diagnostics.length} error(s), ${checks} checks\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write(`PASS check-structure: ${checks} checks\n`);
  }
}


try {
  main();
} catch (error) {
  process.stdout.write(`ERROR [INTERNAL] scripts/check_structure.mjs - ${error.stack ?? error.message}\n`);
  process.stdout.write("FAIL check-structure: internal error\n");
  process.exitCode = 2;
}
