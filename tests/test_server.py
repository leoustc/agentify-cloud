import builtins
import sys
import types
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from agentify.server import build_mcp_prompt, create_app


class FakePiClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def post_prompt(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_post_prompt_construction_and_json_relay() -> None:
    seed = "# Agent seed\n\nUse project rules."
    fake = FakePiClient([{"ok": True}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction=seed)
    client = TestClient(app)

    response = client.post("/v1/do?x=1", json={"instruction": "run", "value": 3})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake.prompts == [
        {
            "endpoint": "/v1/do?x=1",
            "instruction": "run",
            "body": '{"instruction":"run","value":3}',
            "format": "json",
            "context_system_instruction": seed,
        }
    ]


def test_empty_context_system_instruction_is_preserved_in_post_prompt() -> None:
    fake = FakePiClient([{"ok": True}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction="")
    client = TestClient(app)

    response = client.post("/v1/empty", json={"instruction": "run"})

    assert response.status_code == 200
    assert fake.prompts[0]["context_system_instruction"] == ""


def test_get_prompt_construction_and_html_extraction() -> None:
    seed = "# Agent seed\n\nRender carefully."
    fake = FakePiClient([{"content": "<html>ok</html>"}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction=seed)
    client = TestClient(app)

    response = client.get("/docs/page?topic=x")

    assert response.status_code == 200
    assert response.text == "<html>ok</html>"
    assert response.headers["content-type"].startswith("text/html")
    assert fake.prompts[0]["endpoint"] == "/docs/page?topic=x"
    assert fake.prompts[0]["format"] == "html"
    assert fake.prompts[0]["context_system_instruction"] == seed


def test_empty_context_system_instruction_is_preserved_in_get_prompt() -> None:
    fake = FakePiClient([{"content": "<html>ok</html>"}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction="")
    client = TestClient(app)

    response = client.get("/empty-seed")

    assert response.status_code == 200
    assert fake.prompts[0]["context_system_instruction"] == ""


def test_retry_after_invalid_html_response() -> None:
    seed = "# Agent seed\n\nRetry with same context."
    fake = FakePiClient([{"bad": True}, {"content": "<html>fixed</html>"}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction=seed)
    client = TestClient(app)

    response = client.get("/needs-html")

    assert response.status_code == 200
    assert response.text == "<html>fixed</html>"
    assert len(fake.prompts) == 2
    assert fake.prompts[1]["failure"]["attempt"] == 1
    assert fake.prompts[1]["context_system_instruction"] == seed


def test_empty_context_system_instruction_is_preserved_in_retry_prompt() -> None:
    fake = FakePiClient([{"bad": True}, {"content": "<html>fixed</html>"}])
    app = create_app(pi_client=fake, include_mcp=False, context_system_instruction="")
    client = TestClient(app)

    response = client.get("/empty-seed-retry")

    assert response.status_code == 200
    assert len(fake.prompts) == 2
    assert fake.prompts[1]["failure"]["attempt"] == 1
    assert fake.prompts[1]["context_system_instruction"] == ""


def test_api_key_enforcement() -> None:
    fake = FakePiClient([{"ok": True}])
    app = create_app(api_keys={"secret"}, pi_client=fake, include_mcp=False)
    client = TestClient(app)

    missing = client.post("/secure", json={})
    allowed = client.post("/secure", json={}, headers={"authorization": "Bearer secret"})

    assert missing.status_code == 401
    assert allowed.status_code == 200


def test_mcp_prompt_construction() -> None:
    assert build_mcp_prompt({"instruction": "do work", "x": 1}) == {
        "tool function": "user called tools",
        "instruciton": "do work",
        "body": '{"instruction": "do work", "x": 1}',
        "format": "json",
    }


def test_mcp_prompt_includes_context_system_instruction() -> None:
    assert build_mcp_prompt({"instruction": "do work"}, "# Agent seed") == {
        "tool function": "user called tools",
        "instruciton": "do work",
        "body": '{"instruction": "do work"}',
        "format": "json",
        "context_system_instruction": "# Agent seed",
    }


def test_mcp_prompt_preserves_empty_context_system_instruction() -> None:
    assert build_mcp_prompt({"instruction": "do work"}, "") == {
        "tool function": "user called tools",
        "instruciton": "do work",
        "body": '{"instruction": "do work"}',
        "format": "json",
        "context_system_instruction": "",
    }


def test_fastmcp_mount_uses_parent_lifespan_and_internal_root_path(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_lifespan(app):
        yield

    class FakeMCPApp:
        def __init__(self, path):
            self.path = path
            self.lifespan = fake_lifespan

    class FakeFastMCP:
        instances = []

        def __init__(self, name):
            self.name = name
            self.tools = []
            self.http_paths = []
            self.instances.append(self)

        def tool(self, func):
            self.tools.append(func)
            return func

        def http_app(self, path=None):
            self.http_paths.append(path)
            return FakeMCPApp(path)

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(FastMCP=FakeFastMCP))

    app = create_app(pi_client=FakePiClient([]), include_mcp=True)

    mounted_routes = [route for route in app.routes if getattr(route, "path", None) == "/mcp"]
    assert app.state.fastmcp_available is True
    assert app.state.fastmcp_app.path == "/"
    assert app.router.lifespan_context is not None
    assert len(mounted_routes) == 1
    assert mounted_routes[0].app is app.state.fastmcp_app
    assert FakeFastMCP.instances[0].http_paths == ["/"]


def test_create_app_remains_usable_when_fastmcp_is_unavailable(monkeypatch) -> None:
    real_import = builtins.__import__

    def raise_for_fastmcp(name, *args, **kwargs):
        if name == "fastmcp":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", raise_for_fastmcp)
    fake = FakePiClient([{"ok": True}])

    app = create_app(pi_client=fake, include_mcp=True)
    client = TestClient(app)
    response = client.post("/v1/do", json={})

    assert app.state.fastmcp_available is False
    assert app.state.fastmcp_error == "fastmcp is not installed"
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_failed_retry_returns_502() -> None:
    fake = FakePiClient([{"bad": True}, {"still": "bad"}])
    app = create_app(pi_client=fake, include_mcp=False)
    client = TestClient(app)

    response = client.get("/never-html")

    assert response.status_code == 502
    assert "Pi AgentSession delegation failed" in response.json()["detail"]
