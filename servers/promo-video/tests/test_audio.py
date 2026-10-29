import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from promo_video_mcp import audio as A, config, music as M, spec as S

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


def test_norm_chain_uses_the_measured_offset_and_targets_minus_16():
    chain = A.norm_chain({"input_i": -22.5, "input_tp": -3.2, "input_lra": 4.0,
                          "input_thresh": -32.5, "target_offset": 6.5})
    assert "I=-16.0" in chain and "TP=-2.0" in chain and "linear=true" in chain and "offset=6.5" in chain
    assert "measured_I=-22.5" in chain
    assert A.norm_chain({}).startswith("loudnorm=I=-16.0")  # a failed first pass still normalises


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
    ok = {"integrated_lufs": -16.4, "lra_lu": 3.0, "true_peak_db": -1.9}
    assert A.loudness_findings(ok, True, []) == []
    codes = [f["code"] for f in A.loudness_findings({"integrated_lufs": -13.0, "true_peak_db": 0.2}, True, [])]
    assert codes == ["loudness", "true_peak"]
    assert A.loudness_findings(None, True, [])[0]["code"] == "no_loudness"
    long = [{"start_s": 4.0, "end_s": 9.0, "duration_s": 5.0}]
    assert A.loudness_findings(ok, True, long)[0]["code"] == "long_silence"
    assert A.loudness_findings(ok, False, long) == []  # a silent stretch is fine without a voice-over


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def _tone(path: Path, seconds: float, freq: int = 440, gain: str = "-6dB") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-af", f"volume={gain}", str(path)], check=True)
    return path


def test_build_loops_the_bed_to_the_picture_length(work):
    """The bundled track in a 12 s video: trimmed to the picture, at the level the spec asked for."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    track = M.get("chill-main-menu") or M.tracks()[0]
    s = S.normalize({"fps": 10, "lang": "pt-BR", "music": {"id": track["id"], "volume_db": -6, "duck": 20},
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


def test_mux_delivers_the_whole_soundtrack_at_minus_16_lufs(work):
    """Two-pass loudnorm + AAC mux on a real file: the *muxed* audio, not the intermediate WAV, is what
    the delivery bar is measured on."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    mp4 = work / "pic.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=4",
                    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    track = M.get("chill-main-menu") or M.tracks()[0]
    s = S.normalize({"music": {"id": track["id"], "volume_db": -30, "duck": 12},
                     "scenes": [{"id": "a", "type": "title", "title": "a", "duration_s": 4,
                                 "narration": "Uma fala."}]})
    voice = _tone(work / "voice.wav", 4.0, 440, "-30dB")  # quiet inputs: loudnorm has to lift the mix
    rec = A.mux(mp4, s, voice, 4.0)
    assert rec["voice"] is True and rec["ducked"] is True and rec["loudnorm"]["input_i"] < -30  # pass 1 measured
    m = A.measure_r128(str(mp4))
    assert abs(m["integrated_lufs"] - A.TARGET_I) <= A.I_TOL
    assert m["true_peak_db"] <= A.TP_LIMIT
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                   "stream=codec_name:format=duration", "-of", "json", str(mp4)],
                                  capture_output=True, text=True, check=True).stdout)
    assert j["streams"][0]["codec_name"] == "aac"
    assert abs(float(j["format"]["duration"]) - 4.0) < 0.1  # audio as long as the picture
