"""patch_spec: edit a persisted spec by scene id instead of resending the whole JSON."""
from __future__ import annotations

import copy

from . import spec as S


def _scene(s: dict, sid) -> tuple[int, dict]:
    for i, sc in enumerate(s["scenes"]):
        if sc.get("id") == sid:
            return i, sc
    raise KeyError(f"no scene with id {sid!r}")


def _set(sc: dict, field: str, value) -> None:
    sc[field] = value


def apply(h: str, ops: list[dict], dry_run: bool = True) -> dict:
    """ops: {op: replace|add|remove|move, scene, field?, value?, after?}. `replace` sets scene[field];
    `add` inserts a whole scene (value) after scene `after` (or at the end); `remove` drops a scene and
    its direction.scenes entry; `move` puts scene after `after` (null = first)."""
    s = copy.deepcopy(S.load(h))
    diff = []
    for o in ops:
        op, sid = o.get("op"), o.get("scene")
        if op == "add":
            sc = o.get("value")
            if not isinstance(sc, dict) or not sc.get("id"):
                raise ValueError("add needs value = a scene object with an id")
            at = _scene(s, o["after"])[0] + 1 if o.get("after") else len(s["scenes"])
            s["scenes"].insert(at, sc)
            diff.append(f"+ scene {sc['id']}")
        elif op == "remove":
            i, _ = _scene(s, sid)
            s["scenes"].pop(i)
            (s.get("direction") or {}).get("scenes", {}).pop(sid, None)
            diff.append(f"- scene {sid}")
        elif op == "move":
            i, sc = _scene(s, sid)
            s["scenes"].pop(i)
            at = _scene(s, o["after"])[0] + 1 if o.get("after") else 0
            s["scenes"].insert(at, sc)
            diff.append(f"> scene {sid} after {o.get('after')}")
        elif op == "replace":
            _, sc = _scene(s, sid)
            if not o.get("field"):
                raise ValueError("replace needs field")
            _set(sc, o["field"], o.get("value"))
            diff.append(f"~ {sid}.{o['field']}")
        else:
            raise ValueError(f"op {op!r}: use replace, add, remove or move")
    s = S.normalize(s)
    findings = S.lint(s)
    ok = not any(f["severity"] == "error" for f in findings)
    out = {"status": "ok" if ok else "error", "dry_run": dry_run, "diff": diff, "findings": findings}
    if ok:
        out["new_spec_hash"] = S.spec_hash(s) if dry_run else S.persist(s)
    return out
