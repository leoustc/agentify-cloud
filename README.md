# Agentify Cloud

Agentify Cloud turns a Pi agent into a universal FastAPI and MCP server. It
runs one Python service on port `8000` by default, exposes arbitrary HTTP
routes plus an MCP endpoint, and delegates each request to a local Pi
AgentSession.

The distribution package is named `agentify-cloud`. The Python import package
and primary CLI command are `agentify`.

## Design Philosophy

Agentify Cloud is a thin gateway, not an application framework. The server
accepts broad HTTP and MCP input shapes, translates them into clear prompt
contracts, and lets the Pi agent decide the content of the result.

The gateway validates transport and envelope shape only. For POST and MCP calls,
Pi must return JSON. For GET calls, Pi must return JSON containing an HTML
`content` string. Agentify Cloud does not validate semantic content because the
goal is to make the agent reachable through common protocols while keeping the
application logic inside the agent.

The user controls behavior through an `AGENTS.md` prompt gate. That file is the
front door for agent rules: allowed routes, response style, tool policy, domain
constraints, and any project-specific instructions the Pi agent should honor for
FastAPI and MCP requests.

Local use should work without external service setup beyond the packaged Pi
runtime. The embedded Pi AgentSession bridge is the default path, while
`AGENTIFY_PI_URL` remains an advanced override for users who already operate a
separate Pi backend.

Installed packages materialize the locked Pi npm runtime into a per-user cache
on first start. The cache is keyed by the packaged runtime files and guarded by
a per-runtime lock so concurrent first starts reuse one completed dependency
tree. Source checkouts with `src/vendor/pi/node_modules` already present use the
vendored runtime directly.

Release and runtime behavior should stay explicit: clear commands, fresh build
artifacts, bounded retries, clear errors, and no hidden publishing steps.

## Usage

Install from PyPI:

```sh
uv pip install agentify-cloud
```

Start the server:

```sh
agentify server --port 8000
```

The server listens on `0.0.0.0:8000` by default and exposes:

- HTTP GET and POST handling for any path
- an MCP server mounted at `/mcp`
- an embedded local Pi AgentSession bridge from `src/vendor/pi`
- first-run Pi npm dependency materialization for installed wheels
- an `AGENTS.md` prompt gate read at startup

`AGENTIFY_PI_URL` is optional. Set it only when you want to use an external or
already-running Pi AgentSession endpoint instead of the embedded runtime.

### AGENTS.md Prompt Gate

`agentify server` reads a markdown seed file once at startup and injects the
exact file content into every delegated prompt. The default file is `AGENTS.md`
in the current working directory:

```sh
agentify server --port 8000
```

Use `--md-file` to point at a different rule file:

```sh
agentify server --port 8000 --md-file ./runtime/AGENTS.md
```

The markdown content is added as `context_system_instruction` in the prompt
dictionaries sent to Pi for:

- FastAPI GET requests
- FastAPI POST requests
- MCP tool calls
- retry prompts after invalid Pi responses

Use this file to define the agent gate for the running server. For example:

```md
# Agent Gate

## Routes

- `/support/*`: answer as a support assistant and return concise JSON for POST.
- `/dashboard/*`: render complete HTML dashboards for GET.

## Tools

- MCP callers may request data lookup and transformation.
- Do not call external services unless the request explicitly allows it.

## Rules

- Never expose secrets or local environment variables.
- Prefer structured JSON for POST and MCP results.
- For GET results, return one complete HTML document in `content`.
```

`make run` starts the server from `runtime/` by default, so its default prompt
gate is `runtime/AGENTS.md`. The `runtime/` directory is ignored by git and is a
good place for local rules, routes, credentials-adjacent notes, and tool policy
that should not be committed.

### Login

Record a Pi backend selection:

```sh
agentify login --backend <backend-name-or-url>
```

Without `--backend`, the command prompts for a backend value:

```sh
agentify login
```

### HTTP GET

Send any GET request to the server:

```sh
curl http://127.0.0.1:8000/dashboard/today
```

Agentify Cloud builds a prompt from the endpoint and asks Pi to produce HTML.
The response is returned as `text/html`.

### HTTP POST

Send any POST request to any path:

```sh
curl -X POST http://127.0.0.1:8000/tasks/create \
  -H 'content-type: application/json' \
  -d '{"instruction":"create a task summary","title":"Ship README"}'
```

Agentify Cloud sends the endpoint, decoded `instruction` field when present, raw
body text, and requested `json` format to Pi. The JSON response from Pi is
relayed back to the caller.

### API Keys

Require callers to provide an API key:

```sh
agentify server --port 8000 -api_key abc123,def456
```

Or read one key per line from a file:

```sh
agentify server --port 8000 -api_key_file ./keys.txt
```

Clients may authenticate with either header:

```sh
curl http://127.0.0.1:8000/anything -H 'Authorization: Bearer abc123'
curl http://127.0.0.1:8000/anything -H 'x-api-key: abc123'
```

### MCP

Connect an MCP client to the server's `/mcp` endpoint. The server exposes a
generic `agentify` tool that forwards tool payloads to Pi and returns the JSON
result.
