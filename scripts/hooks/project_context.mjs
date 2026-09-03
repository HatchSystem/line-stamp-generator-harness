import fs from "node:fs";
import path from "node:path";

const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,39}$/;
const WINDOWS_RESERVED_NAMES = new Set([
  "ACTIVE",
  "CON", "PRN", "AUX", "NUL",
  ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`),
]);


function validSlug(slug) {
  return SLUG_PATTERN.test(slug) && !WINDOWS_RESERVED_NAMES.has(slug.toUpperCase());
}


async function readStdin() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  return input;
}


function parseSession(file) {
  const values = {};
  if (!fs.existsSync(file)) return values;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*-\s*([a-z_]+)\s*:\s*(.*)$/);
    if (match) values[match[1]] = match[2].trim();
  }
  return values;
}


function isWithin(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}


function readActive(projects) {
  const activeFile = path.join(projects, "ACTIVE");
  if (!fs.existsSync(activeFile) || fs.lstatSync(activeFile).isSymbolicLink()) {
    return { slug: "", invalid: false };
  }
  const slug = fs.readFileSync(activeFile, "utf8").trim();
  return validSlug(slug)
    ? { slug, invalid: false }
    : { slug: "", invalid: Boolean(slug) };
}


function safeSession(projects, slug) {
  if (!validSlug(slug)) return {};
  const project = path.resolve(projects, slug);
  if (!isWithin(projects, project) || !fs.existsSync(project)) return {};
  if (fs.lstatSync(project).isSymbolicLink()) return {};
  const file = path.join(project, "SESSION.md");
  if (!fs.existsSync(file) || fs.lstatSync(file).isSymbolicLink()) return {};
  const realFile = fs.realpathSync(file);
  return isWithin(project, realFile) ? parseSession(realFile) : {};
}


function resolveRoot(payload) {
  const candidate = process.argv[4] || payload?.cwd || process.cwd();
  return path.resolve(candidate);
}


function sessionContext(root) {
  const projects = path.join(root, "projects");
  const active = readActive(projects);
  const rows = [];
  if (fs.existsSync(projects)) {
    for (const entry of fs.readdirSync(projects, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      if (!validSlug(entry.name)) continue;
      const values = safeSession(projects, entry.name);
      if (Object.keys(values).length) {
        rows.push(`${entry.name}: gate=${values.gate ?? "?"}, count=${values.count ?? "?"}, submission=${values.submission ?? "?"}`);
      }
    }
  }
  const listing = rows.length ? rows.sort().join("; ") : "none";
  const activeLabel = active.invalid ? "invalid" : (active.slug || "none");
  return `[project-context] ACTIVE=${activeLabel}; projects=${listing}. 制作依頼ではプロジェクトを確定してから現在ゲートだけを進める。`;
}


function promptContext(root) {
  const projects = path.join(root, "projects");
  const active = readActive(projects);
  if (active.invalid) return "[gate-reminder] ACTIVE の slug が不正です。プロジェクトを選び直してください。";
  if (!active.slug) return "";
  const values = safeSession(projects, active.slug);
  if (!values.gate) return `[gate-reminder] ACTIVE=${active.slug} ですが SESSION.md の gate を確認できません。`;
  return `[gate-reminder] project=${active.slug} gate=${values.gate} submission=${values.submission ?? "?"}. 現在ゲートのユーザー承認前に次へ進まない。`;
}


async function main() {
  const surface = process.argv[2];
  const mode = process.argv[3];
  let payload = {};
  const input = await readStdin();
  if (input.trim()) {
    try {
      payload = JSON.parse(input);
    } catch {
      payload = {};
    }
  }
  const root = resolveRoot(payload);
  const context = mode === "prompt" ? promptContext(root) : sessionContext(root);
  if (!context) return;
  if (surface === "cursor") {
    process.stdout.write(`${JSON.stringify({ additional_context: context })}\n`);
  } else {
    process.stdout.write(`${context}\n`);
  }
}


main().catch((error) => {
  process.stderr.write(`[project-context] ${error.message}\n`);
  process.exitCode = 0;
});
