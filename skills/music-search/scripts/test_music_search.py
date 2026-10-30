#!/usr/bin/env python3
"""Offline tests for music_search.py. No network, no ffmpeg.

Run: python3 -I skills/music-search/scripts/test_music_search.py
     (also collectable by pytest: `python3 -m pytest skills/music-search/scripts`)

Recorded fixtures in ./fixtures/ are trimmed real responses (2026-xx): Openverse audio
for "calm ambient", archive.org advancedsearch, ccMixter lic=zero, Commons search.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import music_search as M  # noqa: E402

FIXTURES = HERE / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def stub_http(routes):
    """routes: {url-substring: payload}. Records the URLs that were requested."""
    calls = []

    def fake(url, *, timeout=25, tries=3, binary=False, referer=None):
        calls.append(url)
        for needle, payload in routes.items():
            if needle in url:
                if binary:
                    return payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                return payload if isinstance(payload, str) else json.dumps(payload)
        raise RuntimeError(f"no fixture for {url}")

    return fake, calls


def make_analysis(n=1200, dt=0.1, level=-18.0, centroid=800.0, rolloff=1500.0, peak_every=50):
    frames = []
    for i in range(n):
        frames.append(
            {
                "t": round(i * dt, 3),
                "m": level + (3.0 if i % 400 > 200 else 0.0),
                "i": level,
                "centroid": centroid,
                "rolloff": rolloff,
                "flux": 1.0 if i % peak_every == 0 else 0.01,
            }
        )
    return {"lufs": level, "lra": 6.0, "frames": frames}


class PolicyTests(unittest.TestCase):
    """The table that decides what may reach `mix`."""

    def verdict(self, raw="", url="", version="", **kw):
        lic, ver = M.parse_license(raw, url=url, version=version)
        cand = M._cand(license_id=lic, license_version=ver, license_url=url, source="ia", **kw)
        return M.policy(cand)

    def test_cc0_allows(self):
        got = self.verdict("cc0", "https://creativecommons.org/publicdomain/zero/1.0/", "1.0")
        self.assertEqual(got["verdict"], "allow")
        self.assertEqual(got["license"], "CC0 1.0")
        self.assertFalse(got["attribution_required"])

    def test_pdm_allows(self):
        got = self.verdict("", "https://creativecommons.org/publicdomain/mark/1.0/")
        self.assertEqual(got["verdict"], "allow")
        self.assertEqual(got["license"], "Public Domain Mark 1.0")

    def test_legacy_public_domain_dedication_allows(self):
        got = self.verdict("", "http://creativecommons.org/licenses/publicdomain/")
        self.assertEqual(got["verdict"], "allow")

    def test_by_4_needs_attribution(self):
        got = self.verdict("by", "https://creativecommons.org/licenses/by/4.0/", "4.0")
        self.assertEqual(got["verdict"], "attribution")
        self.assertEqual(got["license"], "CC BY 4.0")
        self.assertTrue(got["attribution_required"])

    def test_by_3_keeps_its_version(self):
        got = self.verdict("", "https://creativecommons.org/licenses/by/3.0/deed.en")
        self.assertEqual(got["verdict"], "attribution")
        self.assertEqual(got["license"], "CC BY 3.0")
        self.assertIn("3.0", got["license_url"])

    def test_by_without_a_version_is_denied(self):
        # Never invent 4.0: an unknown version has no terms to comply with.
        got = self.verdict("by", "")
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "cc_by_version_unknown")

    def test_by_2_5_is_denied(self):
        got = self.verdict("", "https://creativecommons.org/licenses/by/2.5/")
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "cc_by_2.5_unsupported")

    def test_reupload_channel_is_denied(self):
        got = M.policy(M._cand(license_id="cc0", reupload=True, source="web"))
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "reupload_or_mirror")
        self.assertIn("reupload_or_mirror", M.FATAL_REASONS)

    def test_by_sa_denied(self):
        got = self.verdict("by-sa", "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "share_alike_sync")

    def test_nc_denied(self):
        for token in ("by-nc", "by-nc-sa", "by-nc-nd"):
            got = self.verdict(token, f"https://creativecommons.org/licenses/{token}/4.0/")
            self.assertEqual(got["verdict"], "deny", token)
            self.assertIn("non_commercial", got["verdict_reason"], token)

    def test_nd_denied(self):
        got = self.verdict("by-nd", "https://creativecommons.org/licenses/by-nd/4.0/")
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "no_derivatives_license")

    def test_unknown_denied(self):
        for raw in ("", "other", "all rights reserved"):
            got = self.verdict(raw)
            self.assertEqual(got["verdict"], "deny", raw)
            self.assertEqual(got["verdict_reason"], "license_unknown")

    def test_pd_with_third_party_recording_denied(self):
        got = self.verdict("", "https://creativecommons.org/publicdomain/mark/1.0/", "1.0")
        self.assertEqual(got["verdict"], "allow")
        lic, ver = M.parse_license("pd")
        cand = M._cand(license_id=lic, source="ia", published_year=1908, original_transfer=False)
        got = M.policy(cand)
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "pd_composition_third_party_recording")

    def test_pd_cutoff_is_computed_not_hardcoded(self):
        today = date(2026, 6, 1)
        self.assertEqual(M.pd_cutoff(today), 1931)
        self.assertEqual(M.pd_cutoff(date(2030, 1, 1)), 1935)
        meta = {"published_year_source": "metadata"}  # cross-checked, not an uploader claim
        old = M.policy(M._cand(license_id="pd", published_year=1930, **meta), today=today)
        edge = M.policy(M._cand(license_id="pd", published_year=1931, **meta), today=today)
        later = M.policy(M._cand(license_id="pd", published_year=1946, **meta), today=today)
        self.assertEqual(old["verdict"], "allow")
        self.assertEqual(edge["verdict"], "deny")
        self.assertEqual(later["verdict"], "deny")
        # the same disc ages into the public domain without touching the code
        self.assertEqual(M.policy(M._cand(license_id="pd", published_year=1931, **meta),
                                 today=date(2030, 1, 1))["verdict"], "allow")

    def test_pd_year_needs_a_metadata_cross_check(self):
        # An uploader's own "year" field is a claim; only item metadata dates the recording.
        claimed = M.policy(M._cand(license_id="pd", source="ia", published_year=1930,
                                   published_year_source="uploader"))
        self.assertEqual(claimed["verdict"], "deny")
        self.assertIn("year_unconfirmed", claimed["verdict_reason"])
        self.assertEqual(
            M.policy(M._cand(license_id="pd", source="ia", published_year=1930,
                             published_year_source="metadata"))["verdict"], "allow")

    def test_pd_without_year_denied(self):
        got = M.policy(M._cand(license_id="pd", source="commons"))
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "pd_recording_year_unknown")

    def test_freesound_hosted_denied(self):
        cand = M._cand(
            license_id="cc0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            host="cdn.freesound.org",
            provider="freesound",
            source="openverse",
        )
        got = M.policy(cand)
        self.assertEqual(got["verdict"], "deny")
        self.assertEqual(got["verdict_reason"], "freesound_preview_tos")

    def test_verdict_always_carries_jurisdiction_note_and_risk(self):
        for raw in ("cc0", "by", "by-sa", "by-nc", "", "pdm"):
            got = self.verdict(raw)
            self.assertTrue(got["jurisdiction_note"], raw)
            self.assertIn(got["content_id_risk"], ("low", "medium", "high"), raw)
            self.assertIn(got["verdict"], ("allow", "attribution", "deny"), raw)

    def test_content_id_risk(self):
        self.assertEqual(M.policy(M._cand(license_id="cc0", source="ia"))["content_id_risk"], "low")
        self.assertEqual(
            M.policy(M._cand(license_id="pd", published_year=1908))["content_id_risk"], "high"
        )


class AttributionTests(unittest.TestCase):
    def test_cc_by_block_has_all_five_elements(self):
        track = {
            "title": "Piano Melody",
            "creator": "ZHRØ",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_url": "https://example.org/track/1",
            "copyright": "(c) 2020 ZHRØ",
            "disclaimer": "Provided as-is, no warranty.",
        }
        text = M.attribution_block(track, changes="trimmed to 30 s and synced to video")
        self.assertIn("ZHRØ", text)  # creator
        self.assertIn("(c) 2020 ZHRØ", text)  # copyright notice, when supplied
        self.assertIn("CC BY 4.0", text)  # license name
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", text)  # license URL
        self.assertIn("https://example.org/track/1", text)  # material URI
        self.assertIn("no warranty", text)  # disclaimer, when supplied
        self.assertIn("Changes: trimmed to 30 s and synced to video", text)  # modification note

    def test_default_block_still_credits_and_disclaims(self):
        text = M.attribution_block({"title": "T", "creator": "C", "license": "CC BY 3.0",
                                    "license_url": "u", "source_url": "s"})
        self.assertIn("by C", text)
        self.assertIn("no endorsement", text)
        self.assertIn("Changes:", text)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self.old_xdg

    def test_openverse_freesound_previews_are_skipped(self):
        # Every recorded Openverse audio hit is a cdn.freesound.org preview (5/5 live).
        http, _ = stub_http({"api.openverse.org": fixture("openverse_calm_ambient.json")})
        M.http_get = http
        out = M.search("calm ambient", source="openverse")
        self.assertEqual(out["count"], 0)
        self.assertIn("freesound_preview_tos", out["skipped"])
        self.assertIn("no allow/attribution track", out["reason"])
        self.assertIn("no fallback track", out["reason"])

    def test_ia_candidates_pass_policy_and_filter(self):
        http, _ = stub_http({"archive.org/advancedsearch": fixture("ia_calm_ambient.json")})
        M.http_get = http
        out = M.search("calm ambient", source="ia")
        self.assertGreaterEqual(out["count"], 1)
        for cand in out["results"]:
            self.assertIn(cand["verdict"], ("allow", "attribution"))
            self.assertTrue(cand["license_url"].startswith("http"))
            self.assertTrue(cand["source_url"].startswith("https://archive.org/details/"))
            self.assertTrue(cand["attribution"])
            self.assertNotIn("freesound", cand["host"])
        self.assertEqual(
            [c["vibe_score"] for c in out["results"]],
            sorted((c["vibe_score"] for c in out["results"]), reverse=True),
        )
        self.assertEqual(out["results"][0]["license"] in ("CC0 1.0", "Public Domain Mark 1.0"), True)

    def test_ccmixter_cc0_is_usable(self):
        http, _ = stub_http({"ccmixter.org/api/query": fixture("ccmixter_ambient.json")})
        M.http_get = http
        out = M.search("ambient", source="ccmixter", limit=3)
        self.assertGreaterEqual(out["count"], 1)
        titles = [c["title"] for c in out["results"]]
        self.assertIn("Pianetto Lead", titles)
        for top in out["results"]:
            self.assertEqual(top["verdict"], "allow")
            self.assertTrue(top["file_url"].endswith(".mp3"))
            self.assertGreater(top["vibe_score"], 0)

    def test_commons_by_is_attribution_and_bare_pd_is_refused(self):
        http, _ = stub_http({"commons.wikimedia.org": fixture("commons_calm_ambient.json")})
        M.http_get = http
        out = M.search("calm ambient", source="commons")
        self.assertEqual(out["count"], 1)
        top = out["results"][0]
        self.assertEqual(top["verdict"], "attribution")
        self.assertEqual(top["license"], "CC BY 3.0")
        self.assertIn("pd_recording_year_unknown", out["skipped"])

    def test_min_s_and_limit(self):
        http, _ = stub_http({"commons.wikimedia.org": fixture("commons_calm_ambient.json")})
        M.http_get = http
        self.assertEqual(M.search("calm ambient", source="commons", min_s=5000)["count"], 0)
        self.assertGreaterEqual(M.search("calm ambient", source="commons", min_s=300)["count"], 1)

    def test_search_caches_on_disk(self):
        http, calls = stub_http({"archive.org/advancedsearch": fixture("ia_calm_ambient.json")})
        M.http_get = http
        M.search("calm ambient", source="ia")
        first = len(calls)
        M.search("calm ambient", source="ia")
        self.assertEqual(len(calls), first)  # served from the cache, no second request
        M.search("calm ambient", source="ia", refresh=True)
        self.assertGreater(len(calls), first)

    def test_dead_source_is_not_a_dead_search(self):
        def boom(url, **kw):
            raise RuntimeError("504")

        M.http_get = boom
        out = M.search("calm ambient", source="openverse")
        self.assertEqual(out["count"], 0)
        self.assertIn("error", out["reason"])

    def test_reason_mentions_every_source_tried(self):
        http, _ = stub_http(
            {
                "api.openverse.org": fixture("openverse_calm_ambient.json"),
                "archive.org/advancedsearch": fixture("ia_calm_ambient.json"),
            }
        )
        M.http_get = http
        out = M.search("calm ambient")
        self.assertIn("openverse:", " ".join(out["sources"]) + ":")
        self.assertGreaterEqual(out["count"], 1)


class OriginNodeTests(unittest.TestCase):
    """The origin page licenses the file only through its own license node."""

    def test_footer_and_stray_link_do_not_license_the_file(self):
        page = (
            '<html><body><p>&copy; 2024 Label. All rights reserved.</p>'
            '<p>More by <a href="/by/genre/ambient">ambient</a></p>'
            '<footer>Made with CC0 <a href="https://creativecommons.org/publicdomain/zero/1.0/">tools</a></footer>'
            "</body></html>"
        )
        self.assertEqual(M._scan_license(page), ("other", ""))

    def test_license_node_is_read(self):
        page = ('<p class="credit">"A" by B '
                '<a rel="license" href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></p>')
        self.assertEqual(M._scan_license(page), ("by", "4.0"))

    def test_conflicting_nodes_prove_neither(self):
        page = ('<div id="license"><a rel="license" href="https://creativecommons.org/licenses/by-sa/4.0/">A</a>'
                ' <a rel="license" href="https://creativecommons.org/licenses/by-nc/4.0/">B</a></div>')
        self.assertEqual(M._scan_license(page), ("other", ""))


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name) / "music"
        self._probe, self._analyze = M.probe, M.analyze
        M.probe = lambda path: (300.0, "mp3")
        M.analyze = lambda path: make_analysis()
        self.addCleanup(self._restore)

    def _restore(self):
        M.probe, M.analyze = self._probe, self._analyze
        if self.old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self.old_xdg

    def index(self, cand):
        M.remember([dict(cand)])

    def test_origin_page_without_license_never_downloads(self):
        page = "<html><body>a nice tune, no rights info</body></html>"
        http, calls = stub_http({"landing.example": page})
        M.http_get = http
        self.index(M._cand(id="web-1", source="web", source_url="https://landing.example/track",
                           file_url="https://cdn.example/track.mp3"))
        out = M.fetch("web-1", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "origin_verify_failed")
        self.assertEqual(len(calls), 1)  # only the origin page, never the file
        self.assertFalse(any("cdn.example" in c for c in calls))
        self.assertFalse(self.stage.exists() and any(self.stage.iterdir()))

    def test_denied_license_refused_before_any_network(self):
        http, calls = stub_http({})
        M.http_get = http
        self.index(M._cand(id="ov-x", source="openverse", provider="freesound",
                           host="cdn.freesound.org", license_id="cc0", file_url="https://cdn.freesound.org/x.mp3"))
        out = M.fetch("ov-x", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "license_denied")
        self.assertEqual(calls, [])

    def test_origin_mismatch_is_refused(self):
        page = '<a rel="license" href="https://creativecommons.org/licenses/by-sa/4.0/">license</a>'
        http, _ = stub_http({"landing.example": page, "cdn.example": b"ID3audio"})
        M.http_get = http
        self.index(M._cand(id="web-2", source="web", license_id="cc0",
                           license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                           source_url="https://landing.example/t2", file_url="https://cdn.example/t2.mp3"))
        out = M.fetch("web-2", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "origin_verify_failed")
        self.assertIn("mismatch", out["reason"])

    def test_by_track_verifies_then_stages_with_sidecar(self):
        page = ('<p class="license">"Nocturne" by Ada is licensed CC BY 4.0 '
                '<a rel="license" href="https://creativecommons.org/licenses/by/4.0/">deed</a> '
                'provided as is</p>')
        http, calls = stub_http({"landing.example": page, "cdn.example": b"ID3fakebytes"})
        M.http_get = http
        self.index(M._cand(
            id="web-3", source="web", title="Nocturne", creator="Ada",
            license_id="by", license_version="4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            source_url="https://landing.example/t3", file_url="https://cdn.example/t3.mp3",
        ))
        out = M.fetch("web-3", duration=30, stage_dir=self.stage)
        self.assertNotIn("error", out)
        self.assertEqual(out["path_in_container"], "/music/web-3.mp3")
        self.assertEqual(out["license"], "CC BY 4.0")
        self.assertIn("Ada", out["attribution"])
        self.assertIn("https://landing.example/t3", out["attribution"])
        self.assertEqual(calls[0].startswith("https://landing.example"), True)  # verify first
        self.assertTrue(any("cdn.example" in c for c in calls[1:]))
        staged = self.stage / "web-3.mp3"
        self.assertTrue(staged.is_file())
        side = json.loads((self.stage / "web-3.json").read_text())
        for key in ("id", "title", "creator", "license", "license_version", "license_url",
                    "source_url", "retrieved_at", "attribution_required", "attribution_text",
                    "verdict", "verdict_reason", "license_evidence", "content_id_risk",
                    "jurisdiction_note", "recording_is_original_transfer", "sha256",
                    "duration_s", "mood", "bpm"):
            self.assertIn(key, side)
        self.assertEqual(side["sha256"], __import__("hashlib").sha256(b"ID3fakebytes").hexdigest())
        self.assertEqual(side["path_in_container"], "/music/web-3.mp3")
        self.assertGreaterEqual(side["start_s"], 1.0)
        self.assertLessEqual(side["start_s"] + 30, 300.0 - 1.0)
        for key in ("path_in_container", "start_s", "title", "creator", "license",
                    "license_url", "source_url", "attribution"):
            self.assertIn(key, out)

    def test_short_track_rejected(self):
        page = '<p class="license">CC0 1.0 <a rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">deed</a></p>'
        http, _ = stub_http({"landing.example": page, "cdn.example": b"x"})
        M.http_get = http
        M.probe = lambda path: (12.0, "mp3")
        self.index(M._cand(id="web-4", source="web", license_id="cc0",
                           source_url="https://landing.example/t4", file_url="https://cdn.example/t4.mp3"))
        out = M.fetch("web-4", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "track_too_short")

    def test_gate_failure_blocks_the_stage(self):
        page = '<p class="license">CC0 1.0 <a rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">deed</a></p>'
        http, _ = stub_http({"landing.example": page, "cdn.example": b"x"})
        M.http_get = http
        M.analyze = lambda path: {"lufs": -80.0, "lra": 0.0, "frames": make_analysis()["frames"]}
        self.index(M._cand(id="web-5", source="web", license_id="cc0",
                           source_url="https://landing.example/t5", file_url="https://cdn.example/t5.mp3"))
        out = M.fetch("web-5", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "gate_failed")
        self.assertEqual(out["reason"], "digital_silence")


class AnalysisTests(unittest.TestCase):
    def test_parse_analysis(self):
        text = "\n".join(
            [
                "frame:0    pts:0       pts_time:0",
                "lavfi.r128.M=-20.500",
                "lavfi.r128.I=-19.000",
                "lavfi.r128.LRA=1.500",
                "lavfi.aspectralstats.1.centroid=900.000",
                "lavfi.aspectralstats.1.flux=0.900",
                "lavfi.aspectralstats.1.rolloff=1700.000",
                "frame:1    pts:1024    pts_time:0.021333",
                "lavfi.r128.M=-18.000",
                "lavfi.r128.I=-17.500",
                "lavfi.r128.LRA=6.000",
                "lavfi.aspectralstats.1.centroid=1000.000",
                "lavfi.aspectralstats.1.flux=0.010",
                "lavfi.aspectralstats.1.rolloff=2000.000",
            ]
        )
        got = M.parse_analysis(text)
        self.assertEqual(len(got["frames"]), 2)
        self.assertAlmostEqual(got["lufs"], -17.5)
        self.assertAlmostEqual(got["lra"], 6.0)
        self.assertAlmostEqual(got["frames"][1]["centroid"], 1000.0)

    def test_gates_use_centroid_and_rolloff(self):
        self.assertEqual(M.gate(M.parse_analysis("")), "no_audio")
        silent = make_analysis(level=-80.0)
        self.assertEqual(M.gate(dict(silent, lufs=-80.0)), "digital_silence")
        hiss = make_analysis(centroid=6000.0, rolloff=15000.0)
        self.assertEqual(M.gate(hiss), "noise_dominated")
        dark = make_analysis(centroid=120.0, rolloff=400.0)
        self.assertEqual(M.gate(dark), "too_dark_rumble")
        self.assertIsNone(M.gate(make_analysis()))

    def test_pick_start_stays_inside_the_bounds(self):
        analysis = make_analysis(n=1800, dt=0.1, peak_every=57)
        start = M.pick_start(analysis, 180.0, 30.0)
        self.assertGreaterEqual(start, 1.0)
        self.assertLessEqual(start + 30.0, 180.0 - 1.0)
        peaks = M.flux_peaks(analysis["frames"], 180.0)
        self.assertTrue(peaks)
        self.assertLessEqual(min(abs(start - p) for p in peaks), 1.5)

    def test_pick_start_on_a_short_track_falls_back_to_one_second(self):
        self.assertEqual(M.pick_start(make_analysis(n=100), 10.0, 30.0), 1.0)


class MiscTests(unittest.TestCase):
    def test_default_stage_dir_is_the_mounted_cache_dir(self):
        old = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = "/tmp/xdg-test"
        try:
            self.assertEqual(str(M.default_stage()), "/tmp/xdg-test/promo-video/music")
        finally:
            if old is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old

    def test_slug_is_filesystem_safe(self):
        self.assertEqual(M.slug("Hugh_Jass - Pianetto/Lead.mp3"), "hugh_jass-pianetto-lead.mp3")
        self.assertEqual(M.slug("///"), "x")

    def test_parse_license_forms(self):
        self.assertEqual(M.parse_license("CC0 (CC Zero)", url="http://creativecommons.org/publicdomain/zero/1.0/")[0], "cc0")
        self.assertEqual(M.parse_license("", url="http://creativecommons.org/licenses/publicdomain/")[0], "pdm")
        self.assertEqual(M.parse_license("CC BY 3.0", url="https://creativecommons.org/licenses/by/3.0")[0], "by")
        self.assertEqual(M.parse_license("", url="https://creativecommons.org/licenses/by/3.0")[1], "3.0")
        self.assertEqual(M.parse_license("", url="http://creativecommons.org/licenses/by-nc-nd/4.0/")[0], "by-nc-nd")
        self.assertEqual(M.parse_license("")[0], "other")

    def test_cli_parses_both_commands(self):
        parser = M.build_parser()
        args = parser.parse_args(["search", "--vibe", "calm ambient", "--min-s", "30", "--limit", "3"])
        self.assertEqual((args.vibe, args.min_s, args.limit), ("calm ambient", 30.0, 3))
        args = parser.parse_args(["fetch", "ia-foo", "--duration", "30"])
        self.assertEqual((args.target, args.duration, args.stage_dir), ("ia-foo", 30.0, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
