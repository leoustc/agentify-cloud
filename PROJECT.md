# PROJECT Agentify

this project is to use pi agent as the fastapi and fastmcp server backend. you have a python server running on port 8000 (default).

in this port, you have a fastapi server and a mcp server.

# Architecture

- python server, fastapi and mcp at port 8000
- embedded Pi Agent runtime provided by an npm package, vendored under `src/vendor/pi`
- internal Pi AgentSession bridge runs locally and accepts POST JSON messages, returning JSON messages
- the Python server should start/use this embedded local Pi AgentSession bridge by default, instead of requiring the user to set `AGENTIFY_PI_URL` for normal local runs
- `AGENTIFY_PI_URL` may remain as an override for advanced/external Pi AgentSession endpoints

# CLI
- a uv pip package with cli:
    1. agentify login:
        pi agent login routine, as the customer to choose pi agent backend
    2. agentify server [--port 8000] [-api_key abc123,abc1234] [-api_key_file path-to-key-list-file]
    start the server

# HTTP behavior

- when a request (GET or POST) to the fastapi server with any <url>, you will make make a prompt with json
prompt json format with POST:
{ "endpoint": <url>,
  "instruction": <null or decode from the post json body>,
  "body": string(post body content),
  "format": "json"
}
send this json format to the pi agentsession server with POST, the return should be json as well. you rely the json return from the pi agentsession to the user. only check the json format, no need to check the content. if failed, ask the pi agent to do it again with the failure informaiton.


prompt json format with GET:
{ "endpoint": <url>,
  "instruction": "this is a user GET query, you make a html file for this request with your understand from the endpoint string",
  "format": "html"
}
send this jso fomrat to the pi agent session server with POST, the return should be a json file contains html content. like
{ "content": "string of html file" }
you decode the html content from this json file and return to the user, if there is a failure, re send the message to the pi agent again.

- all error endpoing, will follow the same style as above


# MCP behavior

- all MCP tool calls error with generate a json format as:
{ "tool function": "user called tools",
   "instruciton": "decode from the tool payload if there, default null",
   "body": "string(the tool call)",
   "format": "json"
}

