// Pi extension: safe_bash, bash with dangerous-command blocking (same contract as pi-subagents' safe_bash).
import { execFile } from "node:child_process";
import { isDangerous } from "./core.js";

const DEFAULT_TIMEOUT_S = 300;
const MAX_CHARS = 50_000;

export default function safeBashExtension(pi) {
  pi.registerTool({
    name: "safe_bash",
    label: "Safe Bash",
    description: "Execute a bash command. Blocks dangerous commands (rm -rf /, sudo, mkfs, curl | sh, env, etc.).",
    parameters: {
      type: "object",
      properties: {
        command: { type: "string", description: "Bash command to execute" },
        timeout: { type: "number", description: "Timeout in seconds (default 300; pass more for builds/tests/installs)" },
      },
      required: ["command"],
      additionalProperties: false,
    },
    async execute(_id, params, signal, _onUpdate, ctx) {
      const danger = isDangerous(params.command);
      if (danger) throw new Error(danger);
      const out = await new Promise((resolve, reject) => {
        execFile("bash", ["-c", params.command], {
          cwd: ctx?.cwd ?? process.cwd(), timeout: (params.timeout ?? DEFAULT_TIMEOUT_S) * 1000, signal, maxBuffer: 10 * MAX_CHARS,
        }, (err, stdout, stderr) => {
          let text = `${stdout}${stderr}`;
          if (text.length > MAX_CHARS) text = `...[truncated]\n${text.slice(-MAX_CHARS)}`;
          if (err?.killed) return reject(new Error(`${text}\nCommand timed out`));
          if (err) return reject(new Error(`${text}\n[exit ${err.code}]`));
          resolve(text);
        });
      });
      return { content: [{ type: "text", text: out || "(no output)" }], details: undefined };
    },
  });
}
