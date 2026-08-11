from __future__ import annotations

import httpx

from .config import WoodpeckerConfig


class WoodpeckerClient:
    def __init__(self, config: WoodpeckerConfig) -> None:
        self._http = httpx.Client(
            base_url=f"{config.base_url}/api",
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=30.0,
        )

    def get(self, path: str, params: dict | None = None) -> object:
        resp = self._http.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def post(self, path: str, json_body: dict | None = None) -> object:
        resp = self._http.post(path, json=json_body or {})
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def close(self) -> None:
        self._http.close()


def open_woodpecker(config: WoodpeckerConfig) -> WoodpeckerClient:
    return WoodpeckerClient(config)
