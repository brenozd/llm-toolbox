from __future__ import annotations

import pytest
from PIL import Image

from document_ocr_mcp import tools as t
from document_ocr_mcp.config import Config


def cfg(tmp_path, **kw) -> Config:
    base = dict(roots=(tmp_path.resolve(),), max_bytes=1 << 20, max_pages=3, timeout_s=30, dpi=100, workers=1)
    return Config(**{**base, **kw})


def test_path_outside_roots_and_symlink_escape(tmp_path):
    inside = tmp_path / "in"
    inside.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    (inside / "link").symlink_to(secret)
    c = cfg(tmp_path, roots=(inside.resolve(),))
    for bad in (str(secret), str(inside / "link"), str(inside / ".." / "secret.txt")):
        with pytest.raises(t.OcrError, match="outside"):
            t.resolve_path(c, bad)


def test_size_limit(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"0" * 100)
    with pytest.raises(t.OcrError, match="larger"):
        t.resolve_path(cfg(tmp_path, max_bytes=10), str(f))


def test_parse_pages():
    assert t.parse_pages(None, 10, 3) == [1, 2, 3]
    assert t.parse_pages("1,3-4", 5, 5) == [1, 3, 4]
    for bad in ("0", "9", "a", "1-9", "1-4"):
        with pytest.raises(t.OcrError):
            t.parse_pages(bad, 5, 3)


def test_layer_ok():
    assert t.layer_ok("Nota fiscal número 12345 emitida em 10/10/2026 para Condomínio Milano")
    assert not t.layer_ok("3")
    assert not t.layer_ok("~~~ ### ||| --- ~~~ ### ||| --- ~~~ ### ||| --- ~~~ ###")


def test_parse_tsv_lines_and_confidence():
    hdr = "level\tpage\tblock\tpar\tline\tword\tl\tt\tw\th\tconf\ttext"
    row = lambda b, ln, w, conf, txt: f"5\t1\t{b}\t1\t{ln}\t{w}\t0\t0\t1\t1\t{conf}\t{txt}"
    tsv = "\n".join([hdr, row(1, 1, 1, 90, "Olá"), row(1, 1, 2, 80, "mundo"), row(1, 2, 1, 20, "xq"),
                     row(1, 2, 2, -1, ""), "4\t1\t1\t1\t1\t0\t0\t0\t1\t1\t-1\t"])
    text, conf, low = t.parse_tsv(tsv)
    assert text == "Olá mundo\nxq" and low == ["xq"] and conf == pytest.approx(63.33, abs=0.01)


def test_rejects_bad_lang_mode_and_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    with pytest.raises(t.OcrError, match="lang"):
        t.ocr_document(cfg(tmp_path), str(f), lang="por --psm 0")
    with pytest.raises(t.OcrError, match="mode"):
        t.ocr_document(cfg(tmp_path), str(f), mode="x")
    with pytest.raises(t.OcrError, match="unsupported"):
        t.ocr_document(cfg(tmp_path), str(f))


def test_image_routes_to_ocr_and_warns_low_res(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "run_tesseract", lambda img, lang, timeout: "level\tpage\tblock\tpar\tline\tword\tl\tt\tw\th\tconf\ttext")
    Image.new("RGB", (300, 200), "white").save(tmp_path / "a.png")
    out = t.ocr_document(cfg(tmp_path), str(tmp_path / "a.png"))
    pg = out["pages"][0]
    assert out["content_is_untrusted"] and pg["source"] == "ocr"
    assert any("low resolution" in w for w in pg["warnings"]) and any("no text" in w for w in pg["warnings"])
