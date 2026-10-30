#!/usr/bin/env python3
"""Offline tests for music_search.py. No network, no ffmpeg.

Run: python3 -I skills/music-search/scripts/test_music_search.py
     (also collectable by pytest: `python3 -m pytest skills/music-search/scripts`)

Recorded fixtures in ./fixtures/ are trimmed real responses (2026-xx): Openverse audio for
"calm ambient", archive.org advancedsearch, ccMixter lic=zero. Source records answered by
the stubs (archive.org /metadata, ccMixter ids=, Openverse audio id) are synthetic dicts
shaped like the live ones, so `fetch` is exercised without the network.
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from hashlib import sha256
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import music_search as M  # noqa: E402

FIXTURES = HERE / "fixtures"
REAL_HTTP_GET = M.http_get  # the suite replaces M.http_get freely; HttpTests need the real one


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def stub_http(routes):
    """routes: {url-substring: payload}. Records the URLs that were requested."""
    calls = []

    def fake(url, *, timeout=25, tries=3):
        calls.append(url)
        for needle, payload in routes.items():
            if needle in url:
                return payload if isinstance(payload, str) else json.dumps(payload)
        raise RuntimeError(f"no fixture for {url}")

    return fake, calls


def stub_stream(chunks, calls=None):
    """Stands in for http_stream: a download is a generator of byte blocks."""
    def fake(url, *, timeout=90, referer=None, chunk=1 << 20):
        if calls is not None:
            calls.append(url)
        yield from chunks

    return fake


def ia_item(identifier, licenseurl="", date="", files=None):
    """Shaped like archive.org /metadata/<id>."""
    md = {"identifier": identifier, "title": identifier}
    if licenseurl:
        md["licenseurl"] = licenseurl
    if date:
        md["date"] = date
    return {
        "metadata": md,
        "files": files if files is not None else [
            {"name": f"{identifier}.flac", "format": "Flac", "size": "9000000"},
            {"name": f"{identifier}.mp3", "format": "VBR MP3", "size": "2000000"},
        ],
    }


def make_analysis(n=1200, dt=0.1, level=-18.0, centroid=800.0, rolloff=1500.0):
    frames = [{"centroid": centroid, "rolloff": rolloff} for _ in range(n)]
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
        got = M.policy(M._cand(license_id="cc0", reupload=True, source="ia"))
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
        got = M.policy(M._cand(license_id="pd", source="ia"))
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
            self.assertTrue(got["content_id_reasons"], raw)  # a level alone argues nothing
            self.assertIn(got["verdict"], ("allow", "attribution", "deny"), raw)

    def test_content_id_risk_and_its_reasons(self):
        low = M.policy(M._cand(license_id="cc0", source="ia"))
        self.assertEqual(low["content_id_risk"], "low")
        self.assertEqual(low["content_id_reasons"], ["cc0_or_pdm_from_rights_holder"])
        high = M.policy(M._cand(license_id="pd", published_year=1908))
        self.assertEqual(high["content_id_risk"], "high")
        self.assertEqual(high["content_id_reasons"], ["pd_era_disc_reissued_by_a_label"])
        by = M.policy(M._cand(license_id="by", license_version="4.0"))
        self.assertEqual(by["content_id_risk"], "medium")
        self.assertEqual(by["content_id_reasons"], ["cc_by_without_credit_is_an_easy_claim_target"])
        # the sidecar has to say how to answer a claim, not only that one is possible
        for word in ("license_evidence", "source_url", "sha256", "counter-notice"):
            self.assertIn(word, M.CONTENT_ID_DISPUTE)


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
        # fetch re-reads this item later: the identifier must survive the search
        self.assertTrue(all(c["ia_id"] for c in out["results"]))

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

    def test_ia_results_are_indexed_for_fetch(self):
        http, _ = stub_http({"archive.org/advancedsearch": fixture("ia_calm_ambient.json")})
        M.http_get = http
        out = M.search("calm ambient", source="ia", limit=1)
        top = out["results"][0]
        self.assertEqual(M.resolve_candidate(top["id"])["source_url"], top["source_url"])
        self.assertEqual(M.resolve_candidate("https://example.org/track.mp3"), {})

    def test_min_s_and_limit(self):
        # the recorded ccMixter files are 0:21 and 2:28, so a longer minimum drops them
        http, _ = stub_http({"ccmixter.org/api/query": fixture("ccmixter_ambient.json")})
        M.http_get = http
        too_long = M.search("ambient", source="ccmixter", min_s=600)
        self.assertEqual(too_long["count"], 0)
        self.assertGreaterEqual(too_long["skipped"]["too_short"], 1)
        kept = M.search("ambient", source="ccmixter", min_s=100, limit=2)
        self.assertEqual([c["title"] for c in kept["results"]], ["After the storm"])

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

    def test_provenance_breaks_a_vibe_tie(self):
        def fake(vibe, limit, *, refresh=False):
            return [M._cand(id="ia-b", source="ia", title="B", creator="b", license_id="by",
                            license_version="4.0", duration_s=300),
                    M._cand(id="ia-a", source="ia", title="A", creator="a", license_id="cc0",
                            duration_s=300)]

        old = M.SEARCHERS["ia"]
        M.SEARCHERS["ia"] = fake
        self.addCleanup(lambda: M.SEARCHERS.__setitem__("ia", old))
        out = M.search("calm ambient", source="ia")
        self.assertEqual([c["id"] for c in out["results"]], ["ia-a", "ia-b"])
        self.assertEqual([c["content_id_risk"] for c in out["results"]], ["low", "medium"])


class HttpTests(unittest.TestCase):
    """M6: the Openverse call has 10 s a shot and waits out a 429 instead of burning 3 tries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_xdg = os.environ.get("XDG_CACHE_HOME")
        self.old_http = M.http_get
        M.http_get = REAL_HTTP_GET  # a stub left behind by an earlier class must not answer here
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: setattr(M, "http_get", self.old_http))
        self.addCleanup(lambda: os.environ.__setitem__("XDG_CACHE_HOME", self.old_xdg)
                        if self.old_xdg else os.environ.pop("XDG_CACHE_HOME", None))

    def test_openverse_asks_for_a_ten_second_timeout(self):
        seen = {}

        def fake(url, *, timeout=25, tries=3):
            seen["timeout"] = timeout
            return json.dumps({"results": []})

        M.http_get = fake
        M.search("calm ambient", source="openverse")
        self.assertEqual(seen["timeout"], 10)

    def test_a_429_is_waited_as_long_as_the_origin_asks(self):
        err = urllib.error.HTTPError("https://api.openverse.org/x", 429, "Too Many Requests",
                                     {"Retry-After": "2"}, None)
        slept = []
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=err), \
                mock.patch.object(M.time, "sleep", slept.append):
            with self.assertRaises(M.HttpStatusError) as ctx:
                M.http_get("https://api.openverse.org/v1/audio/?q=calm")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(slept, [2.0, 2.0])  # both retries at the origin's pace, not 1.5/3.0

    def test_retry_after_is_capped_inside_the_call_budget(self):
        err = urllib.error.HTTPError("https://api.openverse.org/y", 503, "busy",
                                     {"Retry-After": "600"}, None)
        slept = []
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=err), \
                mock.patch.object(M.time, "sleep", slept.append):
            with self.assertRaises(M.HttpStatusError):
                M.http_get("https://api.openverse.org/y", tries=2)
        self.assertEqual(slept, [10.0])  # 600 s would blow the caller's budget twice over

    def test_the_status_code_reaches_the_skip_reason(self):
        def boom(url, **kw):
            err = urllib.error.HTTPError("u", 429, "x", {}, None)
            self.addCleanup(err.close)
            raise M.HttpStatusError(url, 3, err)

        M.http_get = boom
        out = M.search("calm ambient", source="openverse")
        self.assertIn("openverse:error:HTTP429", out["sources"])
        self.assertIn("openverse:error:HTTP429", out["reason"])


