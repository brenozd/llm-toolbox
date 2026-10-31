"""Narration cues: when is each word said, so a bullet can appear as the voice reaches it.

Kokoro gives no timestamps, so this *estimates* them: the real pauses in the WAV pin the phrase
boundaries, and inside a phrase the syllables share the time. Measured against faster-whisper on two
Kokoro sentences the start of a word is off by ~100-200 ms (median 97-146, p95 201-383): good enough
to land a reveal on the right phrase, not to promise word-exact sync. `align` is always "estimated".
"""
from __future__ import annotations

import array
import re
import unicodedata
import wave
from pathlib import Path

WIN_S = 0.01
SILENCE_DB = -38.0  # relative to int16 full scale
MIN_PAUSE_S = 0.12
ANCHOR_WINDOW_S = 0.6  # a pause further than this from where the text puts the boundary is not that boundary
DEFAULT_LEAD_MS = 120


def _norm(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.lower())
    return re.sub(r"[^\w]", "", "".join(c for c in w if not unicodedata.combining(c)))


def _syllables(w: str) -> int:
    return max(1, len(re.findall(r"[aeiouyáéíóúâêôãõàü]+", w.lower())))


def speech_span(path: str | Path) -> tuple[float, float, list[tuple[float, float]]]:
    """(first sound, last sound, internal pauses) of a mono 16-bit WAV, from a 10 ms RMS envelope."""
    with wave.open(str(path), "rb") as w:
        sr, raw = w.getframerate(), w.readframes(w.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw[: len(raw) // 2 * 2])
    n = max(1, int(sr * WIN_S))
    floor = (10 ** (SILENCE_DB / 20) * 32768) ** 2
    quiet = [sum(x * x for x in pcm[i:i + n]) / n < floor for i in range(0, len(pcm) - n + 1, n)]
    loud = [i for i, q in enumerate(quiet) if not q]
    if not loud:
        return 0.0, len(pcm) / sr, []
    a, b = loud[0], loud[-1] + 1
    pauses, i = [], a
    while i < b:
        if quiet[i]:
            j = i
            while j < b and quiet[j]:
                j += 1
            if (j - i) * WIN_S >= MIN_PAUSE_S:
                pauses.append((i * WIN_S, j * WIN_S))
            i = j
        else:
            i += 1
    return a * WIN_S, b * WIN_S, pauses


def align(text: str, path: str | Path, spoken=lambda w: w) -> list[dict]:
    """[{w, start_s, end_s}] for every word of `text`. `spoken` maps a written word to what is said
    (spec.say), so a long identifier gets the time of its spoken form."""
    toks = text.split()
    if not toks:
        return []
    lead, end, pauses = speech_span(path)
    wt = [_syllables(spoken(t)) for t in toks]
    total = float(sum(wt))
    ends, acc = [], 0.0
    for x in wt:
        acc += x
        ends.append(lead + (end - lead) * acc / total)
    anchors, used = [], -1  # (last word of the phrase, pause start, pause end), in order
    for k, t in enumerate(toks[:-1]):
        if not re.search(r"[.!?,;:]$", t):
            continue
        best = min(((abs((a + b) / 2 - ends[k]), a, b) for a, b in pauses if a > used), default=None)
        if best and best[0] <= ANCHOR_WINDOW_S:
            anchors.append((k, best[1], best[2]))
            used = best[1]
    spans, first, t0 = [], 0, lead
    for k, a, b in anchors:
        spans.append((first, k + 1, t0, a))
        first, t0 = k + 1, b
    spans.append((first, len(toks), t0, end))
    out = []
    for lo, hi, s, e in spans:
        tot, acc = float(sum(wt[lo:hi])) or 1.0, 0.0
        for i in range(lo, hi):
            out.append({"w": toks[i], "start_s": round(s + (e - s) * acc / tot, 3),
                        "end_s": round(s + (e - s) * (acc + wt[i]) / tot, 3)})
            acc += wt[i]
    return out


def find(words: list[dict], on: str) -> list[int]:
    """Indexes of every word where the phrase `on` starts (accents, case and punctuation ignored)."""
    want = [n for n in (_norm(x) for x in on.split()) if n]
    have = [_norm(x["w"]) for x in words]
    if not want:
        return []
    return [i for i in range(len(have) - len(want) + 1) if have[i:i + len(want)] == want]


def delays(sc: dict, words: list[dict], voice_off_s: float, fps: int) -> dict[int, int]:
    """{item index: frames after the scene starts} for every cue that names a phrase said exactly once.
    Anything else is left out, so the item keeps the delay it always had."""
    out = {}
    for c in sc.get("cues") or []:
        if not isinstance(c, dict) or not isinstance(c.get("on"), str) or not isinstance(c.get("item"), int):
            continue
        hit = find(words, c["on"])
        if len(hit) != 1:
            continue
        lead = c["lead_ms"] if isinstance(c.get("lead_ms"), (int, float)) else DEFAULT_LEAD_MS
        out[c["item"]] = max(0, round((voice_off_s + words[hit[0]]["start_s"] - lead / 1000) * fps))
    return out


def times(sc: dict, words: list[dict], voice_start_s: float) -> dict[int, float]:
    """{cue index: absolute seconds the voice reaches the cue's phrase}, only for a phrase said exactly once
    (what scene.sfx `at: "cue:N"` points at)."""
    out = {}
    for n, c in enumerate(sc.get("cues") or []):
        if isinstance(c, dict) and isinstance(c.get("on"), str):
            hit = find(words, c["on"])
            if len(hit) == 1:
                out[n] = voice_start_s + words[hit[0]]["start_s"]
    return out
