import stat
import tempfile
from pathlib import Path

from whatsapp_mcp import media

PN = "5511999990000"


def test_sanitize_name():
    cases = {
        "../../etc/passwd": "etc_passwd",
        "..": "file",
        ".": "file",
        "": "file",
        None: "file",
        "/abs/path.jpg": "abs_path.jpg",
        "a\x01b\nc.jpg": "a_b_c.jpg",
        "invoice .pdf": "invoice_.pdf",
        "-leading-dash.png": "leading-dash.png",
    }
    for raw, want in cases.items():
        assert media.sanitize_name(raw) == want, (raw, media.sanitize_name(raw))
    assert media.sanitize_name(None, fallback="message") == "message"
    assert "/" not in media.sanitize_name("a/b/c")
    assert "\\" not in media.sanitize_name("a\\b.txt")


def test_download_name_is_name_max_safe():
    name = media.download_name("3EB0ABCDEF0123456789", "x" * 400 + ".jpeg")
    assert len(name.encode()) <= media.NAME_MAX, len(name.encode())
    assert name.endswith(".jpeg") and name.startswith("3EB0ABCDEF0123456789-")
    long_id = media.download_name("y" * 400, None)
    assert len(long_id.encode()) <= media.NAME_MAX


def test_write_download_perms_and_no_overwrite():
    with tempfile.TemporaryDirectory() as d:
        first = media.write_download(d, "MSG1", "photo.jpg", b"one")
        second = media.write_download(d, "MSG1", "photo.jpg", b"two")
        assert first != second and first.name.startswith("MSG1-photo.jpg")
        assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
        assert stat.S_IMODE(first.stat().st_mode) == 0o600
        assert stat.S_IMODE((Path(d) / "downloads").stat().st_mode) == 0o700
        assert first.parent == Path(d) / "downloads"
        # a hostile remote name cannot escape the downloads dir
        escaped = media.write_download(d, "MSG2", "../../../tmp/evil", b"x")
        assert escaped.parent == (Path(d) / "downloads").resolve() or escaped.parent == Path(d) / "downloads"
        assert not (Path(d).parent / "evil").exists()


def test_symlinked_downloads_dir_is_rejected():
    with tempfile.TemporaryDirectory() as d:
        outside = Path(d) / "outside"
        outside.mkdir()
        (Path(d) / "downloads").symlink_to(outside, target_is_directory=True)
        try:
            media.write_download(d, "MSG3", "a.txt", b"x")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError for a symlinked downloads dir")
        assert list(outside.iterdir()) == []


if __name__ == "__main__":
    test_sanitize_name()
    test_download_name_is_name_max_safe()
    test_write_download_perms_and_no_overwrite()
    test_symlinked_downloads_dir_is_rejected()
    print("ok")
