"""Cutdowns: the same arc in a smaller budget, by removing whole scenes -- never by talking faster.

A 60 s master has to yield a 30 s ad and a 15 s cut. The one thing a cutdown must not do is squeeze the
voice-over to fit: speech sped up sounds like a disclaimer, and a shortened line is a rewritten video.
So the only move here is dropping scenes, and the arc decides which ones -- the hook, the proof that
backs its promise, the measured result and the cta never go; the cost of the problem goes first.

The clock comes from `spec.timeline` (the same source stills, render and verify read). A scene whose
narration has no WAV in the manifest yet is budgeted at its read time (words / READ_WPS), so a cutdown
made before narrate() does not promise a duration the voice cannot keep. The kept lines are the same
text (nothing is rewritten), but the cut has its own spec_hash and therefore its own /work/audio/<hash>/
dir, so narrate() speaks them again instead of reusing the master's WAVs.
"""
from __future__ import annotations

import copy
from collections import defaultdict

from . import spec as S

# The beats the arc cannot lose: the promise, its evidence, the outcome and the close.
KEEP = ("hook", "proof", "result", "cta")
# The promise is kept by any of these landing after the hook (same rule as the hook_promise_unkept lint).
DELIVERS = {"proof", "result", "reveal", "value"}
# Why a beat goes, in the order it goes: a repeated hook or cta rehearses an opening/close that already
# happens once, an extra `value` scene repeats the pitch, the `problem` is the setup the hook already
# implies, and everything else unprotected is cut from the tail backwards.
REASONS = {
    "implication": "the cost of the problem: the first beat a shorter cut can lose",
    "hook": "a repeated hook: the first one already opens the video",
    "cta": "an earlier cta: only the last one closes the video",
    "value": "an extra value scene: the first one already makes the pitch",
    "problem": "the problem: kept only while the budget allows",
    "other": "nothing protected is left to cut: the tail goes before the head",
    None: "the plan gives it no role, so it is not part of the arc and goes after every planned beat",
}


class CutdownError(ValueError):
    """A cutdown that cannot be made. `code` is the finding a caller reports (cutdown_infeasible,
    hook_promise_unkept, cutdown_needs_roles); `min_s` is the shortest honest cut when we know it."""

    def __init__(self, code: str, message: str, min_s: float | None = None, **extra):
        super().__init__(f"{code}: {message}")
        self.code, self.min_s, self.extra = code, min_s, extra


def roles(spec: dict) -> dict[str, str]:
    """{scene id: role} from spec.direction.scenes, restricted to scenes that exist.

    Without roles there is no arc, and a cutdown that ignores the arc is just a deletion: refuse instead
    of guessing which scene is the hook."""
    plan = S.plan(spec)
    ids = [sc.get("id") for sc in spec.get("scenes") or []]
    out = {sid: p["role"] for sid, p in plan.items()
           if isinstance(p, dict) and p.get("role") and sid in ids}
    if not out:
        raise CutdownError(
            "cutdown_needs_roles",
            "spec.direction.scenes marks no role, so there is no arc to preserve (the cutdown would keep or "
            "drop scenes by position alone)",
            hint='plan each scene first: direction.scenes = {"<id>": {"role": "hook"|"proof"|"result"|"cta"|...}}')
    return out


def _voice_s(sc: dict, man: dict) -> float:
    """Seconds this scene's voice needs: the measured WAV when the manifest has it, else the read time of
    the line as written. Never less than either -- the narration is not touched by a cutdown."""
    a = man.get(sc.get("id")) or {}
    dur = float(a.get("duration_s") or 0.0)
    if dur:  # the timeline stretches the scene to the WAV, which already paid the tail and the pause
        return dur + S.AUDIO_TAIL + S._num(sc, "pause_after_s")
    narr = sc.get("narration")
    words = len(S.spoken_text(narr).split()) if isinstance(narr, str) else 0
    return words / S.READ_WPS + S.AUDIO_TAIL if words else 0.0


def _span(spec: dict, scenes: list[dict], man: dict) -> float:
    """Seconds these scenes run: what each one holds, floored by what the voice owes a scene that has no
    WAV yet, minus the overlaps the transitions save -- never less than the timeline's own total."""
    if not scenes:
        return 0.0
    n, trans = len(scenes), float(spec.get("transition_s") or 0.0)
    # a scene that is not last pays for the transition it is overlapped by, exactly as timeline() does
    total = sum(max(float(sc.get("duration_s") or 0.0), _voice_s(sc, man) + (trans if i < n - 1 else 0.0))
                for i, sc in enumerate(scenes))
    total -= trans * (n - 1)
    try:  # the clock every other tool reads: take it when it is longer (it caps the overlap on short scenes)
        total = max(total, S.timeline({**spec, "scenes": scenes})["frames"] / spec["fps"])
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        pass
    return round(max(0.0, total), 2)


def estimate(spec: dict, man: dict | None = None) -> float:
    """Seconds the spec runs today, with the narration manifest when it exists (`man` lets a caller price
    a spec whose WAVs are cached under another spec_hash, as every cutdown is)."""
    s = S.normalize(spec)
    if man is None:
        man = S.audio_manifest(s).get("scenes") or {}
    return _span(s, s["scenes"], man)


