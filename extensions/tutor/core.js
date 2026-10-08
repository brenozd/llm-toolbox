// Pure logic for the tutor extension. No pi imports, so it can be tested with node --test.
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

export const TUTOR_DIR = ".tutor";
export const POLL_MS = 30_000;
export const MIN_CHANGED_LINES = 3;
export const MIN_REVIEW_INTERVAL_MS = 5 * 60_000;
export const MAX_PROFILE_PROMPT_CHARS = 8000;
export const MAX_PROFILE_SAVE_CHARS = 20_000;
export const MAX_LADDER = 6;
export const DEFAULT_STATE = { ladderMax: 2, watch: true, lastHash: null, manifestHash: null, lang: null };

// Files whose change means the profile's view of the project may be stale.
const MANIFESTS = [
  "AGENTS.md", "CLAUDE.md", "Cargo.toml", "package.json", "pyproject.toml", "requirements.txt",
  "go.mod", "CMakeLists.txt", "build.zig.zon", "pom.xml", "build.gradle", "build.gradle.kts",
  "Gemfile", "composer.json", "mix.exs",
];

const sha1 = (s) => createHash("sha1").update(s).digest("hex");

// -- Commands ---------------------------------------------------------------

export function parseCommand(text) {
  const [head = "", ...rest] = String(text || "").trim().split(/\s+/);
  const arg = rest.join(" ");
  const cmd = head.toLowerCase();

  switch (cmd) {
    case "": return { type: "toggle" };
    case "on": case "off": case "status": case "refresh": case "profile": return { type: cmd };
    case "review": return { type: "review", arg };
    case "lang": return arg ? { type: "lang", lang: arg } : { type: "invalid", reason: "lang needs a value" };
    case "ladder": {
      const n = Number(arg);
      return arg && Number.isInteger(n) && n >= 0 && n <= MAX_LADDER
        ? { type: "ladder", rung: n }
        : { type: "invalid", reason: `ladder takes an integer 0-${MAX_LADDER}` };
    }
    case "watch":
      return arg === "on" || arg === "off"
        ? { type: "watch", value: arg === "on" }
        : { type: "invalid", reason: "watch takes on|off" };
    default: return { type: "invalid", reason: `unknown command: ${cmd}` };
  }
}

// Last "tutor-mode" session entry wins; default OFF.
export function resolveOn(entries) {
  if (!Array.isArray(entries)) return false;
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const e = entries[i];
    if (e?.type === "custom" && e?.customType === "tutor-mode") return Boolean(e?.data?.on);
  }
  return false;
}

// -- Prompt -----------------------------------------------------------------

export function stripFrontmatter(md) {
  return md.replace(/^---\n[\s\S]*?\n---\n?/, "");
}

