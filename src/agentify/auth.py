"""Authentication and local Pi backend selection helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


CONFIG_DIR = Path.home() / ".agentify"
CONFIG_FILE = CONFIG_DIR / "config.json"


class ApiKeyError(ValueError):
    """Raised when configured API keys cannot be loaded."""


def parse_api_keys(api_key: str | None = None, api_key_file: str | Path | None = None) -> set[str]:
    """Parse API keys from a comma-separated string and a line-oriented file."""

    keys: set[str] = set()
    keys.update(_split_comma_keys(api_key))

    if api_key_file:
        path = Path(api_key_file).expanduser()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ApiKeyError(f"Could not read API key file {path}: {exc}") from exc
        keys.update(_clean_lines(lines))

    return keys


def _split_comma_keys(api_key: str | None) -> Iterable[str]:
    if not api_key:
        return []
    return [part.strip() for part in api_key.split(",") if part.strip()]


def _clean_lines(lines: Iterable[str]) -> Iterable[str]:
    return [line.strip() for line in lines if line.strip()]


def is_authorized(headers: dict[str, str], configured_keys: set[str]) -> bool:
    """Return True when no keys are configured or the request presents a valid key."""

    if not configured_keys:
        return True

    lowered = {key.lower(): value for key, value in headers.items()}
    api_key = lowered.get("x-api-key")
    if api_key and api_key in configured_keys:
        return True

    authorization = lowered.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and token in configured_keys


def save_backend_selection(backend: str) -> Path:
    """Persist the selected Pi backend name for later Pi-specific integrations."""

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"backend": backend}, indent=2) + "\n", encoding="utf-8")
    return CONFIG_FILE

