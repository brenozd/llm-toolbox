from __future__ import annotations

from actual import Actual

from .config import ActualConfig


def open_actual(config: ActualConfig) -> Actual:
    return Actual(
        base_url=config.server_url,
        password=config.password,
        file=config.file,
        encryption_password=config.encryption_password,
        data_dir=config.data_dir,
        cert=config.cert,
    )
