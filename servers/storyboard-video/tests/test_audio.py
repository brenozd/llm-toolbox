import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from storyboard_video_mcp import audio as A, config, spec as S

SUMMARY = """[Parsed_ebur128_0 @ 0x1] t: 4.9   TARGET:-23 LUFS  I: -27.8 LUFS
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -16.3 LUFS
    Threshold: -26.3 LUFS

  Loudness range:
    LRA:         3.1 LU
    Threshold: -36.3 LUFS
    LRA low:   -18.0 LUFS
    LRA high:  -14.9 LUFS

  True peak:
    Peak:       -1.8 dBFS
"""


def test_parse_ebur128_reads_the_summary_not_the_progress_lines():
    m = A.parse_ebur128(SUMMARY)
    assert m == {"integrated_lufs": -16.3, "lra_lu": 3.1, "true_peak_db": -1.8}
    assert A.parse_ebur128("no summary here") is None
    assert A.parse_ebur128(SUMMARY.replace("-1.8 dBFS", "-inf dBFS"))["true_peak_db"] is None


def test_mix_graph_ducks_the_bed_under_the_voice():
    g = A.mix_graph(20.0, voice=True, has_bed=True, volume_db=-18, duck_db=12)
    assert "sidechaincompress" in g and "amix=inputs=2" in g
    assert "afade=t=in" in g and "afade=t=out" in g and "atrim=0:20.000" in g
    assert "volume=-18.00dB" in g
    assert g.endswith("atrim=0:20.000,asetpts=N/SR/TB[out]")
    # the voice is only the sidechain key: it is split, never compressed
    assert "asplit=2[voice][key]" in g and "[ducked][voice]amix" in g


def test_no_narration_means_a_plain_gain_no_ducking():
    g = A.mix_graph(12.0, voice=False, has_bed=True, volume_db=-20)
    assert "sidechaincompress" not in g and "amix" not in g
    assert "volume=-20.00dB" in g and "[out]" in g


def test_deeper_duck_means_a_higher_ratio():
    def ratio(d):
        return float(A.duck_chain(d).split("ratio=")[1].split(":")[0])
    assert ratio(0) == 1.2  # clamped floor: "no ducking" is still a valid filter
    assert ratio(6) < ratio(12) < ratio(24)


def test_fades_never_outlast_a_short_mix():
    g = A.mix_graph(2.0, voice=True, has_bed=True)
    assert "afade=t=in:st=0:d=0.500" in g  # 1.5 s fade clamped to a quarter of a 2 s mix


def test_parse_loudnorm_json_takes_the_last_measurement_block():
    err = '{"input_i":"-30.0","input_tp":"-1.0","input_lra":"2.0","input_thresh":"-40.0","target_offset":"0.1"}\n' \
          '{"input_i":"-22.5","input_tp":"-3.2","input_lra":"4.0","input_thresh":"-32.5","target_offset":"6.5"}\n'
    ln = A.parse_loudnorm_json(err)
    assert ln["input_i"] == -22.5 and ln["target_offset"] == 6.5
    assert A.parse_loudnorm_json("nothing") == {}


def test_norm_chain_uses_the_measured_offset_and_targets_the_default_minus_14():
    chain = A.norm_chain({"input_i": -18.0, "input_tp": -8.0, "input_lra": 4.0,
                          "input_thresh": -28.0, "target_offset": 0.5})
    assert "I=-14.0" in chain and "TP=-1.5" in chain and "linear=true" in chain and "offset=0.5" in chain
    assert "measured_I=-18.0" in chain and "alimiter" not in chain  # 4 dB of gain fits under the ceiling
    assert A.norm_chain({}).startswith("loudnorm=I=-14.0")  # a failed first pass still normalises
    assert A.TARGET_I == A.DEFAULT_TARGET_I  # the old constant stays an alias of the default


@pytest.mark.parametrize("target", [-16.0, -14.0])
def test_norm_chain_takes_the_target_as_a_parameter(target):
    chain = A.norm_chain({"input_i": -22.5, "input_tp": -18.0, "input_lra": 4.0,
                          "input_thresh": -32.5, "target_offset": 6.5}, target)
    assert f"I={target:.1f}" in chain and "linear=true" in chain and "measured_TP=-18.0" in chain
    assert A.norm_chain({}, target).startswith(f"loudnorm=I={target:.1f}")  # a failed first pass too


