from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .jid import canonical

DEFAULT_CONFIG_PATH = "/config/config.json"


class ConfigError(ValueError):
    pass


def valid_recipient(value: str) -> bool:
    return canonical(value) is not None


@dataclass(frozen=True)
class WhatsAppConfig:
    data_dir: str = "/data"
    media_dir: str = "/media"
    allow_send: bool = False
    allowed_recipients: tuple[str, ...] = ()
    max_media_bytes: int = 64 * 1024 * 1024

    @classmethod
    def from_dict(cls, raw: dict) -> WhatsAppConfig:
        if not isinstance(raw, dict):
            raise ConfigError("config must be a JSON object")
        unknown = sorted(set(raw) - set(cls.__dataclass_fields__))
        if unknown:
            raise ConfigError(f"unknown config key(s): {', '.join(unknown)}")
        for key in ("data_dir", "media_dir"):
            if key in raw and not (isinstance(raw[key], str) and raw[key]):
                raise ConfigError(f"{key} must be a non-empty string")
        if "allow_send" in raw and not isinstance(raw["allow_send"], bool):
            raise ConfigError("allow_send must be a boolean")
        size = raw.get("max_media_bytes", 1)
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ConfigError("max_media_bytes must be a positive integer")
        recipients = raw.get("allowed_recipients", [])
        if not isinstance(recipients, list) or not all(isinstance(r, str) for r in recipients):
            raise ConfigError("allowed_recipients must be a list of strings")
        bad = [r for r in recipients if not valid_recipient(r)]
        if bad:
            raise ConfigError(f"allowed_recipients has invalid entries (need 6-15 digits or a JID): {', '.join(bad)}")
        # normalized so that the digits form and the JID form of a number compare equal
        return cls(**{**raw, "allowed_recipients": tuple(canonical(r) for r in recipients)})


def load_config(path: str | Path | None = None) -> WhatsAppConfig:
    config_path = Path(path or os.environ.get("WHATSAPP_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.is_file():
        raise ConfigError(f"config file not found at {config_path}")
    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file at {config_path} is not valid JSON: {e}") from e
    return WhatsAppConfig.from_dict(raw)