class OriginVerifyTests(unittest.TestCase):
    """Origin verification reads the source record, and there is no HTML page scan left."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: os.environ.__setitem__("XDG_CACHE_HOME", self.old_xdg)
                        if self.old_xdg else os.environ.pop("XDG_CACHE_HOME", None))

    def test_ia_record_licenses_the_file(self):
        http, _ = stub_http({"archive.org/metadata/item-a": ia_item(
            "item-a", "https://creativecommons.org/licenses/by/4.0/", "2009-03-01")})
        M.http_get = http
        got = M.verify_at_origin(M._cand(source="ia", ia_id="item-a", license_id="by"))
        self.assertTrue(got["ok"])
        self.assertEqual(got["license_id"], "by")
        self.assertEqual(got["published_year_source"], "metadata")
        self.assertIn("licenseurl=", got["license_evidence"])

    def test_ia_record_without_license_is_unverified(self):
        http, _ = stub_http({"archive.org/metadata/item-b": ia_item("item-b")})
        M.http_get = http
        got = M.verify_at_origin(M._cand(source="ia", ia_id="item-b"))
        self.assertFalse(got["ok"])
        self.assertIn("no usable license", got["detail"])

    def test_ia_record_that_contradicts_the_search_is_refused(self):
        http, _ = stub_http({"archive.org/metadata/item-c": ia_item(
            "item-c", "https://creativecommons.org/licenses/by-sa/4.0/")})
        M.http_get = http
        got = M.verify_at_origin(M._cand(source="ia", ia_id="item-c", license_id="cc0"))
        self.assertFalse(got["ok"])
        self.assertIn("mismatch", got["detail"])

    def test_ia_year_conflict_is_refused(self):
        http, _ = stub_http({"archive.org/metadata/item-d": ia_item(
            "item-d", "https://creativecommons.org/publicdomain/mark/1.0/", "1935-01-01")})
        M.http_get = http
        got = M.verify_at_origin(M._cand(source="ia", ia_id="item-d", license_id="pdm",
                                         published_year=1920))
        self.assertFalse(got["ok"])
        self.assertIn("year conflict", got["detail"])

    def test_ccmixter_api_record_licenses_the_file(self):
        payload = [{"upload_id": 61841, "license_name": "CC0 (CC Zero)",
                    "license_url": "http://creativecommons.org/publicdomain/zero/1.0/"}]
        http, calls = stub_http({"ccmixter.org/api/query": payload})
        M.http_get = http
        got = M.verify_at_origin(M._cand(source="ccmixter", ccm_id=61841, license_id="cc0"))
        self.assertTrue(got["ok"])
        self.assertEqual(got["license_id"], "cc0")
        self.assertIn("ids=61841", calls[0])

    def test_openverse_record_reroute_to_freesound_is_caught(self):
        record = {"id": "ov-1", "license": "cc0", "license_version": "1.0",
                  "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                  "url": "https://cdn.freesound.org/previews/1/1.mp3", "source": "freesound",
                  "foreign_landing_url": "https://example.org/t"}
        http, _ = stub_http({"api.openverse.org/v1/audio/": record})
        M.http_get = http
        cand = M._cand(source="openverse", ov_id="ov-1", license_id="cc0")
        got = M.verify_at_origin(cand)
        self.assertTrue(got["ok"])
        cand.update({k: v for k, v in got.items() if k != "ok"})
        self.assertEqual(M.policy(cand)["verdict_reason"], "freesound_preview_tos")

    def test_unknown_source_has_no_origin_check(self):
        got = M.verify_at_origin(M._cand(source="web", license_id="cc0"))
        self.assertFalse(got["ok"])
        self.assertIn("no origin check available", got["detail"])


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name) / "music"
        self._probe, self._analyze = M.probe, M.analyze
        M.probe = lambda path: (300.0, "mp3")
        M.analyze = lambda path, **kw: make_analysis()
        self.addCleanup(self._restore)

    def _restore(self):
        M.probe, M.analyze = self._probe, self._analyze
        if self.old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self.old_xdg

    def index(self, cand):
        M.remember([dict(cand)])

    def ia_cand(self, identifier, **kw):
        return M._cand(id=f"ia-{identifier}", source="ia", provider="archive.org",
                       host="archive.org", ia_id=identifier, title="Calm Bed", creator="Ada",
                       source_url=f"https://archive.org/details/{identifier}", **kw)

    def test_unknown_candidate_is_refused_without_network(self):
        http, calls = stub_http({})
        M.http_get = http
        out = M.fetch("https://cdn.example/track.mp3", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "unknown_candidate")
        self.assertEqual(calls, [])

    def test_denied_license_refused_before_any_network(self):
        http, calls = stub_http({})
        M.http_get = http
        self.index(M._cand(id="ov-x", source="openverse", provider="freesound",
                           host="cdn.freesound.org", license_id="cc0",
                           file_url="https://cdn.freesound.org/x.mp3"))
        out = M.fetch("ov-x", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "license_denied")
        self.assertEqual(calls, [])

    def test_record_without_license_never_downloads(self):
        http, calls = stub_http({"archive.org/metadata/item-nolic": ia_item("item-nolic")})
        M.http_get = http
        streams = []
        M.http_stream = stub_stream([b"ID3audio"], streams)
        self.index(self.ia_cand("item-nolic", license_id="cc0"))
        out = M.fetch("ia-item-nolic", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "origin_verify_failed")
        self.assertEqual(len(calls), 1)  # the record only, never the file
        self.assertEqual(streams, [])
        self.assertFalse(self.stage.exists() and any(self.stage.iterdir()))

    def test_origin_mismatch_is_refused(self):
        http, calls = stub_http({"archive.org/metadata/item-mm": ia_item(
            "item-mm", "https://creativecommons.org/licenses/by-sa/4.0/")})
        M.http_get = http
        streams = []
        M.http_stream = stub_stream([b"ID3audio"], streams)
        self.index(self.ia_cand("item-mm", license_id="cc0"))
        out = M.fetch("ia-item-mm", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "origin_verify_failed")
        self.assertIn("mismatch", out["reason"])
        self.assertEqual(streams, [])

    def test_by_track_verifies_then_stages_with_sidecar(self):
        raw = b"ID3fakebytes"
        http, calls = stub_http({"archive.org/metadata/item-by": ia_item(
            "item-by", "https://creativecommons.org/licenses/by/4.0/", "2009-03-01")})
        M.http_get = http
        streams = []
        M.http_stream = stub_stream([raw], streams)
        self.index(self.ia_cand("item-by", license_id="by", license_version="4.0",
                                license_url="https://creativecommons.org/licenses/by/4.0/"))
        out = M.fetch("ia-item-by", duration=30, stage_dir=self.stage)
        self.assertNotIn("error", out)
        self.assertEqual(out["path_in_container"], "/music/ia-item-by.mp3")
        self.assertEqual(out["license"], "CC BY 4.0")
        self.assertIn("Ada", out["attribution"])
        self.assertIn("https://archive.org/details/item-by", out["attribution"])
        self.assertEqual(calls[0].startswith("https://archive.org/metadata/"), True)  # verify first
        self.assertEqual(streams, ["https://archive.org/download/item-by/item-by.mp3"])
        staged = self.stage / "ia-item-by.mp3"
        self.assertTrue(staged.is_file())
        side = json.loads((self.stage / "ia-item-by.json").read_text())
        for key in ("id", "title", "creator", "license", "license_version", "license_url",
                    "source_url", "retrieved_at", "attribution_required", "attribution_text",
                    "verdict", "verdict_reason", "license_evidence", "content_id_risk",
                    "content_id_reasons", "content_id_dispute",
                    "jurisdiction_note", "recording_is_original_transfer", "sha256",
                    "duration_s", "mood", "bpm"):
            self.assertIn(key, side)
        self.assertEqual(side["sha256"], sha256(raw).hexdigest())
        self.assertEqual(side["path_in_container"], "/music/ia-item-by.mp3")
        self.assertGreaterEqual(side["start_s"], 1.0)
        self.assertLessEqual(side["start_s"] + 30, 300.0 - 1.0)
        for key in ("path_in_container", "start_s", "title", "creator", "license",
                    "license_url", "source_url", "attribution", "content_id_reasons",
                    "content_id_dispute"):
            self.assertIn(key, out)
        self.assertEqual(side["content_id_dispute"], M.CONTENT_ID_DISPUTE)

    def test_ccmixter_download_sends_a_referer(self):
        payload = [{"upload_id": 61841, "license_name": "CC0 (CC Zero)",
                    "license_url": "http://creativecommons.org/publicdomain/zero/1.0/"}]
        http, _ = stub_http({"ccmixter.org/api/query": payload})
        M.http_get = http
        seen = {}

        def fake(url, *, timeout=90, referer=None, chunk=1 << 20):
            seen["referer"] = referer
            yield b"ID3ccm"

        M.http_stream = fake
        self.index(M._cand(id="ccm-61841", source="ccmixter", ccm_id=61841, license_id="cc0",
                           source_url="https://ccmixter.org/files/Hugh_Jass/61841",
                           file_url="https://ccmixter.org/content/Hugh_Jass/x.mp3"))
        out = M.fetch("ccm-61841", duration=20, stage_dir=self.stage)
        self.assertNotIn("error", out)
        self.assertEqual(seen["referer"], "https://ccmixter.org/files/Hugh_Jass/61841")

    def test_short_track_rejected(self):
        http, _ = stub_http({"archive.org/metadata/item-short": ia_item(
            "item-short", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"x"])
        M.probe = lambda path: (12.0, "mp3")
        self.index(self.ia_cand("item-short", license_id="cc0"))
        out = M.fetch("ia-item-short", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "track_too_short")

    def test_gate_failure_blocks_the_stage(self):
        http, _ = stub_http({"archive.org/metadata/item-silent": ia_item(
            "item-silent", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"x"])
        M.analyze = lambda path, **kw: {"lufs": -80.0, "lra": 0.0,
                                        "frames": make_analysis()["frames"]}
        self.index(self.ia_cand("item-silent", license_id="cc0"))
        out = M.fetch("ia-item-silent", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "gate_failed")
        self.assertEqual(out["reason"], "digital_silence")

    def test_ffprobe_failure_returns_a_payload_not_a_traceback(self):
        http, _ = stub_http({"archive.org/metadata/item-bad": ia_item(
            "item-bad", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"x"])

        def boom(path):
            raise subprocess_timeout()

        M.probe = boom
        self.index(self.ia_cand("item-bad", license_id="cc0"))
        out = M.fetch("ia-item-bad", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "analysis_failed")
        self.assertIn("TimeoutExpired", out["reason"])

    def test_analyze_failure_returns_a_payload_not_a_traceback(self):
        http, _ = stub_http({"archive.org/metadata/item-bad2": ia_item(
            "item-bad2", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"x"])

        def boom(path, **kw):
            raise RuntimeError("ffmpeg died")

        M.analyze = boom
        self.index(self.ia_cand("item-bad2", license_id="cc0"))
        out = M.fetch("ia-item-bad2", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "analysis_failed")
        self.assertIn("ffmpeg died", out["reason"])

    def test_dead_file_is_a_result(self):
        http, _ = stub_http({"archive.org/metadata/item-dead": ia_item(
            "item-dead", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http

        def boom(url, **kw):
            raise RuntimeError("404")
            yield b""  # pragma: no cover

        M.http_stream = boom
        self.index(self.ia_cand("item-dead", license_id="cc0"))
        out = M.fetch("ia-item-dead", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "download_failed")
        self.assertIn("404", out["reason"])

    def fetched_ok(self, stage, ident="item-hint"):
        """The smallest happy path: cc0 record, one streamed block, a 300 s probe."""
        http, _ = stub_http({f"archive.org/metadata/{ident}": ia_item(
            ident, "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"ID3hint"])
        self.index(self.ia_cand(ident, license_id="cc0"))
        return M.fetch(f"ia-{ident}", duration=30, stage_dir=stage)

    def test_mount_hint_warns_when_the_stage_is_not_the_mounted_dir(self):
        out = self.fetched_ok(self.stage)
        self.assertNotIn("error", out)
        self.assertIn("--stage-dir", out["mount_hint"])
        self.assertIn(str(M.mounted_stage()), out["mount_hint"])

    def test_no_mount_hint_when_staging_into_the_mounted_dir(self):
        old = M.mounted_stage
        M.mounted_stage = lambda: self.stage
        self.addCleanup(lambda: setattr(M, "mounted_stage", old))
        self.assertNotIn("mount_hint", self.fetched_ok(self.stage))

    def test_oversized_listing_is_refused_before_the_first_byte(self):
        files = [{"name": "item-big.mp3", "format": "VBR MP3", "size": "60000000"},
                 {"name": "item-big.ogg", "format": "Ogg Vorbis", "size": "5000000"}]
        http, _ = stub_http({"archive.org/metadata/item-big": ia_item(
            "item-big", "https://creativecommons.org/publicdomain/zero/1.0/", files=files)})
        M.http_get = http
        streams = []
        M.http_stream = stub_stream([b"x"], streams)
        self.index(self.ia_cand("item-big", license_id="cc0"))
        out = M.fetch("ia-item-big", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "download_too_large")
        self.assertEqual(out["size_bytes"], 60000000)
        self.assertEqual(out["limit_bytes"], M.MAX_DOWNLOAD_BYTES)
        self.assertIn("item-big.ogg", out["reason"])  # names the smaller formats it skipped
        self.assertEqual(streams, [])  # not one byte of a 60 MB file
        self.assertFalse(self.stage.exists() and any(self.stage.iterdir()))

    def test_slow_download_is_a_result_payload(self):
        http, _ = stub_http({"archive.org/metadata/item-slow": ia_item(
            "item-slow", "https://creativecommons.org/publicdomain/zero/1.0/")})
        M.http_get = http
        M.http_stream = stub_stream([b"x" * 8, b"y" * 8])
        old = M._monotonic
        ticks = iter([0.0, 0.0, 99.0])  # start, one block in time, then past the 45 s budget
        M._monotonic = lambda: next(ticks, 99.0)
        self.addCleanup(lambda: setattr(M, "_monotonic", old))
        self.index(self.ia_cand("item-slow", license_id="cc0"))
        out = M.fetch("ia-item-slow", duration=30, stage_dir=self.stage)
        self.assertEqual(out["error"], "download_too_slow")
        self.assertEqual(out["deadline_s"], M.DOWNLOAD_DEADLINE_S)
        self.assertFalse(self.stage.exists() and any(self.stage.iterdir()))


def subprocess_timeout():
    import subprocess
    return subprocess.TimeoutExpired(cmd="ffprobe", timeout=180)


class DownloadTests(unittest.TestCase):
    def test_streams_in_chunks_and_hashes_incrementally(self):
        chunks = [b"ID3", b"-middle-", b"end"]
        M.http_stream = stub_stream(chunks)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "track.bin"
            size, digest = M.download("https://cdn.example/t.mp3", dest)
            self.assertEqual(size, len(b"".join(chunks)))
            self.assertEqual(dest.read_bytes(), b"".join(chunks))
            self.assertEqual(digest, sha256(b"".join(chunks)).hexdigest())

    def test_oversized_file_aborts(self):
        M.http_stream = stub_stream([b"x" * 32, b"y" * 32])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                M.download("https://cdn.example/big.mp3", Path(tmp) / "t.bin", max_bytes=40)

    def test_the_deadline_is_a_total_budget_not_a_per_read_timeout(self):
        M.http_stream = stub_stream([b"x" * 8, b"y" * 8])
        old = M._monotonic
        ticks = iter([0.0, 0.0, 99.0])
        M._monotonic = lambda: next(ticks, 99.0)
        self.addCleanup(lambda: setattr(M, "_monotonic", old))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(M.DownloadError) as ctx:
                M.download("https://cdn.example/slow.mp3", Path(tmp) / "t.bin")
        self.assertEqual(ctx.exception.code, "download_too_slow")
        self.assertEqual(ctx.exception.detail["deadline_s"], M.DOWNLOAD_DEADLINE_S)

    def test_the_read_timeout_never_outlives_the_download_budget(self):
        """A bare 90 s socket timeout can outlast a 45 s budget on one stalled read."""
        seen = []

        def capturing(url, *, timeout=90, referer=None, chunk=1 << 20):
            seen.append(timeout)
            yield b"ID3"

        M.http_stream = capturing
        with tempfile.TemporaryDirectory() as tmp:
            M.download("https://cdn.example/a.mp3", Path(tmp) / "a.bin")
            M.download("https://cdn.example/b.mp3", Path(tmp) / "b.bin", deadline_s=7)
            M.download("https://cdn.example/c.mp3", Path(tmp) / "c.bin", deadline_s=600)
        self.assertEqual(seen, [M.DOWNLOAD_DEADLINE_S, 7, M.READ_TIMEOUT_S])
        self.assertLessEqual(M.DOWNLOAD_DEADLINE_S, 60)  # still inside the caller's Bash timeout

    def test_ia_listing_reports_the_size_and_the_smaller_formats(self):
        files = [{"name": "item-z.ogg", "format": "Ogg Vorbis", "size": "50000000"},
                 {"name": "item-z.mp3", "format": "VBR MP3", "size": "60000000"}]
        http, calls = stub_http({"archive.org/metadata/item-z": ia_item("item-z", files=files)})
        M.http_get = http
        url, size, others = M.ia_file("item-z")
        self.assertEqual(url, "https://archive.org/download/item-z/item-z.mp3")
        self.assertEqual(size, 60000000)  # mp3 wins the format order even when it is bigger
        self.assertEqual(others, ["item-z.ogg (47 MB)"])
        self.assertEqual(len(calls), 1)  # one listing feeds both the url and its size


class AnalysisTests(unittest.TestCase):
    def test_parse_analysis(self):
        text = "\n".join(
            [
                "frame:0    pts:0       pts_time:0",
                "lavfi.r128.I=-19.000",
                "lavfi.r128.LRA=1.500",
                "lavfi.aspectralstats.1.centroid=900.000",
                "lavfi.aspectralstats.1.rolloff=1700.000",
                "frame:1    pts:1024    pts_time:0.021333",
                "lavfi.r128.I=-17.500",
                "lavfi.r128.LRA=6.000",
                "lavfi.aspectralstats.1.centroid=1000.000",
                "lavfi.aspectralstats.1.rolloff=2000.000",
            ]
        )
        got = M.parse_analysis(text)
        self.assertEqual(len(got["frames"]), 2)
        self.assertAlmostEqual(got["lufs"], -17.5)
        self.assertAlmostEqual(got["lra"], 6.0)
        self.assertAlmostEqual(got["frames"][1]["centroid"], 1000.0)
        self.assertAlmostEqual(got["frames"][1]["rolloff"], 2000.0)

    def test_analyze_seeks_the_window_it_was_asked_for(self):
        seen = {}

        class Out:
            stdout = ""

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return Out()

        old = M.subprocess.run
        M.subprocess.run = fake_run
        try:
            M.analyze(Path("/tmp/x.mp3"), start=3.0, duration=42.0)
        finally:
            M.subprocess.run = old
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("-ss") + 1], "3.000")
        self.assertEqual(cmd[cmd.index("-t") + 1], "42.000")
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))  # fast seek, before the input

    def test_gates_use_centroid_and_rolloff(self):
        self.assertEqual(M.gate(M.parse_analysis("")), "no_audio")
        silent = make_analysis(level=-80.0)
        self.assertEqual(M.gate(dict(silent, lufs=-80.0)), "digital_silence")
        hiss = make_analysis(centroid=6000.0, rolloff=15000.0)
        self.assertEqual(M.gate(hiss), "noise_dominated")
        dark = make_analysis(centroid=120.0, rolloff=400.0)
        self.assertEqual(M.gate(dark), "too_dark_rumble")
        self.assertIsNone(M.gate(make_analysis()))

    def test_pick_start_is_a_clamped_fixed_offset(self):
        self.assertEqual(M.pick_start(300.0, 30.0), M.START_OFFSET_S)
        self.assertGreaterEqual(M.pick_start(300.0, 30.0), 1.0)
        self.assertLessEqual(M.pick_start(300.0, 30.0) + 30.0, 300.0 - 1.0)
        # barely long enough: clamped to the last legal start, still 1 s of tail
        start = M.pick_start(34.0, 30.0)
        self.assertEqual(start, 3.0)
        self.assertLessEqual(start + 30.0, 34.0 - 1.0)
        # the shortest track fetch accepts: 1 s of head, window, 1 s of tail
        tight = M.pick_start(32.0, 30.0)
        self.assertEqual(tight, 1.0)
        self.assertLessEqual(tight + 30.0, 32.0 - 1.0)


class MiscTests(unittest.TestCase):
    def test_default_stage_follows_xdg_and_the_mount_does_not(self):
        old = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = "/tmp/xdg-test"
        try:
            self.assertEqual(str(M.default_stage()), "/tmp/xdg-test/storyboard-video/music")
            # the plugin's mount is pinned to $HOME/.cache: `fetch` prints a mount_hint instead
            # of the two silently disagreeing (M3: keep XDG, warn).
            self.assertEqual(M.mounted_stage(), Path.home() / ".cache" / "storyboard-video" / "music")
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

    def test_only_the_three_sources_remain(self):
        self.assertEqual(M.SOURCES, ("openverse", "ia", "ccmixter"))
        self.assertEqual(sorted(M.SEARCHERS), ["ccmixter", "ia", "openverse"])
        self.assertFalse([n for n in dir(M) if "commons" in n.lower()])

    def test_cli_parses_both_commands(self):
        parser = M.build_parser()
        args = parser.parse_args(["search", "--vibe", "calm ambient", "--min-s", "30", "--limit", "3"])
        self.assertEqual((args.vibe, args.min_s, args.limit), ("calm ambient", 30.0, 3))
        args = parser.parse_args(["fetch", "ia-foo", "--duration", "30"])
        self.assertEqual((args.target, args.duration, args.stage_dir), ("ia-foo", 30.0, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
