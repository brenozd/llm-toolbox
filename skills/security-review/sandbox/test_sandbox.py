"""Real container tests for the security-review sandbox.

Run: python3 -m pytest skills/security-review/sandbox/test_sandbox.py -v
Needs docker (or podman) and network access to build the image once. Tests skip --
never fake a pass -- when no runtime exists or the image cannot be built.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SANDBOX = Path(__file__).resolve().parent
IMAGE = os.environ.get("SANDBOX_IMAGE", "security-review-sandbox:test")
_runtime = os.environ.get("CONTAINER_RUNTIME") or shutil.which("docker") or shutil.which("podman")
RUNTIME = _runtime if _runtime and shutil.which(_runtime) else None
RUN_WEB = SANDBOX / "run-web.sh"
RUN_C = SANDBOX / "run-c.sh"

pytestmark = pytest.mark.docker

TARGET_SERVER = """\
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"in-scope\\n"
            self.send_response(200)
        elif self.path == "/redir":
            body = b""
            self.send_response(302)
            self.send_header("Location", "http://example.com:80/")
        else:
            body = b"nope\\n"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", 8080), H).serve_forever()
"""


def rt(*args, **kwargs):
    return subprocess.run([RUNTIME, *args], capture_output=True, text=True, **kwargs)


def docker_env(**extra):
    return {**os.environ, "CONTAINER_RUNTIME": RUNTIME, "SANDBOX_IMAGE": IMAGE, **extra}


@pytest.fixture(scope="session")
def image():
    if not RUNTIME:
        pytest.skip("no container runtime: neither docker nor podman on PATH")
    if rt("info").returncode != 0:
        pytest.skip(f"{RUNTIME} daemon is not reachable")
    proc = rt("build", "-t", IMAGE, str(SANDBOX), timeout=1800)
    if proc.returncode != 0:
        pytest.skip(f"image build failed:\n{proc.stderr[-3000:]}")
    return IMAGE


@pytest.fixture(scope="session")
def web(image, tmp_path_factory):
    """Internal net + egress net + target + dual-homed proxy, allowlist from scope."""
    tag = str(os.getpid())
    internal, egress = f"sr-internal-{tag}", f"sr-egress-{tag}"
    target, proxy = f"sr-target-{tag}", f"sr-proxy-{tag}"
    # Not pytest's tmp_path: its parents are 0700 and the container's root (userns or
    # rootless) cannot traverse them, so the server file would be unreadable.
    conf = Path(tempfile.mkdtemp(prefix=f"sr-proxy-{tag}-"))
    os.chmod(conf, 0o755)
    (conf / "server.py").write_text(TARGET_SERVER)
    (conf / "server.py").chmod(0o644)
    base = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--pids-limit", "256", "--tmpfs", "/tmp"]

    def cleanup():
        for name in (proxy, target):
            rt("rm", "-f", name)
        for net in (internal, egress):
            rt("network", "rm", net)
        shutil.rmtree(conf, ignore_errors=True)

    try:
        for net, flags in ((internal, ["--internal"]), (egress, [])):
            proc = rt("network", "create", *flags, net)
            assert proc.returncode == 0, proc.stderr
        proc = rt("run", "-d", "--name", target, "--network", egress,
                  "--network-alias", "target", *base,
                  "-v", f"{conf}:/srv:ro", image, "python3", "/srv/server.py")
        assert proc.returncode == 0, proc.stderr

        scope = {
            "targets": ["http://target:8080"],
            "expiresAt": "2999-01-01T00:00:00Z",
            "maxSeconds": 60,
            "maxDiskMB": 10,
            "createdBy": "test@example.com",
        }
        proc = rt("run", "--rm", "-i", "--network", egress, "-v", f"{conf}:/conf",
                  image, "python3", "/opt/sandbox/gen-proxy-conf.py",
                  "--scope", "-", "--out", "/conf/proxy.json", input=json.dumps(scope))
        assert proc.returncode == 0, proc.stderr

        proc = rt("run", "-d", "--name", proxy, "--network", internal,
                  "--network-alias", "proxy", *base,
                  "-v", f"{conf}:/conf:ro", image,
                  "python3", "/opt/sandbox/egress_proxy.py", "--config", "/conf/proxy.json")
        assert proc.returncode == 0, proc.stderr
        proc = rt("network", "connect", egress, proxy)
        assert proc.returncode == 0, proc.stderr
        for _ in range(100):
            if "listening" in rt("logs", proxy).stdout:
                break
            time.sleep(0.1)
        else:
            pytest.fail(f"proxy never became ready:\n{rt('logs', proxy).stdout}{rt('logs', proxy).stderr}")
        yield SimpleNamespace(internal=internal, egress=egress, target=target, proxy=proxy, image=image)
    finally:
        cleanup()


def tool(web, *cmd):
    """A tool container: internal network only, HTTP forced through the proxy."""
    return rt("run", "--rm", "--network", web.internal,
              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
              "--read-only", "--pids-limit", "256", "--tmpfs", "/tmp",
              "-e", "HOME=/tmp",
              "-e", "http_proxy=http://proxy:8888", "-e", "HTTP_PROXY=http://proxy:8888",
              "-e", "https_proxy=", "-e", "HTTPS_PROXY=",
              web.image, *cmd)


def curl(url, *flags):
    return ("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", *flags, url)


def proxy_log(web):
    return rt("logs", web.proxy).stdout


def test_curl_out_of_scope_denied(web):
    proc = tool(web, *curl("http://example.com:80/"))
    assert proc.stdout.strip() == "403", (proc.stdout, proc.stderr)
    log = proxy_log(web)
    assert "decision=DENY" in log and "target=example.com:80" in log, log


def test_curl_in_scope_allowed(web):
    proc = tool(web, *curl("http://target:8080/ok"))
    assert proc.stdout.strip() == "200", (proc.stdout, proc.stderr)
    assert "decision=ALLOW" in proxy_log(web) and "target=target:8080" in proxy_log(web)


def test_redirect_to_out_of_scope_not_followed_by_proxy(web):
    # The proxy relays the 302 verbatim and never asks for the Location itself ...
    mark = len(proxy_log(web))
    proc = tool(web, *curl("http://target:8080/redir"))
    assert proc.stdout.strip() == "302", (proc.stdout, proc.stderr)
    assert "target=example.com:80" not in proxy_log(web)[mark:]
    # ... when the *client* follows it, the proxy denies the second hop.
    mark = len(proxy_log(web))
    proc = tool(web, *curl("http://target:8080/redir", "-L"))
    assert proc.stdout.strip() == "403", (proc.stdout, proc.stderr)
    log = proxy_log(web)[mark:]
    assert "decision=DENY" in log and "target=example.com:80" in log, log


def test_direct_ip_has_no_route(web):
    ip = rt("inspect", "-f",
            '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % web.egress,
            web.target).stdout.strip()
    assert ip, "could not read target IP"
    proc = tool(web, *curl(f"http://{ip}:8080/ok", "--noproxy", "*"))
    assert proc.returncode != 0, f"direct access to {ip} should fail, got {proc.stdout!r}"


def test_nuclei_runs_offline_with_baked_templates(web):
    proc = rt("run", "--rm", "--network", "none",
              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
              "--read-only", "--pids-limit", "256", "--tmpfs", "/tmp",
              "-e", "HOME=/tmp", web.image,
              "nuclei", "-duc", "-nt", "-t", "/opt/nuclei-templates",
              "-no-color", "-silent", "-u", "http://127.0.0.1:1")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "update" not in (proc.stdout + proc.stderr).lower()


@pytest.fixture(scope="session")
def c_work():
    work = Path(tempfile.mkdtemp(prefix="sr-c-work-"))
    work.chmod(0o777)  # the container writes here as its own root
    yield work
    shutil.rmtree(work, ignore_errors=True)


def run_c(work, *cmd, timeout=120):
    return subprocess.run([str(RUN_C), str(work), *cmd], capture_output=True, text=True,
                          env=docker_env(), timeout=timeout)


def test_asan_detects_oob(web, c_work):
    proc = run_c(c_work, "sh", "-c", """
