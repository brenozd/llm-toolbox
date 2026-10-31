"""Pocket TTS voice catalogue and the ranking behind `suggest_voices`.

Pocket TTS has no speed/emotion knob: the voice *is* the pace and the expressiveness, so the skill asks
the user three things (pitch, emotion, pace; optionally flow) and this module ranks the voices against
the answers. Numbers are measured on the generated audio, per language:
  en    from the Kyutai voice study (Whisper small.en, pyin F0), 21 voices;
  pt-BR only `rafael` (native); the English voices reading Portuguese were dropped.
NOT measured: naturalness, accent, whether the intonation is *right* -- only listening settles that.
`jean` and `cosette` (CC BY-NC) are left out on purpose: this tool makes product videos.
"""
from __future__ import annotations

# spec.lang -> --language of the pocket-tts binary
LANG_TAG = {"pt-BR": "portuguese", "en": "english"}
# rafael is the native pt-BR voice; george is "average in everything" in the en study.
DEFAULT = {"pt-BR": "rafael", "en": "george"}

# voice: (license, f0_hz, en (words/s, pause %, intonation sd st) | None, pt-BR (same triple) | None)
# pt-BR keeps only `rafael`, the one native speaker: the others are English speakers reading Portuguese.
VOICES = {
    "marius": ("CC0", 133, (6.0, 30.7, 8.03), None),
    "stuart_bell": ("CC0", 140, (4.38, 23.3, 6.77), None),
    "javert": ("CC0", 80, (4.24, 34.6, 3.9), None),
    "peter_yearsley": ("CC0", 93, (5.0, 23.1, 3.86), None),
    "george": ("CC-BY-4.0", 119, (5.21, 25.8, 3.47), None),
    "bill_boerst": ("CC0", 117, (5.0, 28.2, 2.93), None),
    "charles": ("CC-BY-4.0", 79, (4.88, 26.7, 2.77), None),
    "michael": ("CC-BY-4.0", 94, (4.79, 26.2, 2.4), None),
    "paul": ("CC-BY-4.0", 111, (4.88, 30.7, 2.06), None),
    "eve": ("CC-BY-4.0", 186, (5.06, 22.0, 5.07), None),
    "mary": ("CC-BY-4.0", 179, (4.73, 19.8, 5.0), None),
    "anna": ("CC-BY-4.0", 193, (4.59, 21.5, 4.71), None),
    "alba": ("CC-BY-4.0", 125, (4.76, 15.1, 4.13), None),
    "vera": ("CC-BY-4.0", 174, (4.81, 24.3, 3.91), None),
    "azelma": ("CC-BY-4.0", 213, (4.39, 17.3, 3.78), None),
    "caro_davy": ("CC0", 162, (4.41, 25.6, 3.61), None),
    "jane": ("CC-BY-4.0", 201, (4.58, 20.5, 3.56), None),
    "eponine": ("CC-BY-4.0", 158, (4.49, 24.0, 3.49), None),
    "fantine": ("CC-BY-4.0", 200, (4.97, 24.1, 3.15), None),
    "rafael": ("unverified", 152, None, (3.79, 18.3, 2.89)),  # pt-only voice, not in the en study
}

# answer -> target percentile (0 = lowest of the catalogue, 1 = highest) on one measured column
ASK = {
    "pitch": (0, {"low": 0.0, "high": 1.0}),  # f0_hz: deeper / higher voice (never "gender": F0 is only a proxy)
    "pace": (1, {"slow": 0.0, "normal": 0.5, "fast": 1.0}),  # words per second
    "flow": (2, {"smooth": 0.0, "breathy": 1.0}),  # % of the time in pauses >= 150 ms
    "emotion": (3, {"calm": 0.0, "neutral": 0.5, "expressive": 1.0}),  # intonation sd in semitones
}

LEGEND = {
    "words_per_s": "higher = faster; ~3.3 calm .. ~3.8 brisk in pt-BR, ~4.4 calm .. ~6 rushed in en",
    "pause_pct": "share of the speech in silences >= 150 ms: high = halting/breathy, low = smooth",
    "intonation_sd": "pitch variation in semitones: ~2 monotone, 5-8 expressive; very high may sound theatrical",
    "f0_hz": "median pitch; only a proxy for a deeper/higher voice, not a gender",
}


