import http from "node:http";
import {
  AuthStorage,
  createAgentSession,
  ModelRegistry,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const host = process.env.AGENTIFY_PI_BRIDGE_HOST || "127.0.0.1";
const port = Number.parseInt(process.env.AGENTIFY_PI_BRIDGE_PORT || "0", 10);
const cwd = process.env.AGENTIFY_PI_CWD || process.cwd();
const agentDir = process.env.AGENTIFY_PI_AGENT_DIR;

const session = await createPiAgentSession();

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

async function createPiAgentSession() {
  const authStorage = AuthStorage.create();
  const modelRegistry = ModelRegistry.create(authStorage);
  const settingsManager = SettingsManager.create(cwd, agentDir);
  settingsManager.applyOverrides({
    compaction: { enabled: false },
  });

  const result = await createAgentSession({
    cwd,
    ...(agentDir ? { agentDir } : {}),
    authStorage,
    modelRegistry,
    settingsManager,
    sessionManager: SessionManager.inMemory(cwd),
  });
  return result.session;
}

async function runPrompt(prompt) {
  const promptText = [
    "You are the Pi AgentSession backend for Agentify.",
    "Read the JSON prompt below and return only a valid JSON response.",
    "For prompts with format \"html\", return a JSON object with a string content field containing a complete HTML document.",
    "For prompts with format \"json\", return any valid JSON value that satisfies the user request.",
    JSON.stringify(prompt),
  ].join("\n\n");

  const deltas = [];
  const unsubscribe = session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      deltas.push(event.assistantMessageEvent.delta);
    }
  });
  try {
    await session.prompt(promptText);
  } finally {
    unsubscribe();
  }

  const text = extractLatestAssistantText() || deltas.join("");
  if (!text.trim()) {
    throw new Error("Pi AgentSession produced an empty response");
  }
  return parseJsonFromText(text);
}

function extractLatestAssistantText() {
  for (let index = session.messages.length - 1; index >= 0; index -= 1) {
    const message = session.messages[index];
    if (!message || message.role !== "assistant" || !Array.isArray(message.content)) {
      continue;
    }
    return message.content
      .filter((part) => part && part.type === "text" && typeof part.text === "string")
      .map((part) => part.text)
      .join("");
  }
  return "";
}

function parseJsonFromText(text) {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (match) {
      return JSON.parse(match[1].trim());
    }
    const start = firstJsonStart(trimmed);
    const end = Math.max(trimmed.lastIndexOf("}"), trimmed.lastIndexOf("]"));
    if (start >= 0 && end > start) {
      return JSON.parse(trimmed.slice(start, end + 1));
    }
    throw new Error("Pi AgentSession response was not valid JSON");
  }
}

function firstJsonStart(value) {
  const objectStart = value.indexOf("{");
  const arrayStart = value.indexOf("[");
  if (objectStart === -1) {
    return arrayStart;
  }
  if (arrayStart === -1) {
    return objectStart;
  }
  return Math.min(objectStart, arrayStart);
}

const server = http.createServer(async (request, response) => {
  if (request.method !== "POST") {
    response.writeHead(405, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: "POST required" }));
    return;
  }

  try {
    const body = await readBody(request);
    const prompt = body ? JSON.parse(body) : null;
    const result = await runPrompt(prompt);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(result));
  } catch (error) {
    response.writeHead(502, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: String(error && error.message ? error.message : error) }));
  }
});

server.listen(port, host, () => {
  const address = server.address();
  const actualPort = typeof address === "object" && address ? address.port : port;
  process.stdout.write(JSON.stringify({ type: "ready", url: `http://${host}:${actualPort}` }) + "\n");
});

function shutdown() {
  session.dispose();
  server.close(() => process.exit(0));
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
