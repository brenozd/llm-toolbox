import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  MIN_REVIEW_INTERVAL_MS, buildPromptSection, countChangedLines, decideReview, ensureTutorDir, extractContract,
  gitSnapshot, isBlockedTool, loadState, manifestHash, parseCommand, resolveOn, saveProfile, saveState, tutorPath,
} from "../core.js";

const SKILL = fileURLToPath(new URL("../../../skills/code-tutor/SKILL.md", import.meta.url));
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "tutor-"));
const git = (cwd, ...args) => execFileSync("git", args, { cwd, encoding: "utf8" });

function repo() {
  const dir = tmp();
  git(dir, "init", "-q");
  git(dir, "config", "user.email", "t@t");
  git(dir, "config", "user.name", "t");
  fs.writeFileSync(path.join(dir, "a.txt"), "one\n");
  git(dir, "add", ".");
  git(dir, "commit", "-qm", "init");
  return dir;
}

test("parseCommand", () => {
  assert.deepEqual(parseCommand(""), { type: "toggle" });
  assert.deepEqual(parseCommand(" ON "), { type: "on" });
  assert.deepEqual(parseCommand("review src/main.rs"), { type: "review", arg: "src/main.rs" });
  assert.deepEqual(parseCommand("ladder 3"), { type: "ladder", rung: 3 });
  assert.equal(parseCommand("ladder 9").type, "invalid");
  assert.equal(parseCommand("ladder x").type, "invalid");
  assert.deepEqual(parseCommand("watch off"), { type: "watch", value: false });
  assert.equal(parseCommand("watch maybe").type, "invalid");
  assert.deepEqual(parseCommand("lang rust"), { type: "lang", lang: "rust" });
  assert.equal(parseCommand("lang").type, "invalid");
  assert.equal(parseCommand("nope").type, "invalid");
});

test("extractContract reads only the Contract section of the real SKILL.md", () => {
  const c = extractContract(fs.readFileSync(SKILL, "utf8"));
  assert.match(c, /NEVER edit, create or delete project files/);
  assert.doesNotMatch(c, /## Workflow/);
  assert.doesNotMatch(c, /<!--/);
  assert.equal(extractContract("# no contract here"), "");
});

test("resolveOn: last entry wins, default off", () => {
  assert.equal(resolveOn([]), false);
  assert.equal(resolveOn(undefined), false);
  const e = (on) => ({ type: "custom", customType: "tutor-mode", data: { on } });
  assert.equal(resolveOn([e(true), { type: "message" }]), true);
  assert.equal(resolveOn([e(true), e(false)]), false);
});

test("buildPromptSection: profile, truncation, manifest notice", () => {
  const base = { contract: "RULES", state: { ladderMax: 2, lang: null } };
  assert.match(buildPromptSection({ ...base, profile: null }), /Sem perfil/);
  const withProfile = buildPromptSection({ ...base, profile: "# Perfil\nx", manifestChanged: true });
  assert.match(withProfile, /RULES/);
  assert.match(withProfile, /# Perfil/);
  assert.match(withProfile, /Manifesto\/AGENTS.md mudou/);
  assert.match(buildPromptSection({ ...base, profile: "y".repeat(9000) }), /\[perfil truncado\]/);
});

test("isBlockedTool", () => {
  assert.ok(isBlockedTool("edit") && isBlockedTool("write"));
  assert.ok(!isBlockedTool("read") && !isBlockedTool("bash") && !isBlockedTool("tutor_save_profile"));
});

test("countChangedLines ignores file headers", () => {
  const diff = "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-old\n+new\n+more\n context\n";
  assert.equal(countChangedLines(diff), 3);
});

test("decideReview needs: changed hash, stable across polls, big enough, not too soon", () => {
  const base = { lastHash: "A", changed: 10, now: MIN_REVIEW_INTERVAL_MS + 1, lastReviewAt: 0 };
  assert.equal(decideReview({ ...base, hash: "A", prevHash: "A" }).review, false); // already reviewed
  assert.equal(decideReview({ ...base, hash: "B", prevHash: "A" }).review, false); // still moving
  assert.equal(decideReview({ ...base, hash: "B", prevHash: "B", changed: 1 }).review, false); // too small
  assert.equal(decideReview({ ...base, hash: "B", prevHash: "B", now: 1000 }).review, false); // too soon
  assert.equal(decideReview({ ...base, hash: "B", prevHash: "B" }).review, true);
});

test("ensureTutorDir: .tutor is invisible to git without touching project ignore files", () => {
  const dir = repo();
  ensureTutorDir(dir);
  saveProfile(dir, "# Perfil");
  saveState(dir, { ladderMax: 1 });
  assert.equal(git(dir, "status", "--porcelain"), "");
  assert.equal(fs.existsSync(path.join(dir, ".gitignore")), false);
  assert.equal(loadState(dir).ladderMax, 1);
  assert.equal(loadState(dir).watch, true); // defaults merged
});

test("saveProfile rejects empty and oversized content", () => {
  const dir = tmp();
  assert.throws(() => saveProfile(dir, "  "), /empty/);
  assert.throws(() => saveProfile(dir, "x".repeat(20_001)), /too large/);
  saveProfile(dir, "ok");
  assert.equal(fs.readFileSync(tutorPath(dir, "profile.md"), "utf8"), "ok\n");
});

test("manifestHash changes with the manifest", () => {
  const dir = tmp();
  assert.equal(manifestHash(dir), null);
  fs.writeFileSync(path.join(dir, "Cargo.toml"), "[package]\n");
  const h1 = manifestHash(dir);
  fs.writeFileSync(path.join(dir, "Cargo.toml"), "[package]\n[dependencies]\ntokio = \"1\"\n");
  assert.notEqual(manifestHash(dir), h1);
});

test("gitSnapshot: stable when idle, changes on edit and on new file, null outside git", async () => {
  const dir = repo();
  const clean = await gitSnapshot(dir);
  assert.equal((await gitSnapshot(dir)).hash, clean.hash);
  assert.equal(clean.changed, 0);

  fs.writeFileSync(path.join(dir, "a.txt"), "one\ntwo\nthree\nfour\n");
  const edited = await gitSnapshot(dir);
  assert.notEqual(edited.hash, clean.hash);
  assert.equal(edited.changed, 3);

  fs.writeFileSync(path.join(dir, "new.txt"), "x");
  const withNew = await gitSnapshot(dir);
  assert.notEqual(withNew.hash, edited.hash);
  assert.ok(withNew.changed > edited.changed);

  ensureTutorDir(dir);
  fs.writeFileSync(tutorPath(dir, "state.json"), "{}"); // tutor's own files must not trigger reviews
  assert.equal((await gitSnapshot(dir)).hash, withNew.hash);

  assert.equal(await gitSnapshot(tmp()), null);
});
