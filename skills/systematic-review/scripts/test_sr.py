#!/usr/bin/env python3
"""Offline tests for sr.py. No network, no keys.

Run: python3 -m pytest -q skills/systematic-review/scripts
     (or directly: python3 skills/systematic-review/scripts/test_sr.py)

fixtures/ are trimmed real responses (2026-11): OpenAlex search + single work, Europe PMC
search, arXiv Atom. The live S2 and Unpaywall calls were refused (429 without a key /
422 on the email), so s2_graphene.json and unpaywall_nature12373.json are synthetic dicts
shaped like their documented replies; s2_429.json *is* the recorded refusal body.
"""

import contextlib
import csv
import difflib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sr as S

FIXTURES = HERE / "fixtures"


def fixture(name):
    path = FIXTURES / name
    return path.read_text() if path.suffix == ".xml" else json.loads(path.read_text())


def stub(payload):
    """Stands in for http_get; records the URLs asked for."""
    calls = []

    def fake(url, **kw):
        calls.append((url, kw))
        return payload if isinstance(payload, str) else json.dumps(payload)

    return fake, calls


def run(argv):
    """Run a subcommand and return the JSON it printed to stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        S.main(argv)
    return json.loads(buf.getvalue())


def run_fails(argv):
    """-> (exit code, stderr) for a subcommand that refused to answer."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            S.main(argv)
        except SystemExit as exc:
            return exc.code, err.getvalue()
    raise AssertionError("expected a non-zero exit")


class RecordIdTests(unittest.TestCase):
    def test_same_paper_from_two_sources_shares_one_id(self):
        a = S.record(doi="https://doi.org/10.1038/NATURE12373", title="X", source="openalex")
        b = S.record(doi="doi:10.1038/nature12373", title="A different title", source="s2")
        self.assertEqual(a["id"], b["id"])

    def test_no_doi_falls_back_to_normalised_title(self):
        a = S.record(title="Raman  Spectrum of Graphene!", source="openalex")
        b = S.record(title="raman spectrum of graphene", source="epmc")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["id"], S.record(title="Graphene", source="epmc")["id"])

    def test_norm_doi_strips_prefixes(self):
        for raw in ("https://doi.org/10.1/A ", "http://dx.doi.org/10.1/a", "DOI:10.1/a", "10.1/A."):
            self.assertEqual(S.norm_doi(raw), "10.1/a", raw)