cat > /work/oob.c <<'EOF'
#include <stdlib.h>
int main(void) { char *p = malloc(8); p[8] = 'x'; return p[8]; }
EOF
clang -g -fsanitize=address -o /work/oob /work/oob.c || exit 99
/work/oob
echo "exit=$?"
""")
    assert "AddressSanitizer" in proc.stdout + proc.stderr, (proc.stdout, proc.stderr)
    assert "exit=1" in proc.stdout, proc.stdout  # ASan aborts with rc 1, not 0


def test_afl_fuzzes_under_readonly_capdrop(web, c_work):
    proc = run_c(c_work, "sh", "-c", """
mkdir -p /work/in && printf 'AAAA' > /work/in/seed
cat > /work/t.c <<'EOF'
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  unsigned char b[8] = {0};
  FILE *f = fopen(argv[1], "rb");
  if (!f) return 1;
  fread(b, 1, 8, f); fclose(f);
  if (b[0] == 'B' && b[1] == 'U' && b[2] == 'G') abort();
  return 0;
}
EOF
afl-clang-fast -o /work/t /work/t.c || exit 99
ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:symbolize=0 AFL_NO_UI=1 afl-fuzz -i /work/in -o /work/out -V 5 -- /work/t @@ >/dev/null 2>&1
test -f /work/out/default/fuzzer_stats && echo AFL_OK
""", timeout=180)
    assert "AFL_OK" in proc.stdout, (proc.stdout, proc.stderr)


def test_c_profile_has_no_network(web, c_work):
    proc = run_c(c_work, "sh", "-c", "curl -s --max-time 3 http://1.1.1.1/ ; echo exit=$?")
    assert "exit=0" not in proc.stdout, proc.stdout


@pytest.fixture(scope="session")
def signed_scope():
    """A real ssh-keygen-signed scope: run-web.sh runs nothing without one."""
    root = Path(tempfile.mkdtemp(prefix="sr-web-scope-"))
    keys = Path(tempfile.mkdtemp(prefix="sr-web-keys-"))  # outside the workspace, as guard requires
    root.chmod(0o755)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "key")], check=True)
    scope = {"targets": ["http://localhost:8080"], "expiresAt": "2999-01-01T00:00:00Z",
             "maxSeconds": 60, "maxDiskMB": 10, "createdBy": "test@example.com"}
    path = root / "scope.json"
    path.write_text(json.dumps(scope))
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "key"),
                    "-n", "security-review-scope", str(path)], check=True, cwd=root)
    yield SimpleNamespace(scope=path, sig=Path(str(path) + ".sig"), pubkey=keys / "key.pub")
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(keys, ignore_errors=True)


def test_run_web_out_dir_survives_and_workdir_is_read_only(image, signed_scope):
    """A tool writes /work-out and the file is on the host after --rm; /work stays :ro."""
    work = Path(tempfile.mkdtemp(prefix="sr-web-work-"))
    out = Path(tempfile.mkdtemp(prefix="sr-web-out-"))
    work.chmod(0o755)
    # out stays 0700 from mkdtemp: the container runs as us (--user), so it writes there
    (work / "repo.txt").write_text("source\n")
    try:
        proc = subprocess.run(
            [str(RUN_WEB), str(signed_scope.scope), str(signed_scope.sig),
             str(signed_scope.pubkey), "--", "sh", "-c",
             "cat /work/repo.txt; echo hi > /work-out/probe.txt; id -G; "
             "touch /work/x 2>/dev/null && echo WORK_WRITABLE || echo WORK_RO"],
            capture_output=True, text=True, timeout=180,
            env=docker_env(OUT_DIR=str(out), WORKDIR=str(work)))
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "source" in proc.stdout, (proc.stdout, proc.stderr)
        assert "WORK_RO" in proc.stdout, (proc.stdout, proc.stderr)
        assert not (work / "x").exists()
        assert (out / "probe.txt").read_text().strip() == "hi", os.listdir(out)
        # --group-add: the container keeps the caller's supplementary groups too.
        host_groups = set(subprocess.run(["id", "-G"], capture_output=True,
                                         text=True).stdout.split())
        assert host_groups <= set(proc.stdout.split()), (host_groups, proc.stdout)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


def test_run_web_fails_when_nuclei_scans_nothing(image, signed_scope):
    """nuclei exits 0 after skipping every probe; run-web.sh must not pass that as a run."""
    out = Path(tempfile.mkdtemp(prefix="sr-web-out-"))
    try:
        proc = subprocess.run(
            [str(RUN_WEB), str(signed_scope.scope), str(signed_scope.sig),
             str(signed_scope.pubkey), "--", "nuclei", "-duc", "-silent",
             "-t", "/opt/nuclei-templates", "-u", "http://127.0.0.1:1"],
            capture_output=True, text=True, timeout=300, env=docker_env(OUT_DIR=str(out)))
        assert proc.returncode != 0, (proc.stdout, proc.stderr)
        assert "scan of nothing is not coverage" in proc.stderr, (proc.stdout, proc.stderr)
    finally:
        shutil.rmtree(out, ignore_errors=True)
