#!/usr/bin/env python3
"""Unit tests for screencapture.py. Run: python3 -m unittest test_screencapture -v

Desktop/clipboard capture needs a live graphical session so those paths
aren't exercised here -- only the pure/stdlib pieces are (resize, format
conversion, CDP web capture, DOM capture, session list/clear).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import screencapture as shot  # noqa: E402


class ResizeFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.img_path = Path(self.tmp.name) / "test.png"
        Image.new("RGB", (400, 200), "red").save(self.img_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_resize_keeps_aspect(self):
        shot.resize_image(self.img_path, 200)
        with Image.open(self.img_path) as img:
            self.assertEqual(img.size, (200, 100))

    def test_convert_to_jpeg_removes_source(self):
        jpeg_path = shot.convert_to_jpeg(self.img_path)
        self.assertEqual(jpeg_path.suffix, ".jpg")
        self.assertTrue(jpeg_path.exists())
        self.assertFalse(self.img_path.exists())


class WebCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_web_about_blank(self):
        out = Path(self.tmp.name) / "web.png"
        shot.capture_web("about:blank", out, width=800, height=600, full_page=True)
        self.assertTrue(out.exists())
        with Image.open(out) as img:
            self.assertEqual(img.width, 800)

    def test_capture_dom_about_blank(self):
        out = Path(self.tmp.name) / "dom.html"
        shot.capture_dom("about:blank", out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)


class SessionTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_cwd = Path.cwd()
        import os
        os.chdir(self.tmp.name)

    def tearDown(self):
        import os
        os.chdir(self._orig_cwd)
        self.tmp.cleanup()

    def test_track_and_list(self):
        shot_dir = Path(self.tmp.name) / ".screenshots"
        shot_dir.mkdir()
        f = shot_dir / "shot-1.png"
        Image.new("RGB", (10, 10)).save(f)
        shot._track(f)
        log = shot._session_log()
        self.assertTrue(log.exists())
        self.assertIn(str(f), log.read_text())

    def test_safe_to_delete_rejects_outside_screenshots_dir(self):
        outside = Path(self.tmp.name) / "not-screenshots"
        outside.mkdir()
        f = outside / "shot.png"
        f.touch()
        self.assertFalse(shot._safe_to_delete(f))

    def test_clear_yes_removes_tracked_files(self):
        shot_dir = Path(self.tmp.name) / ".screenshots"
        shot_dir.mkdir()
        f = shot_dir / "shot-1.png"
        Image.new("RGB", (10, 10)).save(f)
        shot._track(f)
        shot.clear_screenshots(confirm=False)
        self.assertFalse(f.exists())
        self.assertFalse(shot._session_log().exists())

    def test_list_with_no_session(self):
        self.assertEqual(shot.list_screenshots(), 0)


class ArgParsingTests(unittest.TestCase):
    def test_main_selftest_flag(self):
        self.assertEqual(shot.main(["--selftest"]), 0)

    def test_viewport_preset_values(self):
        self.assertEqual(shot.VIEWPORTS["mobile"], (390, 844))
        self.assertEqual(shot.VIEWPORTS["tablet"], (768, 1024))




def test_record_steps_validation():
    import record
    import pytest
    ok = record.load_steps('[{"type":"type","text":"ls"},{"type":"click","x":1,"y":2},{"type":"hold_s","s":1}]')
    assert len(ok) == 3
    for bad in ('[]', '[{"type":"nope"}]', '[{"type":"type"}]', '[{"type":"click"}]', '[{"type":"wait_for"}]'):
        with pytest.raises(ValueError):
            record.load_steps(bad)


def test_record_finalize_gif(tmp_path):
    import record
    import subprocess
    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    for ext in (".gif", ".webm", ".mp4"):
        record.finalize(src, tmp_path / f"o{ext}")
        assert (tmp_path / f"o{ext}").stat().st_size > 0


def test_record_gui_rejects_web_steps(tmp_path):
    import record
    import pytest
    with pytest.raises((ValueError, RuntimeError)):
        record.record_gui("true", [{"type": "goto", "url": "x"}], tmp_path / "o.mp4")


class RecordPrivacy(unittest.TestCase):
    def test_receipt_omits_typed_text_and_output_by_default(self):
        import record, tempfile
        out = Path(tempfile.mkdtemp()) / "a.mp4"
        meta = {"steps": [{"type": "type", "text": "export K=secret"}, {"type": "key", "key": "Return"}], "output": "x"}
        record.write_receipt(out, meta, False)
        saved = json.loads(out.with_suffix(".json").read_text())
        self.assertEqual(saved["steps"][0]["text"], "<omitted>")
        self.assertNotIn("output", saved)

    def test_secret_scan(self):
        import record
        self.assertTrue(record.secret_warnings("AWS key " + "AKIA" + "ABCDEFGHIJKLMNOP"))
        self.assertTrue(record.secret_warnings('{"api_' + 'key": "sk-' + 'abcdef1234567890"}'))
        self.assertTrue(record.secret_warnings("Authorization: Bear" + "er abcdef1234567890xyz"))
        self.assertFalse(record.secret_warnings('password = os.environ["PASSWORD_VAR_X"]'))
        self.assertFalse(record.secret_warnings("hello world"))

    def test_geometry_table(self):
        import record
        self.assertEqual(record.GEOMETRY["9:16"]["gui"], (720, 1280))


if __name__ == "__main__":
    unittest.main()
