#!/usr/bin/env python3
"""Testes do review.py. Rodar de dentro de scripts/: python3 -m unittest test_review -v"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import review  # noqa: E402


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, tris, name="f.stl", binary=False):
        path = self.dir / name
        review.write_stl(tris, path, binary=binary)
        return path

    def test_cube_ascii_and_binary(self):
        for binary in (False, True):
            tris, fmt = review.read_stl(self._write(review.cube_tris(), binary=binary))
            self.assertEqual(fmt, "binary" if binary else "ascii")
            m = review.analyze(tris)
            self.assertEqual(len(tris), 12)
            self.assertEqual(m["bad_edges"], 0)
            self.assertEqual(m["shells"], 1)
            self.assertAlmostEqual(m["volume"], 1000, places=3)
            self.assertAlmostEqual(m["base_area"], 100.0)
            self.assertAlmostEqual(m["down_area"], 100.0)
            self.assertEqual(m["overhang_area"], 0)

    def test_hollow_flat_base_passes(self):
        m = review.analyze(review.frame_tris())
        self.assertTrue(review.base_flat(m))
        # menos de 50 % da bbox apoiada: o critério antigo reprovava esta peça
        self.assertLess(m["base_area"], 0.5 * m["size"][0] * m["size"][1])
        self.assertAlmostEqual(m["base_area"], m["down_area"])

    def test_stepped_base_fails(self):
        m = review.analyze(review.step_tris())
        self.assertFalse(review.base_flat(m))
        self.assertLess(m["base_area"], 0.9 * m["down_area"])

    def test_missing_triangle_breaks_watertight(self):
        m = review.analyze(review.cube_tris()[1:])
        self.assertGreater(m["bad_edges"], 0)

    def test_two_shells(self):
        far = [tuple((p[0] + 20, p[1], p[2]) for p in t) for t in review.cube_tris()]
        m = review.analyze(review.cube_tris() + far)
        self.assertEqual(m["shells"], 2)

    def test_inverted_normals(self):
        m = review.analyze([tuple(reversed(t)) for t in review.cube_tris()])
        self.assertLess(m["volume"], 0)

    def test_floating_box_is_detected_by_zmin(self):
        up = [tuple((p[0], p[1], p[2] + 5) for p in t) for t in review.cube_tris()]
        self.assertAlmostEqual(review.analyze(up)["min"][2], 5.0)

    def test_cantilever_is_overhang(self):
        plate = [tuple((x * 3 - 10, y * 3 - 10, z + 10) for x, y, z in t)
                 for t in review.cube_tris()]
        m = review.analyze(review.cube_tris() + plate)
        self.assertAlmostEqual(m["overhang_area"], 900.0)
        self.assertAlmostEqual(m["overhang_z"], 10.0)

    def test_echo_values(self):
        text = 'ECHO: "CHK|wall=3.2|hole=4.2@0"\n'
        self.assertEqual(review.echo_values(text),
                         [("wall", "3.2"), ("hole", "4.2@0")])


class LintTests(unittest.TestCase):
    def test_inputs_are_bare_literals_only(self):
        src = ("w = 10;\nd = 20.5;\nx = w / 2;\n$fn = $preview ? 32 : 64;\n"
               "module p() {\n  cube([3, w, 7]);\n}\n")
        inputs, lits = review.lint(src)
        self.assertEqual(inputs, ["w", "d"])
        self.assertEqual(sorted(v for _, v in lits), ["3", "7"])

    def test_no_module_means_everything_is_input(self):
        inputs, lits = review.lint("a = 1;\nb = 2;\n")
        self.assertEqual(inputs, ["a", "b"])
        self.assertEqual(lits, [])

    def test_top_level_assert_and_formula_are_not_literals(self):
        src = ("L = 50;\nD = 20 * L / (12 * L);\n"
               "assert(15 < D && D < 25, \"fora da faixa\");\n"
               "echo(str(\"CHK|L=\", L));\n"
               "module p() {\n  cube([L, 3, 7]);\n}\n")
        inputs, lits = review.lint(src)
        self.assertEqual(inputs, ["L"])
        self.assertEqual(lits, [(6, "3"), (6, "7")])

    def test_literal_in_module_still_warns(self):
        one_line = "w = 10;\nmodule p() { cube([w, 3, 7]); }\ncube([w, 4, w]);\n"
        _, lits = review.lint(one_line)
        # módulo de uma linha fecha no mesmo nível; o cube() de topo não conta
        self.assertEqual(lits, [(2, "3"), (2, "7")])


class CliTests(unittest.TestCase):
    def test_selftest_passes(self):
        self.assertEqual(review.main(["--selftest"]), 0)
        self.assertEqual(review.selftest(), 0)

    def test_review_missing_file_fails(self):
        rep = review.review(Path("/nonexistent/x.scad"),
                            review.build_parser().parse_args(["x.scad"]))
        self.assertTrue(rep.fails())


if __name__ == "__main__":
    unittest.main()