# who to credit for a CC BY voice (voice credit = the licence condition, like a music credit)
SOURCE = {"alba": "Alba MacKenna"}
SOURCE_DEFAULT = "CSTR VCTK Corpus, University of Edinburgh"


def _f0(name: str, lang: str) -> int:
    return VOICES[name][1]


def _row(name: str, lang: str):
    v = VOICES[name]
    return v[2] if lang == "en" else v[3]


def _metrics(name: str, lang: str) -> dict[str, float]:
    wps, pause, sd = _row(name, lang)
    return {"f0_hz": _f0(name, lang), "words_per_s": wps, "pause_pct": pause, "intonation_sd": sd}


def credits(spec: dict) -> list[str]:
    """CREDITS.txt lines for the CC BY voices the narration of `spec` uses (empty without narration)."""
    scenes = [sc for sc in spec.get("scenes") or [] if isinstance(sc, dict) and sc.get("narration")]
    if not scenes or spec.get("lang") not in DEFAULT:
        return []
    used = {sc.get("voice") or spec.get("voice") or DEFAULT[spec["lang"]] for sc in scenes}
    return [f"- Voice \"{v}\" · {SOURCE.get(v, SOURCE_DEFAULT)} · CC BY 4.0 · https://huggingface.co/kyutai/tts-voices"
            for v in sorted(x for x in used if isinstance(x, str) and VOICES.get(x, ("",))[0] == "CC-BY-4.0")]


def names(lang: str | None = None) -> list[str]:
    return [n for n in VOICES if lang is None or _row(n, lang) is not None]


def suggest(lang: str, n: int = 3, **answers: str | None) -> dict:
    """Rank the voices of `lang` against the answers (pitch, pace, flow, emotion; None/"any" = no opinion).
    Score = mean distance, in percentile of the catalogue, to each answered target; the lowest wins."""
    if lang not in LANG_TAG:
        raise ValueError(f"lang must be one of {sorted(LANG_TAG)} (got {lang!r})")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be an integer >= 1 (got {n!r})")  # more than the pool just returns the pool
    for k in answers:
        if k not in ASK:
            raise ValueError(f"unknown question {k!r}; use {sorted(ASK)}")
    want = {}
    for k, a in answers.items():
        if a in (None, "", "any"):
            continue
        if a not in ASK[k][1]:
            raise ValueError(f"{k} must be one of {sorted(ASK[k][1])} or 'any' (got {a!r})")
        want[k] = ASK[k][1][a]
    pool = names(lang)
    val = lambda k, v: _f0(v, lang) if ASK[k][0] == 0 else _row(v, lang)[ASK[k][0] - 1]
    cols = {k: sorted(val(k, v) for v in pool) for k in ASK}

    def pct(k: str, v: str) -> float:
        x = val(k, v)  # ties share the mean of their ranks, so equal values score equally
        return (cols[k].index(x) + len(cols[k]) - 1 - cols[k][::-1].index(x)) / 2 / max(1, len(pool) - 1)

    def score(v: str) -> float:
        return sum(abs(pct(k, v) - t) for k, t in want.items()) / len(want) if want else 0.0

    ranked = sorted(pool, key=lambda v: (score(v), v != DEFAULT[lang], v))[:n]
    picks = [{"voice": v, "fit": round(1 - score(v), 2), "license": VOICES[v][0],
              "attribution_required": VOICES[v][0] == "CC-BY-4.0", **_metrics(v, lang)} for v in ranked]
    return {"lang": lang, "answers": {k: answers[k] for k in want}, "default": DEFAULT[lang],
            "picks": picks, "legend": LEGEND,
            "caveat": ("pt-BR has a single voice: nothing to rank. " if lang == "pt-BR" else "") + "Naturalness and accent are NOT measured: listen before committing "
                      "(narrate with scratch=true is the cheap way)."}