class SearchTests(unittest.TestCase):
    def test_openalex_reassembles_inverted_abstract(self):
        fake, calls = stub(fixture("openalex_graphene.json"))
        with mock.patch.object(S, "http_get", fake):
            out = run(["search", "--db", "openalex", "--query", "graphene", "--limit", "3"])
        self.assertEqual(out["source"], "openalex")
        self.assertEqual(out["total"], 824774)
        self.assertEqual((out["returned"], len(out["records"])), (2, 2))
        self.assertIn("Raman", out["records"][0]["abstract"])
        self.assertEqual(out["records"][0]["abstract"], out["records"][0]["abstract"].strip())
        self.assertFalse(out["records"][1]["abstract"])  # a work without an abstract stays empty
        self.assertEqual(out["records"][0]["doi"], "10.1103/physrevlett.97.187401")
        self.assertIn("search=graphene", calls[0][0])

    def test_epmc_reads_hitcount_and_year(self):
        fake, _ = stub(fixture("epmc_graphene.json"))
        with mock.patch.object(S, "http_get", fake):
            out = run(["search", "--db", "epmc", "--query", "graphene", "--limit", "3"])
        self.assertEqual(out["total"], 176566)
        self.assertEqual(out["returned"], 2)
        self.assertIsInstance(out["records"][0]["year"], int)
        self.assertTrue(out["records"][0]["abstract"])

    def test_s2_parses_total_and_missing_doi(self):
        fake, _ = stub(fixture("s2_graphene.json"))
        with mock.patch.object(S, "http_get", fake):
            out = run(["search", "--db", "s2", "--query", "graphene", "--limit", "3"])
        self.assertEqual(out["total"], 824774)
        self.assertEqual(out["returned"], 2)
        self.assertEqual(out["records"][1]["doi"], "")  # no DOI -> id comes from the title

    def test_arxiv_reads_atom_and_total(self):
        fake, _ = stub(fixture("arxiv_graphene.xml"))
        with mock.patch.object(S, "http_get", fake):
            out = run(["search", "--db", "arxiv", "--query", "graphene", "--limit", "2"])
        self.assertEqual(out["total"], 22112)
        self.assertEqual(out["returned"], 2)
        self.assertTrue(out["records"][0]["url"].startswith("http://arxiv.org/abs/"))
        self.assertEqual(out["records"][0]["doi"], "10.4236/graphene.2014.32004")

    def test_search_writes_out_file(self):
        fake, _ = stub(fixture("openalex_graphene.json"))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(S, "http_get", fake):
            out_path = Path(tmp) / "search" / "openalex-graphene.json"
            run(["search", "--db", "openalex", "--query", "graphene", "--limit", "2", "--out", str(out_path)])
            self.assertEqual(json.loads(out_path.read_text())["total"], 824774)

    def test_s2_429_is_a_wait_not_an_empty_result(self):
        """Exhausted retries must raise: a 429 body must never be read as total 0."""
        with mock.patch.object(S, "s2_get", mock.Mock(side_effect=S.HttpStatusError("429"))):
            code, err = run_fails(["search", "--db", "s2", "--query", "graphene"])
        self.assertEqual(code, 2)
        self.assertIn("429", err)
        self.assertEqual(fixture("s2_429.json")["code"], "429")  # the recorded refusal

    def test_s2_get_sends_api_key_and_more_tries(self):
        fake, calls = stub(fixture("s2_graphene.json"))
        with mock.patch.object(S, "http_get", fake), mock.patch.dict("os.environ", {"S2_API_KEY": "k1"}):
            S.s2_get("https://api.semanticscholar.org/graph/v1/paper/search?query=x")
        self.assertEqual(calls[0][1]["tries"], 6)
        self.assertEqual(calls[0][1]["headers"], {"x-api-key": "k1"})

    def test_retry_after_caps_and_ignores_garbage(self):
        err = mock.Mock(headers={"Retry-After": "3600"})
        self.assertEqual(S._retry_after(err), 30.0)
        self.assertIsNone(S._retry_after(mock.Mock(headers={})))

    def test_404_is_final_and_not_retried(self):
        """A fabricated DOI must fail on the first answer, not after four backoffs."""
        fake = mock.Mock(side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None))
        with mock.patch.object(urllib.request, "urlopen", fake), mock.patch.object(S.time, "sleep") as slept:
            with self.assertRaises(S.HttpStatusError):
                S.http_get("https://api.openalex.org/works/10.9999/fake.12345")
        self.assertEqual(fake.call_count, 1)
        slept.assert_not_called()

    def test_503_is_retried(self):
        fake = mock.Mock(side_effect=urllib.error.HTTPError("u", 503, "busy", {}, None))
        with mock.patch.object(urllib.request, "urlopen", fake), mock.patch.object(S.time, "sleep"):
            with self.assertRaises(S.HttpStatusError):
                S.http_get("https://example.org", tries=3)
        self.assertEqual(fake.call_count, 3)


class ArxivThrottleTests(unittest.TestCase):
    def test_waits_for_the_gap_and_stamps_the_call(self):
        import time

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "sr-arxiv.stamp").write_text(str(time.time()))
            fake, _ = stub(fixture("arxiv_graphene.xml"))
            with mock.patch.object(S, "STATE", state), mock.patch.object(S, "http_get", fake), mock.patch.object(S.time, "sleep") as slept:
                S.arxiv_get("https://export.arxiv.org/api/query?search_query=all:x")
            self.assertEqual(slept.call_count, 1)
            self.assertGreater(slept.call_args[0][0], 2.0)
            self.assertGreater(float((state / "sr-arxiv.stamp").read_text()), time.time() - 5)

    def test_no_wait_when_the_last_call_is_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "sr-arxiv.stamp").write_text("0")
            fake, _ = stub(fixture("arxiv_graphene.xml"))
            with mock.patch.object(S, "STATE", state), mock.patch.object(S, "http_get", fake), mock.patch.object(S.time, "sleep") as slept:
                S.arxiv_get("https://export.arxiv.org/api/query?search_query=all:x")
            slept.assert_not_called()