def test_the_limiter_only_goes_in_when_the_gain_would_overshoot_the_ceiling():
    """crest 13.4 dB: the gain to -16 lands at -2.35 dBTP, the gain to -14 at -0.34 -- over the -1.5
    ceiling, where loudnorm abandons linear=true (see the ffmpeg test below)."""
    ln = {"input_i": -18.0, "input_tp": -4.0, "input_lra": 8.4, "input_thresh": -30.0, "target_offset": 0.75}
    assert A.limiter_db(ln, -16.0) is None
    assert A.limiter_db(ln, -14.0) == pytest.approx(-5.5)  # peaks clamped at -5.5, +4 dB of gain -> -1.5
    assert A.limiter_db({}, -14.0) is None  # no measurement: nothing to reason about
    chain = A.norm_chain(ln, -14.0)
    assert chain.startswith("alimiter=limit=0.5309:level=false,loudnorm=I=-14.0")  # 10 ** (-5.5/20)
    assert "measured_TP=-5.5" in chain  # the peak the pass will really see after limiting
    # a mix that would have to be crushed to fit keeps loudnorm's dynamic mode instead of being squashed
    crushed = {**ln, "input_i": -40.0, "input_tp": -6.0}
    bursty = {**ln, "input_i": -20.0, "input_tp": -0.45}  # crest 19.5: 5 dB of shaving undershoots the target
    assert A.limiter_db(bursty, -14.0) is None
    assert A.limiter_db(crushed, -14.0) is None
    assert "alimiter" not in A.norm_chain(crushed, -14.0)


def test_mux_command_copies_the_picture_and_encodes_aac_192k():
    cmd = A.mux_cmd(Path("/w/a.mp4"), Path("/w/mix.wav"), 12.0, "loudnorm")
    s = " ".join(cmd)
    assert "-c:v copy" in s and "-c:a aac" in s and "-b:a 192k" in s and "-t 12.000" in s


def test_parse_silences_closes_an_open_silence_at_the_end():
    err = ("[silencedetect @ 0x1] silence_start: 1.5\n[silencedetect @ 0x1] silence_end: 2.5 | "
           "silence_duration: 1\n[silencedetect @ 0x1] silence_start: 9.0\n")
    sil = A.parse_silences(err, 10.0)
    assert [(s["start_s"], s["end_s"]) for s in sil] == [(1.5, 2.5), (9.0, 10.0)]
    assert sil[0]["duration_s"] == 1.0


def test_loudness_findings_enforce_the_delivery_bar():
    ok = {"integrated_lufs": -14.2, "lra_lu": 3.0, "true_peak_db": -1.9}
    assert A.loudness_findings(ok, True, []) == []
    codes = [f["code"] for f in A.loudness_findings({"integrated_lufs": -11.0, "true_peak_db": 0.2}, True, [])]
    assert codes == ["loudness", "true_peak"]
    assert A.loudness_findings(None, True, [])[0]["code"] == "no_loudness"
    long = [{"start_s": 4.0, "end_s": 9.0, "duration_s": 5.0}]
    assert A.loudness_findings(ok, True, long)[0]["code"] == "long_silence"
    assert A.loudness_findings(ok, False, long) == []  # a silent stretch is fine without a voice-over
    # the bar follows the target the spec asked for: -16.4 is fine for a -16 mix, an error for a -14 one
    assert A.loudness_findings({"integrated_lufs": -16.4, "true_peak_db": -2.0}, True, [], -16.0) == []
    assert [f["code"] for f in A.loudness_findings({"integrated_lufs": -16.4, "true_peak_db": -2.0}, True, [])]
    assert "-16 LUFS" in A.loudness_findings({"integrated_lufs": -12.0}, True, [], -16.0)[0]["message"]


