"""The documented spec has to be a spec (U6): the model copies `skills/promo-video/SKILL.md` verbatim,
so a `.5` in that block is a parse error before `validate_spec` ever runs (it did: `json.loads` died at
line 8 col 90). Every fenced ```json block of the skill is parsed here, and the `## Spec` block is run
through `normalize` + `lint` -- the two calls `validate_spec` makes -- so an example that only *looks*
like a spec fails in CI instead of in a live session.

The documented example points at placeholder paths (`/music/<id>.mp3`, `/work/captures/<id>/...`), so
the only errors allowed are the ones about those placeholders (`music_path_missing`, `missing_file`) and
only when the message names the `<id>` template. Anything else -- a bad theme, an unknown `type`, a
`duration_s` out of range -- means the doc drifted from the code.

`SKILL.md` lives at the repo root, which is *not* in the image this suite normally runs in. Resolve it
two ways, exactly like `test_plugin_entry.py`: `PROMO_REPO_ROOT` wins, else the repo is assumed above
this file; when neither exists the tests skip. Run inside the image with the repo mounted read-only:

    docker run --rm -v "$PWD:/repo:ro" promo-video-mcp:<key> \\
        python -m pytest -q tests/test_skill_docs.py
"""

import json
import os
import re
from pathlib import Path

import pytest

from promo_video_mcp import config
from promo_video_mcp import spec as S


def _repo_root():
    """`PROMO_REPO_ROOT`, else the checkout above this file -- None when the tests were copied to a
    shallower place (a flat /tests mount), where guessing the root would raise IndexError."""
    if os.environ.get("PROMO_REPO_ROOT"):
        return Path(os.environ["PROMO_REPO_ROOT"])
    here = Path(__file__).resolve()
    return here.parents[3] if len(here.parents) > 3 else None


REPO_ROOT = _repo_root()
SKILL = REPO_ROOT / "skills" / "promo-video" / "SKILL.md" if REPO_ROOT else None

pytestmark = pytest.mark.skipif(
    not (SKILL and SKILL.is_file()),
    reason="no skills/promo-video/SKILL.md under the repo root "
           f"{REPO_ROOT or '(unresolved)'}: mount the repo or set PROMO_REPO_ROOT")

# A fenced block: ```json ... ```, lazily up to the closing fence at the start of a line.
FENCE = re.compile(r"^```json[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
# The errors a placeholder path can legitimately raise, and the template that has to be in the message.
PLACEHOLDER_CODES = {"music_path_missing", "missing_file"}
PLACEHOLDER = "<id>"


def _blocks() -> list[str]:
    return FENCE.findall(SKILL.read_text(encoding="utf-8"))


def test_the_skill_documents_at_least_the_spec_block():
    """A grep-proof that the extractor still sees the block: a fence style change that hid the spec
    from this test would otherwise turn it into a no-op that always passes."""
    assert _blocks(), f"{SKILL} has no ```json block (did the fence or the language tag change?)"


def test_every_json_block_parses():
    for i, raw in enumerate(_blocks(), 1):
        try:
            json.loads(raw)
        except ValueError as e:  # a copy-pasted `.5`/`…`-quote kills validate_spec before lint
            pytest.fail(f"{SKILL.name} ```json block #{i} is not JSON: {e}\n---\n{raw}")


def test_the_documented_spec_lints_clean_outside_the_placeholder_paths(monkeypatch):
    specs = [json.loads(raw) for raw in _blocks()]
    specs = [s for s in specs if isinstance(s, dict) and "scenes" in s]
    assert specs, f"{SKILL} documents no spec block (no ```json object with `scenes`)"

    # `evidence: "README.md:5"` is resolved against the repo (config.REPO = /repo in the image): point
    # it at the checkout under test so the example is judged in the tree it documents.
    monkeypatch.setattr(config, "REPO", REPO_ROOT)
    for raw_spec in specs:
        spec = S.normalize(raw_spec)  # same two calls validate_spec makes, minus persisting the spec
        findings = S.lint(spec)
        errors = [f for f in findings if f["severity"] == "error"]
        stray = [f for f in errors
                 if f["code"] not in PLACEHOLDER_CODES or PLACEHOLDER not in f["message"]]
        assert not stray, f"documented spec has real errors: {stray}"
        # And the placeholder errors are the ones we predicted, not a silent drift of the example.
        assert {f["code"] for f in errors} <= PLACEHOLDER_CODES
