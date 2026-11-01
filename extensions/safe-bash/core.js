// Denylist gate for safe_bash, modeled on pi-subagents' safe-bash: block destructive/exfiltrating patterns, allow the rest.
// shortcut: regex denylist is best-effort, not a sandbox; use distrobox for untrusted work.
export const DANGEROUS_PATTERNS = [
  /\s-exec\s+(rm|dd|mkfs)\b/,
  /\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(-[a-zA-Z]*r[a-zA-Z]*\s+)?(\/|~\S*)/,
  /\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?(-[a-zA-Z]*f[a-zA-Z]*\s+)?(\/|~\S*)/,
  /\bsudo\b/, /\bmkfs\b/, /\bdd\s+if=/,
  /:\(\)\s*\{\s*:\|:&\s*\}\s*;:/,
  />\s*\/dev\/[sh]d[a-z]/,
  /\bchmod\s+(-[a-zA-Z]+\s+)?777\s+\//,
  /\bchown\s+(-[a-zA-Z]+\s+)?root/,
  /\b(curl|wget)\s.*\|\s*(ba|z)?sh/,
  /\bshutdown\b/, /\breboot\b/, /\binit\s+0\b/, /\bkill\s+-9\s+1\b/, /\bkillall\b/,
  /\beval\s/, /\bsource\s/, /\.\s+.*\$\{/,
  /\|\s*(ba|z)?sh\b/, /\|\s*(python[23]?|perl|node|php)\b/,
  /base64\s+(-d|--decode)\s*\|\s*(ba|z)?sh/,
  /echo\s+[A-Za-z0-9+/=]{20,}\s*\|\s*base64\s+(-d|--decode)/,
  /\$\(.*\b(rm|dd|mkfs|sudo|curl|wget|nc|ncat|netcat|id|whoami|chmod)\b/,
  /`.*\b(rm|dd|mkfs|sudo|curl|wget|nc|ncat|netcat|id|whoami|chmod)\b/,
  /\b(nc|ncat|netcat)\s+.*-l/, /\bnc\s+.*-e\s*(\/bin\/)?(ba)?sh/, /\bncat\s+.*--exec\s*(\/bin\/)?(ba)?sh/,
  /\b(curl|wget)\s.*-o\s*(\/usr|\/bin|\/sbin|\/etc|\/tmp|~)/,
  /\b(curl|wget)\s.*>\s*(\/usr|\/bin|\/sbin|\/etc|\/tmp|~)/,
  />\s*\/(etc|usr|boot)\//,
  /\biptables\b/, /\bufw\b/,
  /\benv\b/, /\bprintenv\b/, // would leak credentials from the environment
];

// Returns null when allowed, otherwise the reason it is blocked.
export function isDangerous(command) {
  if (typeof command !== "string" || !command.trim()) return "empty command";
  const normalized = command.replace(/\\\n/g, " ").replace(/#.*$/gm, "");
  const expanded = normalized.replace(/\$\{[^}]*\}/g, "X").replace(/\$[A-Za-z_][A-Za-z0-9_]*/g, "X");
  const hit = DANGEROUS_PATTERNS.find((p) => p.test(normalized) || p.test(expanded));
  return hit ? `Command blocked by safe_bash: matches dangerous pattern ${hit}` : null;
}