def test_the_target_comes_from_the_spec_and_must_be_in_range():
    assert A.target_lufs({}) == A.DEFAULT_TARGET_I == -14.0
    assert A.target_lufs({"audio": {"target_lufs": -16}}) == -16.0
    assert A.target_lufs({"audio": {"voice": "music"}}) == -14.0  # other audio keys are not our business
    for bad in (-24.5, -11.9, 0, True, "quiet", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            A.target_lufs({"audio": {"target_lufs": bad}})
    with pytest.raises(ValueError):
        A.target_lufs({"audio": "-14"})  # not an object at all
    # every entry point validates the same way, so a bad target cannot reach ffmpeg
    for call in (lambda: A.norm_chain({}, -30),
                 lambda: A.loudness_findings({"integrated_lufs": -14.0}, True, [], -11.0),
                 lambda: A.measure_loudnorm("/dev/null", -25),
                 lambda: A.mux(Path("/w/a.mp4"), {}, None, 1.0, -25),
                 lambda: A.check("/w/a.mp4", 1.0, False, -25),
                 lambda: A.credits_text({}, -25)):
        with pytest.raises(ValueError):
            call()
    # -24 and -12 are the ends of the band, so both are allowed
    assert A.target_lufs({"audio": {"target_lufs": -24}}) == -24.0
    assert A.target_lufs({"audio": {"target_lufs": -12}}) == -12.0


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def _tone(path: Path, seconds: float, freq: int = 440, gain: str = "-6dB") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-af", f"volume={gain}", str(path)], check=True)
    return path


def test_build_loops_the_bed_to_the_picture_length(work):
    """A staged track in a 12 s video: trimmed to the picture, at the level the spec asked for."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    track = _tone(work / "track.wav", 8.0, 220)  # shorter than the video: it has to loop
    s = S.normalize({"fps": 10, "lang": "pt-BR",
                     "music": {"path": str(track), "license": "CC0 1.0", "volume_db": -6, "duck": 20},
                     "scenes": [{"id": "a", "type": "title", "title": "a", "duration_s": 12,
                                 "narration": "Uma fala."}]})
    voice = _tone(work / "voice.wav", 3.0, 440)  # speech from 0 to 3 s, bed alone afterwards
    out = A.build(s, voice, 12.0, work / "mix.wav")
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 48000 and w.getnchannels() == 2
        assert abs(w.getnframes() / 48000 - 12.0) < 0.1  # exactly as long as the picture
    # a shorter video cuts the same track instead of letting it run past the picture
    A.build(s, None, 3.0, work / "bed.wav")
    with wave.open(str(work / "bed.wav"), "rb") as w:
        assert abs(w.getnframes() / 48000 - 3.0) < 0.1


def test_duck_chain_lowers_the_bed_while_the_key_sounds(work):
    """The chain itself: the bed drops by roughly `duck` dB for as long as the sidechain key is loud."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    def run(ducked: bool) -> Path:
        if ducked:
            g = (f"[0:a]volume=-12dB[bed];[1:a]apad,atrim=0:6,asplit=2[voice][key];"
                 f"[bed][key]{A.duck_chain(24)}[ducked];[ducked][voice]amix=inputs=2:normalize=0[out]")
        else:
            g = "[0:a]volume=-12dB[bed];[1:a]apad,atrim=0:6[voice];[bed][voice]amix=inputs=2:normalize=0[out]"
        o = work / f"d{ducked}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
                        "-f", "lavfi", "-i", "sine=frequency=3000:duration=2", "-filter_complex", g,
                        "-map", "[out]", "-ar", "48000", "-ac", "2", str(o)], check=True)
        return o

    def bed_only(p, t0, t1):
        # 3 kHz key out of band: measure the 300 Hz bed alone, low-passed away from the voice
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af",
                            f"atrim={t0}:{t1},lowpass=f=500,volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
        return float(r.stderr.split("mean_volume:")[1].split("dB")[0])

    plain, ducked = run(False), run(True)
    assert bed_only(ducked, 0.5, 2.0) < bed_only(plain, 0.5, 2.0) - 6  # ducked under the key
    assert abs(bed_only(ducked, 3.0, 5.0) - bed_only(plain, 3.0, 5.0)) < 1.5  # back up once it stops


def test_build_without_music_or_voice_is_silence(work):
    s = S.normalize({"scenes": [{"id": "a", "type": "title", "title": "a"}]})
    assert A.build(s, None, 3.0, work / "mix.wav") is None