// The "## Contract" section of SKILL.md is the single source for the per-turn prompt.
export function extractContract(md) {
  const body = stripFrontmatter(md);
  const start = body.search(/^## Contract\s*$/m);
  if (start === -1) return "";
  const rest = body.slice(start).replace(/^## Contract\s*\n/, "");
  const end = rest.search(/^## /m);
  return (end === -1 ? rest : rest.slice(0, end)).replace(/<!--[\s\S]*?-->/g, "").trim();
}

export function buildPromptSection({ contract, profile, state, manifestChanged }) {
  const lines = [
    "# Tutor mode: ON",
    contract,
    "",
    `Estado: ladderMax=${state.ladderMax}${state.lang ? `, lang=${state.lang}` : ""}`,
    "Ferramentas edit/write estão bloqueadas. Instrua em texto; o usuário escreve o código.",
  ];
  if (profile) {
    const clipped = profile.length > MAX_PROFILE_PROMPT_CHARS
      ? `${profile.slice(0, MAX_PROFILE_PROMPT_CHARS)}\n[perfil truncado]`
      : profile;
    lines.push("", "## Perfil do projeto (.tutor/profile.md)", clipped);
    if (manifestChanged) {
      lines.push("", "Manifesto/AGENTS.md mudou desde o perfil. Na próxima oportunidade pesquise só o delta e salve com tutor_save_profile.");
    }
  } else {
    lines.push("", "Sem perfil do projeto (.tutor/profile.md). Rode o modo `setup` antes de revisar.");
  }
  return lines.join("\n");
}

// -- Persistence (.tutor/) --------------------------------------------------

export const tutorPath = (cwd, ...p) => path.join(cwd, TUTOR_DIR, ...p);

// A "*" gitignore inside the dir ignores the whole dir, itself included: no edit to the project's own ignore files.
export function ensureTutorDir(cwd) {
  fs.mkdirSync(tutorPath(cwd), { recursive: true });
  const gi = tutorPath(cwd, ".gitignore");
  if (!fs.existsSync(gi)) fs.writeFileSync(gi, "*\n");
}

export function loadState(cwd) {
  try {
    return { ...DEFAULT_STATE, ...JSON.parse(fs.readFileSync(tutorPath(cwd, "state.json"), "utf8")) };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

export function saveState(cwd, state) {
  ensureTutorDir(cwd);
  fs.writeFileSync(tutorPath(cwd, "state.json"), `${JSON.stringify(state, null, 2)}\n`);
}

export function loadProfile(cwd) {
  try {
    return fs.readFileSync(tutorPath(cwd, "profile.md"), "utf8");
  } catch {
    return null;
  }
}

export function saveProfile(cwd, content) {
  if (typeof content !== "string" || !content.trim()) throw new Error("profile content is empty");
  if (content.length > MAX_PROFILE_SAVE_CHARS) throw new Error(`profile too large (max ${MAX_PROFILE_SAVE_CHARS} chars)`);
  ensureTutorDir(cwd);
  fs.writeFileSync(tutorPath(cwd, "profile.md"), content.endsWith("\n") ? content : `${content}\n`);
}

export function manifestHash(cwd) {
  const parts = [];
  for (const name of MANIFESTS) {
    try {
      parts.push(name, fs.readFileSync(path.join(cwd, name), "utf8"));
    } catch { /* manifest absent */ }
  }
  return parts.length ? sha1(parts.join("\0")) : null;
}

// -- Edit/write guard -------------------------------------------------------

// shortcut: only the edit/write tools are blocked; bash redirects can still write, the contract forbids it.
export function isBlockedTool(toolName) {
  return toolName === "edit" || toolName === "write";
}

// -- Watcher ----------------------------------------------------------------

export function countChangedLines(diff) {
  return diff.split("\n").filter((l) => /^[+-](?![+-]{2} )/.test(l)).length;
}

const defaultRun = (cmd, args, opts) => execFileP(cmd, args, { maxBuffer: 8 * 1024 * 1024, ...opts });

// Hash of "what the working tree looks like vs HEAD". null when not a git repo, or no commits yet.
// shortcut: untracked files are hashed by size+mtime (not content) and count as MIN_CHANGED_LINES each.
export async function gitSnapshot(cwd, run = defaultRun) {
  try {
    const { stdout: diff } = await run("git", ["diff", "HEAD", "--no-color"], { cwd });
    const { stdout: other } = await run("git", ["ls-files", "--others", "--exclude-standard"], { cwd });
    const untracked = other.split("\n").filter(Boolean).slice(0, 200);
    const parts = [diff];
    for (const f of untracked) {
      try {
        const s = fs.statSync(path.join(cwd, f));
        parts.push(`${f}:${s.size}:${s.mtimeMs}`);
      } catch { /* vanished between ls-files and stat */ }
    }
    return { hash: sha1(parts.join("\0")), changed: countChangedLines(diff) + (parts.length - 1) * MIN_CHANGED_LINES };
  } catch {
    return null;
  }
}

// Review only when the tree changed since the last review, stayed identical across two polls
// (the user stopped typing), is big enough, and the last review was not too recent.
export function decideReview({ hash, prevHash, lastHash, changed, now, lastReviewAt }) {
  if (hash === lastHash) return { review: false, prevHash: hash };
  if (hash !== prevHash) return { review: false, prevHash: hash };
  if (changed < MIN_CHANGED_LINES) return { review: false, prevHash: hash };
  if (now - lastReviewAt < MIN_REVIEW_INTERVAL_MS) return { review: false, prevHash: hash };
  return { review: true, prevHash: hash };
}
