import json
import tempfile
from pathlib import Path

from vikunja_mcp.config import ConfigError, VikunjaConfig, load_config


def test_load_config_minimal():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.json"
        path.write_text(json.dumps({"base_url": "https://vikunja.example.com", "token": "tok"}))
        cfg = load_config(path)
        assert cfg == VikunjaConfig(base_url="https://vikunja.example.com", token="tok")


def test_load_config_strips_trailing_slash():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.json"
        path.write_text(json.dumps({"base_url": "https://vikunja.example.com/", "token": "tok"}))
        cfg = load_config(path)
        assert cfg.base_url == "https://vikunja.example.com"


def test_load_config_missing_field():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.json"
        path.write_text(json.dumps({"base_url": "https://vikunja.example.com"}))
        try:
            load_config(path)
            assert False, "expected ConfigError"
        except ConfigError as e:
            assert "token" in str(e)


def test_load_config_missing_file():
    try:
        load_config("/nonexistent/config.json")
        assert False, "expected ConfigError"
    except ConfigError:
        pass


if __name__ == "__main__":
    test_load_config_minimal()
    test_load_config_strips_trailing_slash()
    test_load_config_missing_field()
    test_load_config_missing_file()
    print("ok")