@pytest.mark.parametrize("target", [None, -16.0, -14.0])
def test_mux_delivers_the_whole_soundtrack_at_the_target(work, target):
    """Two-pass loudnorm + AAC mux on a real file: the *muxed* audio, not the intermediate WAV, is what
    the delivery bar is measured on. `target=None` means "whatever the spec asks for" (the default)."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    mp4 = work / "pic.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=4",
                    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    track = _tone(work / "track.wav", 6.0, 220)
    audio = {} if target is None else {"target_lufs": target}
    s = S.normalize({"audio": audio,
                     "music": {"path": str(track), "license": "CC0 1.0", "volume_db": -30, "duck": 12},
                     "scenes": [{"id": "a", "type": "title", "title": "a", "duration_s": 4,
                                 "narration": "Uma fala."}]})
    voice = _tone(work / "voice.wav", 4.0, 440, "-30dB")  # quiet inputs: loudnorm has to lift the mix
    rec = A.mux(mp4, s, voice, 4.0)
    want = A.DEFAULT_TARGET_I if target is None else target
    assert rec["target_lufs"] == want
    assert rec["voice"] is True and rec["ducked"] is True and rec["loudnorm"]["input_i"] < -30  # pass 1 measured
    m = A.measure_r128(str(mp4))
    assert abs(m["integrated_lufs"] - want) <= A.I_TOL
    assert m["true_peak_db"] <= A.TP_LIMIT
    assert A.loudness_findings(m, True, [], want) == []  # the spec's own bar accepts the delivery
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                   "stream=codec_name:format=duration", "-of", "json", str(mp4)],
                                  capture_output=True, text=True, check=True).stdout)
    assert j["streams"][0]["codec_name"] == "aac"
    assert abs(float(j["format"]["duration"]) - 4.0) < 0.1  # audio as long as the picture


def _crest_mix(work, seconds: float = 8.0) -> Path:
    """A voice+bed mix with the crest factor of a real read (TP - I around 13 dB) levelled to ~-20 LUFS:
    loudnorm needs a realistic ~6 dB of gain, and that crest sits inside the -16 linear window but
    outside the -14 one (13.7 > 12.5)."""
    def tone(name, freq, chain):
        p = work / name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration={seconds}", "-af", chain, str(p)], check=True)
        return p
    bed_ = tone("bed.wav", 220, "volume=-16dB")
    voice_ = tone("vox.wav", 180, "volume='if(lt(mod(t,4),2),0.5,0)':eval=frame,volume=-8dB")
    clicks = tone("clicks.wav", 2500, "volume='if(lt(mod(t,3),0.02),1,0)':eval=frame,volume=-4dB")  # plosives
    mix = work / "crest.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bed_), "-i", str(voice_), "-i", str(clicks),
                    "-filter_complex",
                    "[0:a]aresample=48000,aformat=channel_layouts=stereo[bed];"
                    "[1:a]aresample=48000,aformat=channel_layouts=stereo[vox];"
                    "[2:a]aresample=48000,aformat=channel_layouts=stereo[cl];"
                    "[bed][vox][cl]amix=inputs=3:normalize=0:dropout_transition=0[out]",
                    "-map", "[out]", "-ar", "48000", "-ac", "2", str(mix)], check=True)
    m = A.measure_r128(str(mix))
    levelled = work / "crest20.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mix), "-af",
                    f"volume={-20.0 - m['integrated_lufs']:.2f}dB", "-ar", "48000", "-ac", "2", str(levelled)],
                   check=True)
    return levelled


def test_minus_14_needs_the_limiter_to_keep_loudnorm_linear(work):
    """The risk the phase plan flags: at -14 the linear window is 2 dB narrower, so a mix whose peaks
    survive -16 makes loudnorm switch to its dynamic mode (pumping) -- measured, not assumed."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    mix = _crest_mix(work)
    ln = A.measure_loudnorm(str(mix))
    crest = ln["input_tp"] - ln["input_i"]
    assert 12.5 < crest < 14.5, f"crest {crest:.1f} dB is not the band this test is about"
    assert A.limiter_db(ln, -16.0) is None  # -16 still fits the linear window
    lim = A.limiter_db(ln, -14.0)
    assert lim is not None and lim >= A.LIMIT_FLOOR_DB

    def pass2(pre: str, peak: float) -> dict:
        chain = (f"{pre}loudnorm=I=-14.0:TP={A.TARGET_TP}:LRA={A.TARGET_LRA}:measured_I={ln['input_i']}"
                 f":measured_TP={peak}:measured_LRA={ln['input_lra']}:measured_thresh={ln['input_thresh']}"
                 f":offset={ln['target_offset']}:linear=true:print_format=json")
        r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(mix), "-af", chain,
                            "-f", "null", "-"], capture_output=True, text=True)
        blocks = [json.loads(m.group(0)) for m in re.finditer(r"\{[^{}]*\"output_i\"[^{}]*\}", r.stderr, re.S)]
        return blocks[-1] if blocks else {}

    blind = pass2("", ln["input_tp"])  # loudnorm alone: it over-shoots the ceiling, so it goes dynamic
    assert blind["normalization_type"] == "dynamic"
    kept = pass2(f"alimiter=limit={10 ** (lim / 20):.4f}:level=false,", lim)
    assert kept["normalization_type"] == "linear"  # the mitigation the shipped chain applies
    assert abs(float(kept["output_i"]) + 14.0) <= A.I_TOL
    assert float(kept["output_tp"]) <= A.TARGET_TP + 0.1
    assert A.norm_chain(ln, -14.0).startswith(f"alimiter=limit={10 ** (lim / 20):.4f}:level=false,loudnorm=")