def _order(ids: list[str], rs: dict[str, str]) -> list[str]:
    """The drop queue: implications, the repeated hooks and ctas, the extra value scenes, the problem,
    then the unprotected tail."""
    kept = {sid for sid in ids if rs.get(sid) in KEEP}
    by = defaultdict(list)
    for sid in ids:
        by[rs.get(sid)].append(sid)
    out = list(by["implication"])
    # the role is protected, not every scene that carries it: a second hook or an earlier cta is repetition
    out += by["hook"][1:]  # the first hook is the promise every later beat has to keep
    out += by["cta"][:-1]  # only the last cta closes the video; an earlier one repeats the close
    out += by["value"][1:]  # the first value scene is the pitch; any further one repeats it
    out += by["problem"]
    out += [sid for sid in reversed(ids) if sid not in kept and sid not in out]
    return out


def _promise_kept(ids: list[str], rs: dict[str, str]) -> bool:
    """True when the hook still has a later beat that delivers what it promised (the lint's rule)."""
    for i, sid in enumerate(ids):
        if rs.get(sid) == "hook":
            return any(rs.get(x) in DELIVERS for x in ids[i + 1:])
    return True


def _reason(sid: str, rs: dict[str, str]) -> str:
    return REASONS.get(rs.get(sid), REASONS["other"])


def _prune(spec: dict, ids: list[str]) -> dict:
    """The same spec with only `ids`, and direction.scenes trimmed to match (a plan entry for a scene that
    is gone is a dangling id the linter would warn about)."""
    s = copy.deepcopy(spec)
    s["scenes"] = [sc for sc in s["scenes"] if sc.get("id") in ids]
    plan = S.plan(s)
    if plan and isinstance(s.get("direction"), dict):
        s["direction"]["scenes"] = {k: v for k, v in plan.items() if k in ids}
    return s


def cutdown(spec: dict, target_s: float) -> dict:
    """Fit `spec` into `target_s` seconds by removing scenes, and report every removal with its reason.

    Raises CutdownError(code="cutdown_infeasible", min_s=...) when the protected beats alone are longer
    than the target, and code="hook_promise_unkept" when the only way to fit is to leave a hook that kept
    its promise without the beat that proved it. The returned spec has a different spec_hash (its
    cues/plan are recomputed) and its own /work/audio/<hash>/ dir, so narrate() speaks the kept lines
    again -- the same text, never a faster one. `duration_basis` says where `duration_s` was measured:
    "master" before the cut is narrated (the master manifest's WAVs, the closest clock there is),
    "spec" once the cut has a manifest of its own."""
    s = S.normalize(spec)
    target = float(target_s)
    if not target > 0:
        raise ValueError(f"target_s must be a positive number of seconds (got {target_s!r})")
    rs = roles(s)
    ids = [sc.get("id") for sc in s["scenes"]]
    man = S.audio_manifest(s).get("scenes") or {}
    before = _span(s, s["scenes"], man)
    kept, total, removed, blocked = list(ids), before, [], []
    promised = _promise_kept(kept, rs)  # a spec that already breaks the promise is not made worse here
    for sid in _order(ids, rs):
        if total <= target:
            break
        rest = [x for x in kept if x != sid]
        if promised and not _promise_kept(rest, rs):  # the proof of the hook's promise: cutting it would lie
            blocked.append(sid)
            continue
        kept, total = rest, _span(s, [sc for sc in s["scenes"] if sc.get("id") in rest], man)
        promised = promised and _promise_kept(rest, rs)
        removed.append({"scene": sid, "reason": _reason(sid, rs)})
    if total > target and blocked:
        raise CutdownError(
            "hook_promise_unkept",
            f"{total:g}s is the shortest cut that keeps the hook's promise: dropping {', '.join(blocked)} "
            f"leaves the hook promising something no surviving scene proves (target {target:g}s)",
            min_s=total, kept=[x for x in kept if rs.get(x) in KEEP],
            hook=[x for x in kept if rs.get(x) == "hook"])
    if total > target:
        raise CutdownError(
            "cutdown_infeasible",
            f"{total:g}s is the shortest honest cut ({', '.join(f'{x} {rs.get(x)}' for x in kept)}); the "
            f"narration is never sped up, so {target:g}s is not in this script -- write a shorter one",
            min_s=total, kept=kept)
    out = _prune(s, kept)
    own = S.audio_manifest(out).get("scenes") or {}
    if own:  # this cut was narrated once already: its own WAVs are the clock, not the master's
        total, basis = _span(out, out["scenes"], own), "spec"
    else:  # pre-narrate: these seconds are the master manifest's estimate for the same lines
        basis = "master"
    return {"spec": out, "removed": removed, "duration_s": total, "duration_basis": basis,
            "target_s": round(target, 2), "before_s": before, "kept": kept,
            "roles": {sid: rs[sid] for sid in kept}, "lint": S.lint(out)}
