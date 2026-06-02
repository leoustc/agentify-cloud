# Agentify Cloud Execution Plan

## Objective

Build a Python distribution package named `agentify-cloud` with a primary
`agentify` CLI that starts one local server on port `8000` by default. The
Python import package remains `agentify` because `agentify-cloud` is not a
valid Python module name. The server must expose:

- a FastAPI HTTP app that delegates arbitrary GET and POST endpoints to a local
  Pi Agent AgentSession backend
- a FastMCP server on the same port
- an embedded Pi Agent runtime vendored from the required npm package under
  `src/vendor/pi`, used by default through a local AgentSession bridge
- CLI commands for Pi login and server startup

Implementation should favor a small, testable scaffold over broad framework
customization.

## Expected Package Shape

Create a conventional Python package layout:

- `pyproject.toml`
  - package metadata for distribution `agentify-cloud`
  - runtime dependencies for FastAPI, Uvicorn, FastMCP, HTTP client, and CLI
  - primary console script entry point `agentify = "agentify.cli:main"` or
    equivalent
  - compatibility console script entry point `agentify-cloud = "agentify.cli:main"`
    for users who prefer a command matching the distribution name
  - pytest/test dependencies if the project uses optional dev extras
- `src/agentify/__init__.py`
- `src/agentify/cli.py`
- `src/agentify/server.py`
- `src/agentify/pi_client.py`
- `src/agentify/pi_runtime.py` or an equivalent isolated module for starting
  and addressing the embedded local Pi AgentSession bridge
- `src/agentify/auth.py`
- `src/vendor/pi/` containing the vendored Pi Agent npm package/runtime assets
  needed for local execution
- `tests/`

Use additional files only where they reduce complexity.

## CLI Behavior

Implement:

```sh
agentify login
agentify server --port 8000 -api_key abc123,abc1234 -api_key_file path-to-key-list-file
```

Requirements:

- `agentify login` should run or stub the Pi Agent login selection routine in a
  clear extension point. If no Pi SDK/API is available in the repo, provide a
  minimal interactive command that records the selected backend locally and
  keeps the Pi-specific integration isolated in `auth.py`.
- `agentify server` starts the combined FastAPI/FastMCP service.
- `agentify-cloud` remains available as a distribution-name console-script alias.
- `--port` defaults to `8000`.
- `-api_key` accepts a comma-separated list.
- `-api_key_file` reads one API key per non-empty line.
- If API keys are configured, require incoming HTTP requests to provide a valid
  key through `Authorization: Bearer <key>` or `x-api-key: <key>`.
- Keep API-key parsing separately testable.

## Pi AgentSession Client

Implement a small client abstraction in `pi_client.py`:

- accepts a prompt dictionary
- sends it as JSON by POST to the local Pi AgentSession endpoint
- returns parsed JSON
- raises a typed error for transport failure, non-JSON responses, or JSON that
  does not match the required envelope

Configuration:

- normal local runs must not require `AGENTIFY_PI_URL`
- by default, start or reuse the embedded Pi Agent runtime vendored under
  `src/vendor/pi` and expose it through a local Pi AgentSession bridge
- `AGENTIFY_PI_URL` is only an advanced override for an external or already
  running Pi AgentSession endpoint; if present, use it instead of starting the
  embedded bridge
- startup should fail only when both the override is unusable and the embedded
  bridge cannot be started or addressed; error messages should name the missing
  vendored runtime or bridge startup failure, not ask ordinary users to set
  `AGENTIFY_PI_URL`
- keep process startup, port/path discovery, readiness checks, and cleanup for
  the embedded bridge isolated from HTTP prompt/response validation so it can be
  tested with fakes

Retry behavior:

- For delegated HTTP/MCP calls, validate only response format, not semantic
  content.
- On invalid format or transport failure, retry by sending the original prompt
  plus failure information to the Pi AgentSession.
- Keep retry count bounded, for example one retry after the initial attempt.
- If retry still fails, return an appropriate FastAPI error response with a
  concise diagnostic.

## FastAPI HTTP Behavior

