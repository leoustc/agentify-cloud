"""Client abstraction for the local Pi AgentSession POST endpoint."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .pi_runtime import EmbeddedPiRuntime, PiRuntimeError, start_embedded_pi_runtime


class PiClientError(RuntimeError):
    """Raised when Pi AgentSession cannot produce a usable JSON response."""


def pi_url_from_env() -> str:
    url = os.environ.get("AGENTIFY_PI_URL", "").strip()
    if not url:
        raise PiClientError("AGENTIFY_PI_URL is not set.")
    return url


def resolve_pi_url() -> tuple[str, EmbeddedPiRuntime | None]:
    """Return the external override URL or start the embedded local runtime."""

    override_url = os.environ.get("AGENTIFY_PI_URL", "").strip()
    if override_url:
        return override_url, None
    try:
        runtime = start_embedded_pi_runtime()
    except PiRuntimeError as exc:
        raise PiClientError(
            "Could not start the embedded Pi AgentSession bridge from src/vendor/pi. "
            f"{exc}"
        ) from exc
    return runtime.url, runtime


class PiAgentSessionClient:
    """Small async client for posting prompt dictionaries to Pi AgentSession."""

    def __init__(self, url: str | None = None, timeout: float = 60.0) -> None:
        self.runtime: EmbeddedPiRuntime | None = None
        if url is None:
            self.url, self.runtime = resolve_pi_url()
        else:
            self.url = url
        self.timeout = timeout

    async def post_prompt(self, prompt: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=prompt)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PiClientError(f"Pi AgentSession request failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise PiClientError("Pi AgentSession returned non-JSON content.") from exc

    async def aclose(self) -> None:
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None
