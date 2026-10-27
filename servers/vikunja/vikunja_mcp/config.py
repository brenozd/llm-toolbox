from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = "/config/config.json"

REQUIRED_FIELDS = ("base_url", "token")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class VikunjaConfig:
    base_url: str
    token: str = field(repr=False)

    @classmethod
    def from_dict(cls, raw: dict) -> "VikunjaConfig":
        missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            raise ConfigError(f"config missing required field(s): {', '.join(missing)}")
        return cls(base_url=raw["base_url"].rstrip("/"), token=raw["token"])


def load_config(path: str | Path | None = None) -> VikunjaConfig:
    config_path = Path(path or os.environ.get("VIKUNJA_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.is_file():
        raise ConfigError(f"config file not found at {config_path}")
    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file at {config_path} is not valid JSON: {e}") from e
    return VikunjaConfig.from_dict(raw)