Register catch-all routes for arbitrary paths. Preserve the endpoint path and
query string in the delegated prompt.

### POST

For any POST request, build:

```json
{
  "endpoint": "<url>",
  "instruction": null,
  "body": "string(post body content)",
  "format": "json"
}
```

Rules:

- `endpoint` should include path and query string.
- `body` is the raw request body decoded to text when possible, with a stable
  fallback for bytes that are not valid UTF-8.
- `instruction` is decoded from the JSON request body when present. Prefer an
  explicit `instruction` field if the body is a JSON object; otherwise use
  `null`.
- Send this prompt to Pi AgentSession.
- Require the Pi response to be JSON.
- Relay the returned JSON object/value to the HTTP caller without validating
  its semantic content.
- On failure, retry with failure information as described above.

### GET

For any GET request, build:

```json
{
  "endpoint": "<url>",
  "instruction": "this is a user GET query, you make a html file for this request with your understand from the endpoint string",
  "format": "html"
}
```

Rules:

- Send this prompt to Pi AgentSession.
- Require the Pi response to be JSON containing a string `content` field.
- Return `content` as `text/html`.
- On failure, retry with failure information as described above.

### Error Endpoints

FastAPI 404 and other error paths should follow the same delegated style as
normal requests where practical:

- unknown GET paths delegate with the GET prompt
- unknown POST paths delegate with the POST prompt
- framework/runtime failures should return normal error responses, but avoid
  creating custom behavior that bypasses the catch-all routes for user endpoints

## FastMCP Behavior

Run a FastMCP server on the same port as the FastAPI service, mounted under a
clear path such as `/mcp` if the library supports ASGI mounting.

Expose at least one generic tool that delegates tool calls to Pi AgentSession.
Use a stable name such as `agentify`.

For delegated MCP tool calls, generate:

```json
{
  "tool function": "user called tools",
  "instruciton": "<decoded tool payload instruction or null>",
  "body": "string(the tool call)",
  "format": "json"
}
```

Notes:

- Keep the misspelled key `instruciton` because `PROJECT.md` specifies it that
  way.
- Decode instruction from the tool payload if present; otherwise use `null`.
- Validate that the Pi response is JSON and return it to the MCP caller.
- Apply the same bounded retry behavior on invalid response format.

If the chosen FastMCP version cannot mount cleanly into FastAPI, document the
constraint in Backend's handoff and implement the closest supported same-port
ASGI integration.

## Tests And Verification

Backend should add focused tests for:

- default Pi AgentSession client/runtime configuration without `AGENTIFY_PI_URL`
- `AGENTIFY_PI_URL` override behavior when it is explicitly set
- embedded bridge startup/address resolution failure with an actionable error
- API-key parsing from CLI string and key file
- POST prompt construction, including raw body and decoded instruction
- GET prompt construction and HTML response extraction
- Pi retry behavior after invalid/non-JSON response
- HTTP API-key enforcement when keys are configured
- MCP prompt construction for the generic tool, if testable without a live MCP
  client

Run the relevant verification before handoff, preferably:

```sh
python -m pytest
python -m compileall src
```

If dependency installation is not available in the environment, Backend should
still run syntax checks that are possible and report exactly what could not be
verified.

## Backend Handoff Expectations

Backend should:

1. Read `AGENTS.md`, `PROJECT.md`, and this file before coding.
2. Fix the startup path so `uv run agentify server --port 8000` and
   `make run PORT=8000` do not fail just because `AGENTIFY_PI_URL` is unset.
3. Implement the embedded Pi runtime bridge behavior above, using `src/vendor/pi`
   as the default runtime location and `AGENTIFY_PI_URL` only as an override.
4. Keep Pi-specific code behind `pi_client.py`, `pi_runtime.py` or equivalent,
   and `auth.py` so server behavior can be tested with fakes.
5. Avoid unbounded retries or blocking startup indefinitely on Pi availability;
   use bounded readiness checks and clear errors for bridge startup failure.
6. After implementation, write a mailbox message to Review with:
   - files changed
   - behavior implemented
   - verification commands and results
   - known risks or unimplemented Pi/FastMCP integration limits
