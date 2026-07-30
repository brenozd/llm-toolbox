import json
import tempfile
from pathlib import Path

from actual_budget_mcp.config import ActualConfig, ConfigError, load_config


def test_load_config_minimal():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.json"
        path.write_text(json.dumps({"server_url": "http://x:5006", "password": "pw", "file": "my-budget"}))
        cfg = load_config(path)
        assert cfg == ActualConfig(server_url="http://x:5006", password="pw", file="my-budget")


def test_load_config_missing_field():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.json"
        path.write_text(json.dumps({"server_url": "http://x:5006"}))
        try:
            load_config(path)
            assert False, "expected ConfigError"
        except ConfigError as e:
            assert "password" in str(e) and "file" in str(e)


def test_load_config_missing_file():
    try:
        load_config("/nonexistent/config.json")
        assert False, "expected ConfigError"
    except ConfigError:
        pass


if __name__ == "__main__":
    test_load_config_minimal()
    test_load_config_missing_field()
    test_load_config_missing_file()
    print("ok")
