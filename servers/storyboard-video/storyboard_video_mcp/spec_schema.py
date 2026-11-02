"""JSON Schema of the video spec, built from spec.py's constants so the contract cannot drift from the lints.
Structural only: the lints (validate_spec) own the semantic rules."""
from __future__ import annotations

from . import spec as S


def schema() -> dict:
    text = {"type": "string"}
    scene = {
        "type": "object", "required": ["id", "type"],
        "properties": {
            "id": {"type": "string", "description": "free text, unique in the spec; the address patch_spec uses"},
            "type": {"enum": sorted(S.TYPES)},
            "duration_s": {"oneOf": [{"type": "number", "minimum": 1.5, "maximum": 12}, {"const": "auto"}],
                           "description": "'auto' = estimated from the narration, then stretched to the measured audio"},
            "narration": text, "title": text, "subtitle": text, "heading": text, "caption": text,
            "items": {"type": "array", "items": text, "maxItems": 5},
            "lines": {"type": "array", "maxItems": 18},
            "evidence": {"type": "string", "pattern": r"^.+:\d+(-\d+)?$", "description": "file:line or file:a-b proving a number"},
            "intent": {"type": "object", "required": ["sees", "understands"],
                       "properties": {"sees": text, "understands": text},
                       "description": "what is on screen / what the viewer should take away"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "storyboard-video spec",
        "type": "object", "required": ["scenes"],
        "properties": {
            "aspect": {"enum": sorted(S.ASPECTS)}, "fps": {"type": "integer", "minimum": 10, "maximum": 60},
            "lang": {"enum": sorted(S.LANGS)}, "say": {"type": "object", "additionalProperties": text},
            "direction": {"type": "object", "properties": {
                **{k: {"enum": sorted(S.DIRECTION_ENUMS[k])} for k in ("purpose", "motion", "audio", "arc")},
                "strict_intent": {"type": "boolean", "description": "every scene must carry an intent"},
                "scenes": {"type": "object", "additionalProperties": {"type": "object", "properties": {
                    "role": {"enum": sorted(S.DIRECTION_ENUMS["role"])}}}}}},
            "scenes": {"type": "array", "minItems": 1, "items": scene},
        },
    }
