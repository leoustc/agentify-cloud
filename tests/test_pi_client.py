import asyncio
from dataclasses import dataclass

import pytest

from agentify import pi_client
from agentify.pi_client import PiAgentSessionClient, PiClientError
from agentify.pi_runtime import PiRuntimeError


@dataclass
class FakeRuntime:
    url: str = "http://127.0.0.1:12345"
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def test_default_client_starts_embedded_runtime_when_override_is_unset(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.delenv("AGENTIFY_PI_URL", raising=False)
    monkeypatch.setattr(pi_client, "start_embedded_pi_runtime", lambda: runtime)

    client = PiAgentSessionClient()

    assert client.url == "http://127.0.0.1:12345"
    assert client.runtime is runtime


def test_pi_url_override_skips_embedded_runtime(monkeypatch) -> None:
    def fail_start():
        raise AssertionError("embedded runtime should not start when override is set")

    monkeypatch.setenv("AGENTIFY_PI_URL", "http://external.example/session")
    monkeypatch.setattr(pi_client, "start_embedded_pi_runtime", fail_start)

    client = PiAgentSessionClient()

    assert client.url == "http://external.example/session"
    assert client.runtime is None


def test_default_runtime_failure_is_actionable(monkeypatch) -> None:
    monkeypatch.delenv("AGENTIFY_PI_URL", raising=False)

    def fail_start():
        raise PiRuntimeError("Embedded Pi AgentSession bridge is missing at src/vendor/pi/agentify-bridge.mjs.")

    monkeypatch.setattr(pi_client, "start_embedded_pi_runtime", fail_start)

    with pytest.raises(PiClientError, match="embedded Pi AgentSession bridge from src/vendor/pi") as exc:
        PiAgentSessionClient()

    assert "AGENTIFY_PI_URL" not in str(exc.value)


def test_client_aclose_stops_owned_runtime(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.delenv("AGENTIFY_PI_URL", raising=False)
    monkeypatch.setattr(pi_client, "start_embedded_pi_runtime", lambda: runtime)

    client = PiAgentSessionClient()
    asyncio.run(client.aclose())

    assert runtime.closed is True
    assert client.runtime is None
