#!/usr/bin/env python3
"""Deterministic validator for a security-review findings report.

Stdlib only. Nothing a sub-skill reports is taken on trust: the PoC is executed
again (through guard.py by default, so scope and budget still apply), evidence is
re-hashed, and the report envelope is closed (unknown keys and long prose are
errors). A `verified: true`-style field is never read as proof; the validator
rejects the field and re-executes anyway.

What the negative control does and does not prove: the control proves that the PoC
produces a signal different from a benign command. It does not prove that the PoC
contacted the target, nor that the signal depends on the flaw; a PoC that only prints
the expected signal passes.

A wrapper argv is rejected on purpose: `timeout 30 ./poc` and `nice ./poc` both fail,
because the PoC must be argv[0] -- timeouts belong on the executor, not on the command.

Exit code: 0 only when the report is ok.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "report_schema.json"

sys.path.insert(0, str(HERE))
import guard  # noqa: E402  (same directory; the pre-flight below uses its checks)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# C0/C1 controls and ESC: a newline or an escape sequence inside a one-line field is how
# text taken from the target would forge structure or repaint the orchestrator's output.
# U+2028/U+2029 break lines in some readers; the bidi controls reorder the visible text.
CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
# argv is never a shell string; these as argv[0] would turn one back into one.
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "cmd", "cmd.exe", "powershell", "pwsh"}
# Wrappers exec whatever follows them, so they are the same hole as a bare shell.
WRAPPERS = {"env", "busybox", "xargs", "nohup", "setsid", "timeout", "nice", "stdbuf",
            "chroot", "ionice", "nsenter", "unshare", "strace", "ltrace", "time",
            "command"}


class RunResult(NamedTuple):
    """What an executor observed. `refused` is set when the PoC never ran."""

    exitCode: int
    stdout: str
    stderr: str
    refused: str | None = None


def load_schema(path=None) -> dict:
    return json.loads(Path(path or SCHEMA_PATH).read_text())


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_envelope(obj, required, allowed, where, errors, forbidden=()) -> bool:
    """Reject unknown/forbidden keys and list missing ones. False if not an object."""
    if not isinstance(obj, dict):
        errors.append(f"{where} must be a JSON object")
        return False
    for key in sorted(set(obj) - set(allowed)):
        if key in forbidden:
            errors.append(f"{where}.{key}: not accepted as proof; the validator re-executes "
                          "pocVerifyCommand itself")
        else:
            errors.append(f"{where}.{key}: unknown field (the envelope is closed)")
    for key in required:
        if key not in obj:
            errors.append(f"{where}.{key}: missing required field")
    return True


def _text(errors, where, obj, key, limit, single_line=True) -> None:
    value = obj[key]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}.{key}: must be a non-empty string")
    elif len(value) > limit:
        errors.append(f"{where}.{key}: {len(value)} chars exceeds the {limit}-char limit "
                      "(free text is capped)")
    elif single_line and CONTROL_RE.search(value):
        errors.append(f"{where}.{key}: contains a control character (newline, ESC, ...); a "
                      "one-line field cannot carry structure")


def _enum(errors, where, obj, key, allowed) -> None:
    if key in obj and obj[key] not in allowed:
        errors.append(f"{where}.{key}: expected one of {', '.join(allowed)}; got {obj[key]!r}")


def _validate_coverage(coverage, schema, errors) -> list | None:
    cs = schema["report"]["coverage"]
    cov = coverage
    if not isinstance(cov, dict):
        errors.append("report.coverage must be an object with 'inspected' and 'excluded'")
        return None
    for key in sorted(set(cov) - set(cs["required"])):
        errors.append(f"report.coverage.{key}: unknown field (the envelope is closed)")
    for key in cs["required"]:
        if key not in cov:
            errors.append(f"report.coverage.{key}: missing required field")
    limit = schema["limits"]["coverageItem"]
    inspected = cov.get("inspected")
    if "inspected" in cov:
        if not isinstance(inspected, list):
            errors.append("report.coverage.inspected must be a list of strings")
        else:
            for i, item in enumerate(inspected):
                _text(errors, f"report.coverage.inspected[{i}]", {"v": item}, "v", limit)
    excluded = cov.get("excluded")
    if "excluded" in cov:
        if not isinstance(excluded, list):
            errors.append("report.coverage.excluded must be a list of {item, reason}")
            excluded = None
        for i, entry in enumerate(excluded or []):
            where = f"report.coverage.excluded[{i}]"
            if not isinstance(entry, dict) or set(entry) != {"item", "reason"}:
                errors.append(f"{where}: must be exactly {{item, reason}}")
                continue
            _text(errors, where, entry, "item", limit)
            _enum(errors, where, entry, "reason", cs["excludedReason"]["enum"])
    return inspected if isinstance(inspected, list) else None


def _validate_expect(expect, schema, errors) -> bool:
    """True when `expect` states at least one checkable expectation."""
    allowed = schema["finding"]["expect"]["allowed"]
    if not isinstance(expect, dict):
        errors.append("finding.expect must be an object stating an expected exit code "
                      "and/or a substring of stdout/stderr")
        return False
    for key in sorted(set(expect) - set(allowed)):
        errors.append(f"finding.expect.{key}: unknown field (allowed: {', '.join(allowed)})")
    if not set(expect) & set(allowed):
        errors.append("finding.expect must state at least one of: " + ", ".join(allowed))
        return False
    ok = True
    for key in ("exitCode", "httpStatus"):
        if key in expect and not _is_int(expect[key]):
            errors.append(f"finding.expect.{key} must be an integer")
            ok = False
    for key in ("stdoutContains", "stderrContains"):
        if key in expect:
            bad = len(errors)
            # a matched substring may legitimately span lines, so it is not single-line
            _text(errors, "finding.expect", expect, key,
                  schema["limits"]["expectSubstring"], single_line=False)
            ok = ok and len(errors) == bad
    return ok


def _validate_evidence_files(files, evidence_dir, schema, errors) -> None:
    if not isinstance(files, list) or not files:
        errors.append("finding.evidenceFiles must be a non-empty list of {path, sha256}")
        return
    if evidence_dir is None:
        errors.append("report: no evidence directory given, so evidenceFiles cannot be "
                      "checked")
        return
    root = Path(os.path.realpath(evidence_dir))
    for i, entry in enumerate(files):
        where = f"finding.evidenceFiles[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object with 'path' and 'sha256'")
            continue
        if set(entry) != set(schema["finding"]["evidence"]["required"]):
            errors.append(f"{where}: must be exactly {{path, sha256}}")
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            errors.append(f"{where}.path must be a non-empty string")
            continue
        if CONTROL_RE.search(path):
            errors.append(f"{where}.path: contains a control character (newline, ESC, ...)")
            continue
        real = Path(os.path.realpath(Path(path) if os.path.isabs(path) else root / path))
        # realpath: a symlink (or a parent directory symlink) that leaves the evidence
        # directory is the escape this check exists for.
        if real != root and root not in real.parents:
            errors.append(f"{where}: {path} resolves outside the evidence directory "
                          f"{root} (symlink escape)")
            continue
        if not real.is_file():
            errors.append(f"{where}: {path} does not exist")
            continue
        declared = entry.get("sha256")
        if not isinstance(declared, str) or SHA256_RE.match(declared) is None:
            errors.append(f"{where}.sha256 must be a lowercase hex sha256")
            continue
        actual = sha256_file(real)
        if actual != declared:
            errors.append(f"{where}: sha256 of {path} is {actual[:12]}..., declared "
                          f"{declared[:12]}...")


def _poc_candidates(finding, cwd=None) -> list[str]:
    """sha256 of every argv element naming an existing file, resolved against the PoC cwd."""
    argv = finding.get("pocVerifyCommand")
    if not isinstance(argv, list):
        return []
    base = Path(cwd) if cwd is not None else Path.cwd()
    hashes = []
    for arg in argv:
        if isinstance(arg, str):
            path = Path(arg) if os.path.isabs(arg) else base / arg
            if path.is_file():
                hashes.append(sha256_file(path))
    return hashes


def _validate_argv(finding, key, schema, errors) -> bool:
    """argv must be a non-empty string list that is not a shell invocation."""
    argv = finding.get(key)
    where = f"finding.{key}"
    if not isinstance(argv, list) or not argv:
        errors.append(f"{where} must be a non-empty argv list, not a shell string")
        return False
    if not all(isinstance(arg, str) and arg.strip() for arg in argv):
        errors.append(f"{where} must contain only non-empty strings")
        return False
    limit = schema["limits"]["commandArg"]
    for i, arg in enumerate(argv):
        if len(arg) > limit:
            errors.append(f"{where}[{i}]: {len(arg)} chars exceeds the {limit}-char limit")
        elif CONTROL_RE.search(arg):
            errors.append(f"{where}[{i}]: contains a control character (newline, ESC, ...)")
    names = [Path(arg).name.lower() for arg in argv]
    if names[0] in SHELLS | WRAPPERS:
        # A wrapper execs its arguments, so the shell it delegates to is the same hole:
        # ['/bin/nice', 'sh', '-c', ...] reports the shell, not just the wrapper.
        at = next((i for i, name in enumerate(names) if name in SHELLS), 0)
        what = ("is a shell" if names[at] in SHELLS else
                "is a wrapper that execs one; a wrapper is a shell by another name")
        errors.append(f"{where}[{at}]: {argv[at]!r} {what} -- pass an argv list that "
                      "execs the PoC directly")
        return False
    return True


def _mismatches(result, expect, prefix) -> list[str]:
    """Every declared expectation the run does not meet (empty = it reproduces)."""
    out = []
    if "exitCode" in expect and result.exitCode != expect["exitCode"]:
        out.append(f"{prefix} exited {result.exitCode}, declared {expect['exitCode']}")
    if "stdoutContains" in expect and expect["stdoutContains"] not in result.stdout:
        out.append(f"{prefix} stdout does not contain {expect['stdoutContains']!r}")
    if "stderrContains" in expect and expect["stderrContains"] not in result.stderr:
        out.append(f"{prefix} stderr does not contain {expect['stderrContains']!r}")
    if "httpStatus" in expect and not re.search(
            rf"(?<!\d){expect['httpStatus']}(?!\d)", result.stdout):
        # shortcut: an HTTP status is only read as the bare number in stdout (the PoC
        # prints it); upgrade to a structured probe result if bodies can contain numbers.
        out.append(f"{prefix} stdout never shows HTTP status {expect['httpStatus']}")
    return out


def _run(executor, argv, cwd, what, errors):
    """One run through the executor; None (with the reason recorded) if it never ran."""
    try:
        result = executor(argv, cwd)
    except subprocess.TimeoutExpired as exc:
        errors.append(f"finding: {what} timed out after {exc.timeout}s")
        return None
    except OSError as exc:
        errors.append(f"finding: {what} could not be executed: {exc}")
        return None
    # guard's argparse diagnostics exit 2 with "usage:": that is a refusal, never the PoC.
    refusal = result.refused or _guard_refusal(result.stderr)
    if refusal:
        errors.append(f"finding: {what} refused by the guard: {refusal}")
        return None
    return result


def _reexecute(finding, expect, executor, cwd, errors) -> None:
    """Run the PoC and its negative control; only the PoC may reproduce the expectation."""
    if executor is None:
        errors.append("finding: no executor configured, so pocVerifyCommand was not "
                      "re-executed (an unverified finding cannot pass)")
        return
    result = _run(executor, finding["pocVerifyCommand"], cwd, "re-execution", errors)
    if result is not None:
        errors.extend(_mismatches(result, expect, "re-execution"))
    control = _run(executor, finding["negativeControlCommand"], cwd,
                   "negativeControlCommand", errors)
    if control is None:
        return
    if not _mismatches(control, expect, "negative control"):
        errors.append("finding.negativeControlCommand: the benign control meets expect too, "
                      "so the expectation proves nothing; it must distinguish the PoC from "
                      "a run that cannot show the flaw")


def validate_finding(finding, schema, executor=None, evidence_dir=None, cwd=None) -> dict:
    errors: list[str] = []
    if not isinstance(finding, dict):
        return {"id": None, "ok": False, "errors": ["finding must be a JSON object"]}
    fs = schema["finding"]
    fid = finding.get("id")
    allowed = set(fs["required"]) | set(fs.get("optional", []))
    _check_envelope(finding, fs["required"], allowed, "finding", errors,
                    set(fs.get("forbidden", [])))

    if "id" in finding and (not isinstance(fid, str) or ID_RE.match(fid) is None):
        errors.append("finding.id: expected ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    _enum(errors, "finding", finding, "severity", fs["severity"]["enum"])
    _enum(errors, "finding", finding, "confidence", fs["confidence"]["enum"])
    for key in ("title", "location"):
        if key in finding:
            _text(errors, "finding", finding, key, schema["limits"][key])

    if "pocSha256" in finding:
        declared = finding["pocSha256"]
        if not isinstance(declared, str) or SHA256_RE.match(declared) is None:
            errors.append("finding.pocSha256 must be a lowercase hex sha256")
        else:
            hashes = _poc_candidates(finding, cwd)
            if not hashes:
                errors.append(f"finding.pocSha256: pocVerifyCommand names no existing file, "
                              f"so {declared[:12]}... cannot be re-checked")
            elif declared not in hashes:
                errors.append(f"finding.pocSha256 {declared[:12]}... matches no file named in "
                              "pocVerifyCommand (the PoC was edited, or the hash is forged)")

    expect_ok = _validate_expect(finding["expect"], schema, errors) if "expect" in finding \
        else False
    argv_ok = _validate_argv(finding, "pocVerifyCommand", schema, errors) \
        if "pocVerifyCommand" in finding else False
    control_ok = _validate_argv(finding, "negativeControlCommand", schema, errors) \
        if "negativeControlCommand" in finding else False

    if argv_ok and control_ok and expect_ok:
        _reexecute(finding, finding["expect"], executor, cwd, errors)
    # Evidence is hashed after re-execution: a PoC that rewrites its own evidence cannot
    # pass by being hashed first.
    if "evidenceFiles" in finding:
        _validate_evidence_files(finding["evidenceFiles"], evidence_dir, schema, errors)

    return {"id": fid if isinstance(fid, str) else None, "ok": not errors, "errors": errors}


def validate_report(report, schema=None, executor=None, evidence_dir=None, cwd=None) -> dict:
    schema = schema or load_schema()
    report_schema = schema["report"]
    errors: list[str] = []

    if not isinstance(report, dict):
        return {"ok": False, "errors": ["report must be a JSON object"], "findings": []}

    allowed = set(report_schema["required"]) | set(report_schema.get("optional", []))
    _check_envelope(report, report_schema["required"], allowed, "report", errors,
                    set(report_schema.get("forbidden", [])))

    if "schemaVersion" in report and not _is_int(report["schemaVersion"]):
        # True == 1 and 1.0 == 1: an exact int is the only accepted type.
        errors.append("report.schemaVersion: must be an integer; got "
                      f"{report['schemaVersion']!r}")
    elif "schemaVersion" in report and report["schemaVersion"] != schema["schemaVersion"]:
        errors.append(f"report.schemaVersion: expected {schema['schemaVersion']}; got "
                      f"{report['schemaVersion']!r}")

    inspected = _validate_coverage(report.get("coverage"), schema, errors) \
        if "coverage" in report else None

    count = report.get("itemsInspected")
    if "itemsInspected" in report:
        if not _is_int(count) or count < 0:
            errors.append("report.itemsInspected must be a non-negative integer")
        elif count == 0:
            # Zero work is never a pass on its own: only a small enumerated reason counts.
            reasons = report_schema["notApplicableReason"]["enum"]
            if "notApplicableReason" not in report:
                errors.append("report: itemsInspected is 0 and no notApplicableReason given; "
                              "an empty review is never a pass (allowed: "
                              + ", ".join(reasons) + ")")
            elif report["notApplicableReason"] not in reasons:
                errors.append("report.notApplicableReason: free prose is not accepted; expected "
                              "one of " + ", ".join(reasons))
            if report.get("findings"):
                errors.append("report: findings are present but itemsInspected is 0 "
                              "(nothing was inspected)")
        else:
            if "notApplicableReason" in report:
                errors.append("report.notApplicableReason: only allowed when itemsInspected "
                              "is 0")
            if inspected is not None and len(inspected) != count:
                errors.append(f"report.itemsInspected is {count} but coverage.inspected "
                              f"lists {len(inspected)}")

    findings_raw = report.get("findings")
    if "findings" in report and not isinstance(findings_raw, list):
        errors.append("report.findings must be a list")
        findings_raw = []
    findings_raw = findings_raw or []
    if len(findings_raw) > schema["limits"]["maxFindings"]:
        errors.append(f"report.findings: {len(findings_raw)} exceeds the "
                      f"{schema['limits']['maxFindings']} limit")

    cwd = cwd if cwd is not None else evidence_dir
    results = [validate_finding(f, schema, executor, evidence_dir, cwd) for f in findings_raw]
    seen = set()
    for result in results:
        if result["id"] is not None:
            if result["id"] in seen:
                errors.append(f"report.findings: duplicate finding id {result['id']!r}")
            seen.add(result["id"])
    ok = not errors and all(r["ok"] for r in results)
    return {"ok": ok, "errors": errors, "findings": results}


def _preflight(scope, sig, pubkey, target, max_seconds) -> str | None:
    """The guard's own checks, in this process, before anything is executed.

    Without this, an argparse error inside guard exits 2 with "usage:" and that exit
    code would be read as the PoC's own (a report declaring exitCode 2 would pass with
    the PoC never run).
    """
    if int(max_seconds) < 1:
        return "max-seconds must be a positive integer"
    try:
        manifest = guard.verify_scope(scope, sig, pubkey)
    except guard.ScopeError as exc:
        return str(exc)
    if "://" not in str(target):
        return f"--target must be an exact scheme://host:port; got {target!r}"
    if not guard.check_target(manifest, str(target)):
        return f"target {target!r} is not in the signed scope"
    return None


def guard_executor(scope, sig, pubkey, target, max_seconds) -> callable:
    """PoC executor that only runs through guard.py (scope + budget enforced there)."""
    preflight: list = []  # one entry, computed on the first run and reused

    def refusal():
        if not preflight:
            preflight.append(_preflight(scope, sig, pubkey, target, max_seconds))
        return preflight[0]

    def run(argv, cwd):
        denied = refusal()
        if denied:
            return RunResult(1, "", "", denied)
        cmd = [sys.executable, str(HERE / "guard.py"), "run",
               "--scope", str(scope), "--sig", str(sig), "--pubkey", str(pubkey),
               "--target", str(target), "--max-seconds", str(int(max_seconds)),
               "--cwd", str(cwd), "--", *argv]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                                  timeout=int(max_seconds) * 2 + 60)
        except subprocess.TimeoutExpired:
            return RunResult(124, "", "", f"guard timed out after {max_seconds}s")
        # guard.py lets the child inherit stdout/stderr, so capturing the guard process
        # captures the PoC's own streams.
        return RunResult(proc.returncode, proc.stdout, proc.stderr,
                         _guard_refusal(proc.stderr))

    return run


def _guard_refusal(stderr: str) -> str | None:
    """guard's own refusal message, if it refused instead of running the PoC."""
    for line in stderr.splitlines():
        line = line.strip()
        # shortcut: a PoC stderr line starting with "guard:" or "usage:" would read as a
        # refusal; prefix guard's diagnostics differently if PoCs ever echo that.
        if line.startswith(("guard:", "usage:")) and not line.startswith("guard: warning:"):
            return line.split(":", 1)[1].strip()
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="validate a security-review findings report")
    parser.add_argument("--report", required=True, help="report JSON to validate")
    parser.add_argument("--evidence-dir", required=True,
                        help="directory every evidenceFiles path must stay inside")
    parser.add_argument("--cwd", default=None, help="working directory for re-execution")
    parser.add_argument("--scope", default=None, help="signed scope manifest")
    parser.add_argument("--sig", default=None, help="scope signature")
    parser.add_argument("--pubkey", default=None, help="scope signer's public key")
    parser.add_argument("--target", default=None,
                        help="exact scheme://host:port the PoCs test")
    parser.add_argument("--max-seconds", type=int, default=60,
                        help="re-execution budget (guard's signed ceiling still wins)")
    args = parser.parse_args(argv)

    executor = None
    if all((args.scope, args.sig, args.pubkey, args.target)):
        executor = guard_executor(args.scope, args.sig, args.pubkey, args.target,
                                  args.max_seconds)
    try:
        report = json.loads(Path(args.report).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        result = {"ok": False, "errors": [f"report unreadable: {exc}"], "findings": []}
    else:
        result = validate_report(report, executor=executor, evidence_dir=args.evidence_dir,
                                 cwd=args.cwd or args.evidence_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
