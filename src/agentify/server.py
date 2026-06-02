"""FastAPI/FastMCP server that delegates user work to Pi AgentSession."""

from __future__ import annotations

import argparse
import base64
import json
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import is_authorized
from .pi_client import PiAgentSessionClient


GET_HTML_INSTRUCTION = (
    "this is a user GET query, you make a html file for this request with your "
    "understand from the endpoint string"
)

Validator = Callable[[Any], Any]
Lifespan = Callable[[FastAPI], Any]


@dataclass(frozen=True)
class FastMCPMount:
    mcp: Any
    app: Any


def create_app(
    *,
    api_keys: set[str] | None = None,
    pi_client: Any | None = None,
    include_mcp: bool = True,
    context_system_instruction: str | None = None,
) -> FastAPI:
    configured_keys = api_keys or set()
    client = pi_client or PiAgentSessionClient()
    mcp_mount: FastMCPMount | None = None
    mcp_error: str | None = None

    if include_mcp:
        mcp_mount, mcp_error = build_fastmcp_mount(client, context_system_instruction)

    client_lifespan = build_client_lifespan(client)
    mcp_lifespan = getattr(mcp_mount.app, "lifespan", None) if mcp_mount else None
    app = FastAPI(title="Agentify", lifespan=combine_lifespans(client_lifespan, mcp_lifespan))
    app.state.context_system_instruction = context_system_instruction

    if include_mcp:
        if mcp_mount:
            app.mount("/mcp", mcp_mount.app)
            app.state.fastmcp_available = True
            app.state.fastmcp = mcp_mount.mcp
            app.state.fastmcp_app = mcp_mount.app
        else:
            app.state.fastmcp_available = False
            app.state.fastmcp_error = mcp_error or "fastmcp is not installed"

    async def require_api_key(request: Request) -> None:
        if not is_authorized(dict(request.headers), configured_keys):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key.",
            )

    @app.get("/{path:path}", response_class=HTMLResponse, dependencies=[Depends(require_api_key)])
    async def delegate_get(path: str, request: Request) -> HTMLResponse:
        prompt = build_get_prompt(request, context_system_instruction)
        result = await delegate_with_retry(client, prompt, validate_html_response)
        return HTMLResponse(content=result, status_code=status.HTTP_200_OK)

    @app.post("/{path:path}", dependencies=[Depends(require_api_key)])
    async def delegate_post(path: str, request: Request) -> JSONResponse:
        prompt = await build_post_prompt(request, context_system_instruction)
        result = await delegate_with_retry(client, prompt, validate_json_response)
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)

    return app


def build_fastmcp_mount(
    client: Any,
    context_system_instruction: str | None = None,
) -> tuple[FastMCPMount | None, str | None]:
    """Build the FastMCP ASGI app before the parent FastAPI app is created."""

    try:
        from fastmcp import FastMCP
    except ImportError:
        return None, "fastmcp is not installed"

    mcp = FastMCP("agentify")

    @mcp.tool
    async def agentify(payload: Any = None) -> Any:
        return await delegate_mcp_tool(client, payload, context_system_instruction)

    return FastMCPMount(mcp=mcp, app=mcp.http_app(path="/")), None


def combine_lifespans(*lifespans: Lifespan | None) -> Lifespan | None:
    active_lifespans = [lifespan for lifespan in lifespans if lifespan is not None]
    if not active_lifespans:
        return None
    if len(active_lifespans) == 1:
        return active_lifespans[0]

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            for lifespan in active_lifespans:
                await stack.enter_async_context(lifespan(app))
            yield

    return combined_lifespan


def build_client_lifespan(client: Any) -> Lifespan | None:
    close = getattr(client, "aclose", None)
    if close is None:
        return None

    @asynccontextmanager
    async def client_lifespan(app: FastAPI):
        try:
            yield
        finally:
            await close()

    return client_lifespan


def endpoint_from_request(request: Request) -> str:
    endpoint = request.url.path
    if request.url.query:
        endpoint = f"{endpoint}?{request.url.query}"
    return endpoint


async def build_post_prompt(request: Request, context_system_instruction: str | None = None) -> dict[str, Any]:
    raw_body = await request.body()
    body = decode_body(raw_body)
    instruction = decode_instruction(raw_body)
    return with_context_system_instruction({
        "endpoint": endpoint_from_request(request),
        "instruction": instruction,
        "body": body,
        "format": "json",
    }, context_system_instruction)


def build_get_prompt(request: Request, context_system_instruction: str | None = None) -> dict[str, Any]:
    return with_context_system_instruction({
        "endpoint": endpoint_from_request(request),
        "instruction": GET_HTML_INSTRUCTION,
        "format": "html",
    }, context_system_instruction)


def with_context_system_instruction(
    prompt: dict[str, Any],
    context_system_instruction: str | None,
) -> dict[str, Any]:
    if context_system_instruction is not None:
        prompt["context_system_instruction"] = context_system_instruction
    return prompt


def decode_body(raw_body: bytes) -> str:
    try:
        return raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return "base64:" + base64.b64encode(raw_body).decode("ascii")


def decode_instruction(raw_body: bytes) -> Any | None:
    if not raw_body:
        return None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload.get("instruction")
    return None


def validate_json_response(response: Any) -> Any:
    return response


def validate_html_response(response: Any) -> str:
    if isinstance(response, dict) and isinstance(response.get("content"), str):
        return response["content"]
    raise ValueError("Pi response must be a JSON object with a string content field.")


async def delegate_with_retry(
    client: Any,
    prompt: dict[str, Any],
    validator: Validator,
    *,
    retries: int = 1,
) -> Any:
    current_prompt = prompt
    failures: list[str] = []

    for attempt in range(retries + 1):
        try:
            response = await client.post_prompt(current_prompt)
            return validator(response)
        except Exception as exc:
            failures.append(str(exc))
            if attempt >= retries:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Pi AgentSession delegation failed: {exc}",
                ) from exc
            current_prompt = with_failure_information(prompt, failures, attempt + 1)

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Pi AgentSession delegation failed.")


def with_failure_information(prompt: dict[str, Any], failures: list[str], attempt: int) -> dict[str, Any]:
    retry_prompt = dict(prompt)
    retry_prompt["failure"] = {
        "attempt": attempt,
        "message": failures[-1],
        "history": list(failures),
        "instruction": "Previous Pi AgentSession response was invalid. Regenerate a response in the requested format.",
    }
    return retry_prompt


def build_mcp_prompt(payload: Any = None, context_system_instruction: str | None = None) -> dict[str, Any]:
    instruction = payload.get("instruction") if isinstance(payload, dict) else None
    return with_context_system_instruction({
        "tool function": "user called tools",
        "instruciton": instruction,
        "body": stringify_tool_payload(payload),
        "format": "json",
    }, context_system_instruction)


def stringify_tool_payload(payload: Any = None) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(payload)


async def delegate_mcp_tool(client: Any, payload: Any = None, context_system_instruction: str | None = None) -> Any:
    prompt = build_mcp_prompt(payload, context_system_instruction)
    return await delegate_with_retry(client, prompt, validate_json_response)


def run_server(port: int, api_keys: set[str], context_system_instruction: str | None) -> None:
    import uvicorn

    app = create_app(api_keys=api_keys, context_system_instruction=context_system_instruction)
    uvicorn.run(app, host="0.0.0.0", port=port)


def positive_port(value: str) -> int:
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port
