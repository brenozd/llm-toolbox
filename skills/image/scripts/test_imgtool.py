#!/usr/bin/env python3
"""Unit tests for imgtool.py. Run: python3 -m unittest test_imgtool -v"""

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import imgtool  # noqa: E402


class ImgtoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "src.png"
        Image.new("RGB", (400, 200), "blue").save(self.src)
        self.parser = imgtool.build_parser()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *flags):
        args = self.parser.parse_args([str(self.src), *flags])
        return imgtool.run(self.src, args)

    def test_crop(self):
        out = self._run("--crop", "0,0,100,100")
        with Image.open(out) as img:
            self.assertEqual(img.size, (100, 100))

    def test_rotate(self):
        out = self._run("--rotate", "90")
        with Image.open(out) as img:
            self.assertEqual(img.size, (200, 400))

    def test_resize_width_only(self):
        out = self._run("--resize", "200")
        with Image.open(out) as img:
            self.assertEqual(img.size, (200, 100))

    def test_resize_wxh(self):
        out = self._run("--resize", "50x50")
        with Image.open(out) as img:
            self.assertEqual(img.size, (50, 50))

    def test_scale(self):
        out = self._run("--scale", "0.5")
        with Image.open(out) as img:
            self.assertEqual(img.size, (200, 100))

    def test_blur(self):
        out = self._run("--blur", "3")
        self.assertTrue(out.exists())

    def test_sharpen(self):
        out = self._run("--sharpen")
        self.assertTrue(out.exists())

    def test_grayscale(self):
        out = self._run("--grayscale")
        self.assertTrue(out.exists())

    def test_brightness(self):
        out = self._run("--brightness", "1.5")
        self.assertTrue(out.exists())

    def test_contrast(self):
        out = self._run("--contrast", "1.5")
        self.assertTrue(out.exists())

    def test_saturation(self):
        out = self._run("--saturation", "0.5")
        self.assertTrue(out.exists())

    def test_flip_horizontal(self):
        out = self._run("--flip", "horizontal")
        with Image.open(out) as img:
            self.assertEqual(img.size, (400, 200))

    def test_flip_vertical(self):
        out = self._run("--flip", "vertical")
        with Image.open(out) as img:
            self.assertEqual(img.size, (400, 200))

    def test_flip_invalid_direction_raises(self):
        img = Image.new("RGB", (10, 10))
        with self.assertRaises(ValueError):
            imgtool.op_flip(img, "sideways")

    def test_text_overlay(self):
        out = self._run("--text", "hi", "--text-pos", "5,5")
        self.assertTrue(out.exists())

    def test_format_convert_jpeg(self):
        out = self._run("--format", "jpeg")
        self.assertEqual(out.suffix, ".jpg")
        with Image.open(out) as img:
            self.assertEqual(img.mode, "RGB")

    def test_format_convert_webp(self):
        out = self._run("--format", "webp")
        self.assertEqual(out.suffix, ".webp")

    def test_chained_ops(self):
        out = self._run("--crop", "0,0,300,150", "--rotate", "90", "--blur", "2", "--resize", "100")
        with Image.open(out) as img:
            self.assertEqual(img.size[0], 100)

    def test_explicit_output_path(self):
        target = Path(self.tmp.name) / "custom.png"
        out = self._run("--output", str(target))
        self.assertEqual(out, target)
        self.assertTrue(target.exists())

    def test_main_requires_input(self):
        self.assertEqual(imgtool.main([]), 1)

    def test_main_selftest_flag(self):
        self.assertEqual(imgtool.main(["--selftest"]), 0)


if __name__ == "__main__":
    unittest.main()