class OaAndCitesTests(unittest.TestCase):
    def test_oa_refuses_without_sr_email(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code, err = run_fails(["oa", "10.1038/nature12373"])
        self.assertNotEqual(code, 0)
        self.assertIn("SR_EMAIL", err)

    def test_oa_reads_unpaywall_location(self):
        fake, calls = stub(fixture("unpaywall_nature12373.json"))
        with mock.patch.object(S, "http_get", fake), mock.patch.dict("os.environ", {"SR_EMAIL": "a@b.org"}):
            out = run(["oa", "10.1038/nature12373"])
        self.assertIn("email=a%40b.org", calls[0][0])
        rec = out["records"][0]
        self.assertTrue(rec["is_oa"])
        self.assertEqual(rec["oa_status"], "green")
        self.assertTrue(rec["pdf_url"].endswith("?pdf=render"))

    def test_cites_back_and_forward(self):
        back = {"data": [{"citedPaper": {"title": "Old", "year": 1999, "externalIds": {"DOI": "10.1/old"}, "citationCount": 5}}]}
        fwd = {"data": [{"citingPaper": {"title": "New", "year": 2021, "externalIds": {"DOI": "10.1/new"}, "citationCount": 1}}]}
        with mock.patch.object(S, "http_get", stub(back)[0]):
            out = run(["cites", "10.1038/nature12373", "--dir", "back"])
        self.assertEqual((out["dir"], out["total"], out["records"][0]["doi"]), ("back", 1, "10.1/old"))
        self.assertEqual((out["source"], out["records"][0]["source"]), ("snowball", "snowball"))  # not folded into s2
        fake, calls = stub(fwd)
        with mock.patch.object(S, "http_get", fake):
            out = run(["cites", "10.1038/nature12373", "--dir", "fwd"])
        self.assertIn("/citations?", calls[0][0])
        self.assertEqual(out["records"][0]["title"], "New")


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "verified.json"

    def test_existing_doi_verifies_and_is_logged(self):
        with mock.patch.object(S, "http_get", stub(fixture("openalex_work_nature12373.json"))[0]):
            out = run(["verify", "10.1038/nature12373", "--out", str(self.log)])
        self.assertTrue(out["records"][0]["ok"])
        self.assertEqual(json.loads(self.log.read_text())[0]["doi"], "10.1038/nature12373")

    def test_fabricated_doi_fails_closed(self):
        fake = mock.Mock(side_effect=S.HttpStatusError("404 Not Found"))
        with mock.patch.object(S, "http_get", fake):
            code, err = run_fails(["verify", "10.9999/fake.12345", "--out", str(self.log)])
        self.assertEqual(code, 2)
        self.assertIn("could not be resolved", err)
        self.assertFalse(self.log.exists())  # nothing gets logged on failure

    def test_network_error_fails_closed(self):
        fake = mock.Mock(side_effect=OSError("network unreachable"))
        with mock.patch.object(S, "http_get", fake):
            code, _ = run_fails(["verify", "10.1038/nature12373", "--out", str(self.log)])
        self.assertNotEqual(code, 0)

    def test_title_mismatch_exits_non_zero(self):
        with mock.patch.object(S, "http_get", stub(fixture("openalex_work_nature12373.json"))[0]):
            code, err = run_fails(["verify", "10.1038/nature12373", "--title", "Graphene transistors for everyone", "--out", str(self.log)])
        self.assertEqual(code, 1)
        self.assertIn("mismatch", err)
        self.assertFalse(json.loads(self.log.read_text())[0]["ok"])

    def test_title_similarity_tolerates_case_and_punctuation(self):
        with mock.patch.object(S, "http_get", stub(fixture("openalex_work_nature12373.json"))[0]):
            out = run(["verify", "10.1038/nature12373", "--title", "Nanometre-scale thermometry in a living cell.", "--out", str(self.log)])
        self.assertTrue(out["records"][0]["ok"])

    def test_entry_uses_the_template_keys(self):
        """templates/report.md quotes `title_similarity`; `similarity` would not be reproducible."""
        with mock.patch.object(S, "http_get", stub(fixture("openalex_work_nature12373.json"))[0]):
            entry = run(["verify", "10.1038/nature12373", "--out", str(self.log)])["records"][0]
        self.assertEqual(entry["title_similarity"], 1.0)
        self.assertNotIn("similarity", entry)
        self.assertEqual(entry["url"], "")

    def test_arxiv_url_drops_the_id_prefix_and_stores_a_url_not_a_doi(self):
        page = "<html><head><title>[2408.04646v2] Nanometre-scale thermometry in a living cell</title></head></html>"
        with mock.patch.object(S, "http_get", stub(page)[0]):
            entry = run(["verify", "https://arxiv.org/abs/2408.04646v2", "--title", "Nanometre-scale thermometry in a living cell", "--out", str(self.log)])["records"][0]
        self.assertEqual(entry["title"], "Nanometre-scale thermometry in a living cell")
        self.assertTrue(entry["ok"])  # 0.894 with the prefix -> 1.0 without it
        self.assertEqual(entry["url"], "https://arxiv.org/abs/2408.04646v2")
        self.assertEqual(entry["doi"], "")


class DedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "records.csv"

    def writes(self, name, records):
        path = self.dir / name
        path.write_text(json.dumps({"source": name.split("-")[0], "query": "q", "total": 9, "returned": len(records), "records": records}))
        return path

    def test_merges_by_doi_then_title_and_links_near_duplicates(self):
        a = self.writes("openalex-graphene.json", [
            S.record(doi="https://doi.org/10.1/A", title="Raman spectrum of graphene", source="openalex"),
            S.record(title="Graphene thermometry in living cells", source="openalex"),
        ])
        b = self.writes("s2-graphene.json", [
            S.record(doi="doi:10.1/a", title="Raman spectrum of graphene layers", source="s2"),
            S.record(title="Graphene thermometry in living cells!", source="s2"),
            S.record(title="Graphene thermometry in a living cell", source="s2"),
        ])
        out = run(["dedupe", str(a), str(b), "--out", str(self.out)])
        self.assertEqual((out["total"], out["returned"], out["duplicates_removed"]), (5, 3, 2))
        rows = list(csv.DictReader(self.out.open()))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["sources"], "openalex,s2")  # every source that saw the record
        self.assertEqual(len({r["study_id"] for r in rows}), 2)  # the two thermometry titles are one study
        self.assertTrue(out["near_duplicates"])
        self.assertEqual(len({r["id"] for r in rows}), 3)  # stable ids survive the merge

    def test_links_only_at_95_so_a_human_sees_the_rest(self):
        a = self.writes("openalex-graphene.json", [
            S.record(doi="10.1/p", title="Graphene thermometry in living cells", source="openalex"),
            S.record(doi="10.1/q", title="Graphene thermometry of living cells", source="openalex"),
        ])
        out = run(["dedupe", str(a), "--out", str(self.out)])
        rows = list(csv.DictReader(self.out.open()))
        self.assertLess(difflib.SequenceMatcher(None, "graphene thermometry in living cells", "graphene thermometry of living cells").ratio(), S.NEAR_TITLE)
        self.assertEqual(len({r["study_id"] for r in rows}), 2)  # 0.94 is not an auto-link
        self.assertEqual(out["near_duplicates"], [])

    def test_ids_are_stable_across_runs(self):
        a = self.writes("openalex-graphene.json", [S.record(doi="10.1/x", title="T", source="openalex")])
        first = run(["dedupe", str(a), "--out", str(self.out)])["near_duplicates"]
        second = run(["dedupe", str(a), "--out", str(self.out)])["near_duplicates"]
        rows = list(csv.DictReader(self.out.open()))
        self.assertEqual(first, second)
        self.assertEqual(rows[0]["id"], S.stable_id("10.1/x", "T"))


