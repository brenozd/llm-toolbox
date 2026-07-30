from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = "/config/config.json"
DEFAULT_DATA_DIR = "/data"

REQUIRED_FIELDS = ("server_url", "password", "file")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ActualConfig:
    server_url: str
    password: str
    file: str
    encryption_password: str | None = None
    data_dir: str = DEFAULT_DATA_DIR
    cert: bool | str = True

    @classmethod
    def from_dict(cls, raw: dict) -> "ActualConfig":
        missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            raise ConfigError(f"config missing required field(s): {', '.join(missing)}")
        return cls(
            server_url=raw["server_url"],
            password=raw["password"],
            file=raw["file"],
            encryption_password=raw.get("encryption_password"),
            data_dir=raw.get("data_dir", DEFAULT_DATA_DIR),
            cert=raw.get("cert", True),
        )


def load_config(path: str | Path | None = None) -> ActualConfig:
    config_path = Path(path or os.environ.get("ACTUAL_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.is_file():
        raise ConfigError(f"config file not found at {config_path}")
    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file at {config_path} is not valid JSON: {e}") from e
    return ActualConfig.from_dict(raw)
