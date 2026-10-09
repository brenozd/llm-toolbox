// Pi extension for the code-tutor skill: toggle, per-turn contract, edit/write block, profile tool, watcher.
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_STATE, DEBOUNCE_MS, buildPromptSection, extractContract, gitSnapshot, decideReview, isBlockedTool,
  loadProfile, loadState, manifestHash, parseCommand, resolveOn, saveProfile, saveState, tutorPath,
} from "./core.js";

const SKILL_PATH = fileURLToPath(new URL("../../skills/code-tutor/SKILL.md", import.meta.url));
const SKILL_CMD = "/skill:code-tutor";
const FALLBACK_CONTRACT = "You are a programming tutor. Never edit project files; teach in words and let the user write the code.";
const BLOCK_REASON = "Tutor mode ON: edit/write are blocked. Describe the change in text (file:line + what and why) and let the user write it. For mechanical work tell them to run /tutor off.";

export default function tutorExtension(pi) {
  let on = false;
  let busy = false;
  let ticking = false;
  let timer = null;
  let watcher = null;
  let lastCtx = null;
  let cwd = process.cwd();
  let toolRegistered = false;
  let state = { ...DEFAULT_STATE };
  let contract = FALLBACK_CONTRACT;

  try {
    contract = extractContract(fs.readFileSync(SKILL_PATH, "utf8")) || FALLBACK_CONTRACT;
  } catch { /* skill file missing: keep the fallback contract */ }

  const notify = (msg, level = "info") => {
    try { lastCtx?.ui?.notify?.(msg, level); } catch { /* ui may be gone after a session switch */ }
  };

  const syncStatus = () => {
    try {
      lastCtx?.ui?.setStatus?.("tutor", on ? `tutor${state.watch ? " +watch" : ""}${busy ? " *" : ""}` : undefined);
    } catch { /* theme/ui proxy not ready */ }
  };

  // skill commands only expand with expandPromptTemplates; while the agent runs, queue instead of interrupting
  const dispatch = (arg) => {
    pi.sendUserMessage(arg ? `${SKILL_CMD} ${arg}` : SKILL_CMD, {
      expandPromptTemplates: true,
      ...(busy ? { deliverAs: "followUp" } : {}),
    });
  };

  // -- Profile tool: the only write the tutor gets ----------------------------
  const ensureTool = () => {
    if (toolRegistered) return;
    toolRegistered = true;
    pi.registerTool({
      name: "tutor_save_profile",
      label: "Tutor: save profile",
      description: "Save the complete project profile markdown to .tutor/profile.md. It is the only file the tutor may write.",
      parameters: {
        type: "object",
        properties: { content: { type: "string", description: "Complete content of profile.md" } },
        required: ["content"],
        additionalProperties: false,
      },
      async execute(_id, params, _signal, _onUpdate, ctx) {
        const dir = ctx?.cwd ?? cwd;
        saveProfile(dir, params.content);
        state.manifestHash = manifestHash(dir);
        saveState(dir, state);
        return { content: [{ type: "text", text: "Profile saved to .tutor/profile.md" }], details: undefined };
      },
    });
  };

  // -- Watcher ---------------------------------------------------------------
  async function tick() {
    if (!on || !state.watch || ticking) return;
    if (busy) return arm(); // agent running: look again once it is quiet
    ticking = true;
    try {
      const snap = await gitSnapshot(cwd, state.lastHash || "HEAD");
      if (!snap || !decideReview({ ...snap, lastHash: state.lastHash })) return;
      const base = snap.base;
      state.lastHash = snap.hash;
      saveState(cwd, state);
      notify("Tutor: changes since the last notification, reviewing.");
      dispatch(`review auto ${base} ${snap.hash}`);
    } finally {
      ticking = false;
    }
  }

  // Debounce: every fs event pushes the review back, so editors that save on each keystroke stay quiet.
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { tick().catch(() => {}); }, DEBOUNCE_MS);
    timer.unref?.();
  };

  const startWatcher = () => {
    if (watcher || !state.watch) return;
    try {
      // recursive fs.watch is inotify on Linux
      watcher = fs.watch(cwd, { recursive: true }, (_ev, file) => {
        if (!/^(\.git|\.tutor|node_modules)([\\/]|$)/.test(String(file ?? ""))) arm();
      });
      watcher.on("error", () => stopWatcher());
    } catch { /* unwatchable dir: no auto reviews */ }
  };

  const stopWatcher = () => {
    watcher?.close();
    watcher = null;
    clearTimeout(timer);
    timer = null;
  };

  // Mark the current tree as reviewed so the watcher does not repeat an explicit review.
  const markReviewed = async () => {
    const snap = await gitSnapshot(cwd);
    if (!snap) return;
    state.lastHash = snap.hash;
    saveState(cwd, state);
  };

  async function setOn(value) {
    on = value;
    pi.appendEntry("tutor-mode", { on });
    if (on) {
      ensureTool();
      state = loadState(cwd);
      // baseline: pre-existing work in progress is not reviewed unprompted
      if (!state.lastHash) await markReviewed();
      startWatcher();
      if (!loadProfile(cwd)) dispatch("setup");
    } else {
      stopWatcher();
    }
    syncStatus();
    notify(`Tutor ${on ? "ON" : "OFF"}.`);
  }

  const restore = (ctx) => {
    lastCtx = ctx;
    cwd = ctx?.cwd ?? cwd;
    const entries = ctx?.sessionManager?.getBranch?.() || ctx?.sessionManager?.getEntries?.() || [];
    on = resolveOn(entries);
    state = loadState(cwd);
    stopWatcher();
    if (on) {
      ensureTool();
      startWatcher();
    }
    syncStatus();
  };

  // -- Command ---------------------------------------------------------------
  pi.registerCommand("tutor", {
    description: "Tutor mode: on|off|status|review [arg]|refresh|lang <x>|ladder <0-6>|watch on|off|profile",
    handler: async (args, ctx) => {
      lastCtx = ctx;
      cwd = ctx?.cwd ?? cwd;
      const cmd = parseCommand(args);

      switch (cmd.type) {
        case "toggle": return setOn(!on);
        case "on": return setOn(true);
        case "off": return setOn(false);
        case "status": {
          const profile = loadProfile(cwd) ? "yes" : "no";
          return notify(`Tutor ${on ? "ON" : "OFF"} | ladderMax ${state.ladderMax} | watch ${state.watch ? "on" : "off"} | lang ${state.lang ?? "auto"} | profile ${profile}`);
        }
        case "profile":
          return notify(loadProfile(cwd) ? `Profile: ${tutorPath(cwd, "profile.md")} (editable)` : "No profile yet. Run /tutor review or /tutor refresh.");
        case "review":
        case "refresh":
          if (!on) return notify("Tutor is OFF. Run /tutor on first.", "warning");
          if (cmd.type === "review") await markReviewed();
          return dispatch(cmd.type === "review" ? `review${cmd.arg ? ` ${cmd.arg}` : ""}` : "refresh");
        case "lang":
          state.lang = cmd.lang;
          saveState(cwd, state);
          return notify(`Tutor language set to ${cmd.lang}.`);
        case "ladder":
          state.ladderMax = cmd.rung;
          saveState(cwd, state);
          return notify(`Tutor ladderMax set to ${cmd.rung}.`);
        case "watch":
          state.watch = cmd.value;
          saveState(cwd, state);
          if (on) (cmd.value ? startWatcher() : stopWatcher());
          syncStatus();
          return notify(`Tutor watch ${cmd.value ? "on" : "off"}.`);
        default:
          return notify(cmd.reason, "warning");
      }
    },
  });

  // -- Events ----------------------------------------------------------------
  pi.on("session_start", async (_event, ctx) => restore(ctx));
  pi.on("session_tree", async (_event, ctx) => restore(ctx));
  pi.on("session_shutdown", async () => stopWatcher());

  pi.on("agent_start", async () => { busy = true; syncStatus(); });
  pi.on("agent_settled", async () => { busy = false; syncStatus(); });

  pi.on("before_agent_start", async (event) => {
    const sections = event?.systemPromptOptions?.sections;
    if (!on) {
      if (sections) delete sections.tutor;
      return;
    }
    const profile = loadProfile(cwd);
    const mh = manifestHash(cwd);
    const text = buildPromptSection({
      contract,
      profile,
      state,
      manifestChanged: Boolean(profile && state.manifestHash && mh !== state.manifestHash),
    });
    if (sections && typeof sections === "object") {
      sections.tutor = text;
      return;
    }
    return { systemPrompt: `${event?.systemPrompt ? `${event.systemPrompt}\n\n` : ""}${text}` };
  });

  pi.on("tool_call", async (event) => {
    if (on && isBlockedTool(event?.toolName)) return { block: true, reason: BLOCK_REASON };
  });
}