class VersionTests(unittest.TestCase):
    def test_version_comes_from_skill_md(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as raised:
            S.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertRegex(buf.getvalue().strip(), r"^\d+\.\d+\.\d+$")


class ScreenDiffTests(unittest.TestCase):
    def test_counts_agreement_and_disagreeing_ids(self):
        out = run(["screen-diff", str(FIXTURES / "screen_t1_a.csv"), str(FIXTURES / "screen_t1_b.csv")])
        self.assertEqual(out["total"], 4)  # ids seen by both passes
        self.assertEqual(out["agreement_pct"], 75.0)
        self.assertEqual(out["disagreeing_ids"], ["id-02"])
        self.assertEqual(out["only_in_a"], ["id-05"])
        self.assertEqual(out["only_in_b"], ["id-06"])
        self.assertEqual(out["counts"]["a"]["exclude"], 2)
        self.assertEqual(out["returned"], len(out["disagreeing_ids"]))

    def test_empty_overlap_does_not_divide_by_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "a.csv"
            two = Path(tmp) / "b.csv"
            one.write_text("id,decision,reason\nx,include,\n")
            two.write_text("id,decision,reason\ny,exclude,\n")
            out = run(["screen-diff", str(one), str(two)])
        self.assertEqual((out["total"], out["agreement_pct"]), (0, 0.0))

    def test_arbitrated_covers_the_done_check(self):
        """done = every disagreeing id has a row in the arbitrated t1.csv."""
        out = run(["screen-diff", str(FIXTURES / "screen_t1_a.csv"), str(FIXTURES / "screen_t1_b.csv")])
        self.assertEqual(out["unarbitrated_ids"], ["id-02"])  # no --arbitrated: nothing is resolved
        with tempfile.TemporaryDirectory() as tmp:
            t1 = Path(tmp) / "t1.csv"
            t1.write_text("id,decision,reason\nid-02,include,doubt: keep\n")
            out = run(["screen-diff", str(FIXTURES / "screen_t1_a.csv"), str(FIXTURES / "screen_t1_b.csv"), "--arbitrated", str(t1)])
        self.assertEqual(out["unarbitrated_ids"], [])
        self.assertEqual(out["disagreeing_ids"], ["id-02"])


class PrismaTests(unittest.TestCase):
    def test_arithmetic_from_the_recorded_review_dir(self):
        out = run(["prisma", str(FIXTURES / "review")])
        self.assertEqual(out["total"], out["counts"]["identified"])
        self.assertEqual(out["returned"], out["counts"]["included"])
        self.assertTrue(out["balanced"])
        self.assertEqual(
            out["counts"],
            {
                "identified": 8,          # 5 openalex + 3 s2 returned
                "duplicates_removed": 2,  # 8 - 6 unique rows
                "screened": 6,
                "excluded_stage1": 1,
                "sought_full_text": 5,
                "not_retrieved": 1,
                "full_text_assessed": 4,
                "excluded_stage2": 2,
                "included": 2,
                "included_studies": 2,
            },
        )
        self.assertEqual(out["per_source"], {"openalex": 5, "s2": 3})
        self.assertEqual(out["per_source_total"], {"openalex": 900, "s2": 800})
        self.assertEqual(out["excluded_reasons"], {"wrong population": 2})

    def test_included_counts_reports_and_studies_separately(self):
        """Two reports of one study are 2 included records but 1 included study."""
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "review"
            shutil.copytree(FIXTURES / "review", copy)
            rows = list(csv.DictReader((copy / "records.csv").open(newline="")))
            for row in rows:
                if row["id"] == "id-02":
                    row["study_id"] = "id-01"  # id-01 and id-02 are two reports of one study
            with (copy / "records.csv").open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            out = run(["prisma", str(copy)])
        self.assertEqual((out["counts"]["included"], out["counts"]["included_studies"]), (2, 1))
        self.assertTrue(out["balanced"])

    def test_stage_1_checkpoint_balances_before_stage_2_files_exist(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "review"
            shutil.copytree(FIXTURES / "review", copy)
            (copy / "screening" / "t2.csv").unlink()
            code, _ = run_fails(["prisma", str(copy)])  # full check still refuses
            self.assertEqual(code, 1)
            out = run(["prisma", str(copy), "--stage", "1"])
        self.assertTrue(out["balanced"])
        self.assertEqual(out["stage"], 1)
        self.assertEqual(out["counts"]["full_text_assessed"], 0)

    def test_arbitrated_csv_overrides_the_passes(self):
        """A two-pass include must not resurrect what the human excluded, and vice versa."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "t1-A.csv").write_text("id,decision,reason\nx,exclude,no graphene\n")
            (d / "t1-B.csv").write_text("id,decision,reason\nx,exclude,no graphene\n")
            (d / "t1.csv").write_text("id,decision,reason\nx,include,doubt: keep\n")
            self.assertEqual(S.stage_decisions(d, "t1"), {"x": "include"})
            (d / "t1.csv").write_text("id,decision,reason\nx,exclude,no graphene\n")
            (d / "t1-B.csv").write_text("id,decision,reason\nx,include,\n")
            self.assertEqual(S.stage_decisions(d, "t1"), {"x": "exclude"})

    def test_snowball_hits_are_counted_apart_from_the_databases(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "review"
            shutil.copytree(FIXTURES / "review", copy)
            snow = {"source": "snowball", "query": "10.1/x0", "total": 1, "returned": 1,
                    "records": [S.record(doi="10.1/x9", title="Title 9", source="snowball")]}
            (copy / "search" / "snowball-1-back.json").write_text(json.dumps(snow))
            out = run(["prisma", str(copy)])
        self.assertEqual(out["per_source"], {"openalex": 5, "s2": 3, "snowball": 1})
        self.assertTrue(out["balanced"])

    def test_inconsistent_counts_exit_non_zero(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "review"
            shutil.copytree(FIXTURES / "review", copy)
            rows = (copy / "screening" / "t2.csv").read_text().splitlines()
            (copy / "screening" / "t2.csv").write_text("\n".join(rows[:-1]) + "\n")  # drop one decision
            code, err = run_fails(["prisma", str(copy)])
        self.assertEqual(code, 1)
        self.assertIn("do not add up", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
