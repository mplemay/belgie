import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile, mkdtemp } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import express from "express";

import { generateToolTypes } from "../src/codegen.ts";

const SCHEMA_TOOLS = [
  {
    description: "Build a model.\nThis closes */ safely.",
    inputSchema: {
      $defs: {
        Node: {
          properties: {
            name: { type: "string" },
            next: { anyOf: [{ $ref: "#/$defs/Node" }, { type: "null" }] },
          },
          required: ["name"],
          type: "object",
        },
      },
      properties: {
        choices: { items: { enum: ["a", "b"] }, type: "array" },
        labels: { additionalProperties: { type: "string" }, type: "object" },
        metrics: {
          additionalProperties: { type: "number" },
          properties: { name: { type: "string" } },
          required: ["name"],
          type: "object",
        },
        node: { $ref: "#/$defs/Node" },
        pair: {
          items: false,
          prefixItems: [{ type: "string" }, { type: "integer" }],
          type: "array",
        },
        value: { oneOf: [{ const: "auto" }, { type: ["number", "null"] }] },
      },
      required: ["node", "pair"],
      type: "object",
    },
    name: "model-tool",
    outputSchema: {
      properties: {
        payload: {
          allOf: [
            {
              type: "object",
              properties: { id: { type: "string" } },
              required: ["id"],
            },
            {
              type: "object",
              properties: { active: { type: "boolean" } },
              required: ["active"],
            },
          ],
        },
      },
      required: ["payload"],
      type: "object",
    },
  },
  {
    inputSchema: {
      properties: { limit: { minimum: 1, type: "integer" } },
      type: "object",
    },
    name: "model_tool",
    outputSchema: {
      properties: { count: { type: "integer" } },
      required: ["count"],
      type: "object",
    },
  },
];

const TEXT_CONTENT_TOOL = {
  description: "Get the current server time in ISO 8601 format.",
  inputSchema: {
    properties: {},
    title: "get_timeArguments",
    type: "object",
  },
  name: "get-time",
  outputSchema: {
    $defs: {
      Annotations: {
        description: "Optional annotations the client can use to inform how objects are used or displayed.",
        properties: {
          audience: {
            anyOf: [
              {
                items: { enum: ["user", "assistant"], type: "string" },
                type: "array",
              },
              { type: "null" },
            ],
            default: null,
            title: "Audience",
          },
          lastModified: {
            anyOf: [{ type: "string" }, { type: "null" }],
            default: null,
            title: "Lastmodified",
          },
          priority: {
            anyOf: [{ maximum: 1, minimum: 0, type: "number" }, { type: "null" }],
            default: null,
            title: "Priority",
          },
        },
        title: "Annotations",
        type: "object",
      },
      TextContent: {
        description: "Text provided to or from an LLM.",
        properties: {
          _meta: {
            anyOf: [{ additionalProperties: true, type: "object" }, { type: "null" }],
            default: null,
            title: "Meta",
          },
          annotations: {
            anyOf: [{ $ref: "#/$defs/Annotations" }, { type: "null" }],
            default: null,
          },
          text: { title: "Text", type: "string" },
          type: {
            const: "text",
            default: "text",
            title: "Type",
            type: "string",
          },
        },
        required: ["text"],
        title: "TextContent",
        type: "object",
      },
    },
    properties: {
      result: {
        items: { $ref: "#/$defs/TextContent" },
        title: "Result",
        type: "array",
      },
    },
    required: ["result"],
    title: "get_timeOutput",
    type: "object",
  },
};

const PYTHON_MCP_V2_TOOLS = JSON.parse(
  await readFile(new URL("fixtures/python-mcp-v2-tools.json", import.meta.url), "utf8"),
);

async function startMcpServer(listTools, onRequest = () => {}) {
  const app = createMcpExpressApp({ host: "127.0.0.1" });
  app.post("/mcp", async (request, response) => {
    onRequest(request);
    const server = new Server({ name: "belgie-codegen-test", version: "1.0.0" }, { capabilities: { tools: {} } });
    server.setRequestHandler(ListToolsRequestSchema, listTools);
    const transport = new StreamableHTTPServerTransport({
      enableJsonResponse: true,
      sessionIdGenerator: undefined,
    });
    response.on("close", () => {
      void transport.close();
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(request, response, request.body);
  });
  const http = await new Promise((resolve, reject) => {
    const server = app.listen(0, "127.0.0.1", () => {
      resolve(server);
    });
    server.once("error", reject);
  });
  const address = http.address();
  assert.ok(address && typeof address !== "string");
  return {
    close: async () =>
      new Promise((resolve, reject) =>
        http.close((error) => {
          error ? reject(error) : resolve();
        }),
      ),
    url: `http://127.0.0.1:${address.port}/mcp`,
  };
}

async function startOAuthMcpServer() {
  const app = createMcpExpressApp({ host: "127.0.0.1" });
  app.use(express.urlencoded({ extended: false }));
  let origin = "";
  let registration;
  let authorization;
  let registrationCount = 0;
  let tokenCount = 0;
  let authenticatedRequests = 0;

  app.get("/.well-known/oauth-protected-resource", (_request, response) => {
    response.json({
      authorization_servers: [origin],
      resource: `${origin}/mcp`,
      scopes_supported: ["tools:read"],
    });
  });
  app.get("/.well-known/oauth-protected-resource/mcp", (_request, response) => {
    response.status(404).end();
  });
  app.get("/.well-known/oauth-authorization-server", (_request, response) => {
    response.json({
      authorization_endpoint: `${origin}/authorize`,
      code_challenge_methods_supported: ["S256"],
      grant_types_supported: ["authorization_code", "refresh_token"],
      issuer: origin,
      registration_endpoint: `${origin}/register`,
      response_types_supported: ["code"],
      scopes_supported: ["tools:read"],
      token_endpoint: `${origin}/token`,
      token_endpoint_auth_methods_supported: ["none"],
    });
  });
  app.post("/register", (request, response) => {
    registrationCount += 1;
    registration = request.body;
    assert.equal(registration.client_name, "Belgie MCP Tool Codegen");
    assert.match(registration.redirect_uris[0], /^http:\/\/127\.0\.0\.1:\d+\/callback$/u);
    response.status(201).json({ ...registration, client_id: "belgie-test-client" });
  });
  app.get("/authorize", async (request, response) => {
    assert.equal(request.query.client_id, "belgie-test-client");
    assert.equal(request.query.response_type, "code");
    assert.equal(request.query.code_challenge_method, "S256");
    assert.equal(request.query.scope, "tools:read");
    assert.equal(typeof request.query.state, "string");
    assert.ok(request.query.state.length >= 32);
    assert.equal(request.query.redirect_uri, registration.redirect_uris[0]);
    authorization = request.query;

    const invalidCallback = new URL(request.query.redirect_uri);
    invalidCallback.searchParams.set("code", "wrong-state-code");
    invalidCallback.searchParams.set("state", "invalid-state");
    const invalidResponse = await fetch(invalidCallback);
    assert.equal(invalidResponse.status, 400);

    const callback = new URL(request.query.redirect_uri);
    callback.searchParams.set("code", "authorization-code");
    callback.searchParams.set("state", request.query.state);
    response.redirect(302, callback.toString());
  });
  app.post("/token", (request, response) => {
    tokenCount += 1;
    assert.equal(request.body.grant_type, "authorization_code");
    assert.equal(request.body.code, "authorization-code");
    assert.equal(request.body.client_id, "belgie-test-client");
    assert.equal(request.body.redirect_uri, registration.redirect_uris[0]);
    const challenge = createHash("sha256").update(request.body.code_verifier).digest("base64url");
    assert.equal(challenge, authorization.code_challenge);
    response.json({ access_token: "belgie-test-token", token_type: "Bearer" });
  });

  app.post("/mcp", async (request, response) => {
    if (request.headers.authorization !== "Bearer belgie-test-token") {
      response
        .status(401)
        .set(
          "www-authenticate",
          `Bearer resource_metadata="${origin}/.well-known/oauth-protected-resource", scope="tools:read"`,
        )
        .json({ error: "unauthorized" });
      return;
    }
    authenticatedRequests += 1;
    const server = new Server({ name: "belgie-oauth-test", version: "1.0.0" }, { capabilities: { tools: {} } });
    server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [SCHEMA_TOOLS[1]],
    }));
    const transport = new StreamableHTTPServerTransport({
      enableJsonResponse: true,
      sessionIdGenerator: undefined,
    });
    response.on("close", () => {
      void transport.close();
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(request, response, request.body);
  });
  app.get("/mcp", (request, response) => {
    if (request.headers.authorization !== "Bearer belgie-test-token") {
      response.status(401).end();
      return;
    }
    response.status(405).end();
  });

  const http = await new Promise((resolve, reject) => {
    const server = app.listen(0, "127.0.0.1", () => {
      resolve(server);
    });
    server.once("error", reject);
  });
  const address = http.address();
  assert.ok(address && typeof address !== "string");
  origin = `http://127.0.0.1:${address.port}`;
  return {
    close: async () =>
      new Promise((resolve, reject) =>
        http.close((error) => {
          error ? reject(error) : resolve();
        }),
      ),
    metrics: () => ({ registrationCount, tokenCount, authenticatedRequests }),
    url: `${origin}/mcp`,
  };
}

async function runCli(args, environment = {}, onStderr = () => {}) {
  const child = spawn(process.execPath, [join(process.cwd(), "dist/cli.js"), ...args], {
    cwd: process.cwd(),
    env: { ...process.env, ...environment },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => (stdout += chunk));
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
    onStderr(chunk);
  });
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", resolve);
  });
  return { code, stderr, stdout };
}

test("generates deterministic types from every tools/list page", async () => {
  let pages = 0;
  const server = await startMcpServer(async (request) => {
    pages += 1;
    if (request.params?.cursor === undefined) {
      return { nextCursor: "second", tools: [SCHEMA_TOOLS[1]] };
    }
    assert.equal(request.params.cursor, "second");
    return { tools: [SCHEMA_TOOLS[0]] };
  });
  try {
    const first = await generateToolTypes({ oauth: false, url: server.url });
    const second = await generateToolTypes({ oauth: false, url: server.url });
    assert.equal(first, second);
    assert.equal(pages, 4);
    const golden = await readFile(new URL("fixtures/codegen.golden.ts", import.meta.url), "utf8");
    assert.equal(first, golden);
  } finally {
    await server.close();
  }
});

test("accepts URL objects and explicit headers", async () => {
  let authorization;
  const server = await startMcpServer(
    async () => ({ tools: [SCHEMA_TOOLS[0], SCHEMA_TOOLS[1]] }),
    (request) => {
      authorization = request.headers.authorization;
    },
  );
  try {
    const generated = await generateToolTypes({
      headers: { authorization: "Bearer direct" },
      oauth: false,
      url: new URL(server.url),
    });
    assert.match(generated, /export const modelTool/u);
    assert.equal(authorization, "Bearer direct");
  } finally {
    await server.close();
  }
});

test("generates structured types for list[TextContent] tool results", async () => {
  const server = await startMcpServer(async () => ({ tools: [TEXT_CONTENT_TOOL] }));
  try {
    const generated = await generateToolTypes({ oauth: false, url: server.url });
    const golden = await readFile(new URL("fixtures/text-content.golden.ts", import.meta.url), "utf8");
    assert.equal(generated, golden);
  } finally {
    await server.close();
  }
});

test("generates common Python MCP v2 tool types", async () => {
  const server = await startMcpServer(async () => ({ tools: PYTHON_MCP_V2_TOOLS }));
  try {
    const generated = await generateToolTypes({ oauth: false, url: server.url });
    const golden = await readFile(new URL("fixtures/python-mcp-v2.golden.ts", import.meta.url), "utf8");
    assert.equal(generated, golden);
  } finally {
    await server.close();
  }
});

test("generates safe deterministic function identifiers", async () => {
  const server = await startMcpServer(async () => ({
    tools: [
      {
        inputSchema: { properties: {}, type: "object" },
        name: "class",
        outputSchema: { properties: {}, type: "object" },
      },
      {
        inputSchema: { properties: {}, type: "object" },
        name: "1-search",
        outputSchema: { properties: {}, type: "object" },
      },
      {
        inputSchema: { properties: {}, type: "object" },
        name: "namespace",
        outputSchema: { properties: {}, type: "object" },
      },
    ],
  }));
  try {
    const generated = await generateToolTypes({ oauth: false, url: server.url });
    assert.match(generated, /export const tool1Search =/u);
    assert.match(generated, /export const toolClass =/u);
    assert.match(generated, /export const toolNamespace =/u);
  } finally {
    await server.close();
  }
});

describe("rejects empty, duplicate, and unsupported tool schemas", () => {
  it("empty", async () => {
    const server = await startMcpServer(async () => ({ tools: [] }));
    try {
      await assert.rejects(generateToolTypes({ oauth: false, url: server.url }), /exposed no tools/u);
    } finally {
      await server.close();
    }
  });

  it("duplicate", async () => {
    const server = await startMcpServer(async () => ({
      tools: [SCHEMA_TOOLS[0], SCHEMA_TOOLS[0]],
    }));
    try {
      await assert.rejects(generateToolTypes({ oauth: false, url: server.url }), /duplicate tool name/u);
    } finally {
      await server.close();
    }
  });

  it("repeated pagination cursor", async () => {
    const server = await startMcpServer(async (request) =>
      request.params?.cursor === undefined
        ? { nextCursor: "repeat", tools: [SCHEMA_TOOLS[0]] }
        : { nextCursor: "repeat", tools: [] },
    );
    try {
      await assert.rejects(
        generateToolTypes({ oauth: false, url: server.url }),
        /repeated tools\/list cursor "repeat"/u,
      );
    } finally {
      await server.close();
    }
  });

  it("unsupported", async () => {
    const server = await startMcpServer(async () => ({
      tools: [
        {
          inputSchema: {
            properties: { value: { not: { type: "string" } } },
            type: "object",
          },
          name: "unsafe",
          outputSchema: { properties: {}, type: "object" },
        },
      ],
    }));
    try {
      await assert.rejects(
        generateToolTypes({ oauth: false, url: server.url }),
        /MCP tool "unsafe" has an inputSchema TypeScript cannot compile:.*unsupported JSON Schema keyword "not"/u,
      );
    } finally {
      await server.close();
    }
  });

  it("zod-incompatible output schema", async () => {
    const server = await startMcpServer(async () => ({
      tools: [
        {
          inputSchema: { properties: {}, type: "object" },
          name: "invalid-pattern",
          outputSchema: {
            properties: { value: { type: "string" } },
            type: "object",
            unevaluatedProperties: false,
          },
        },
      ],
    }));
    try {
      await assert.rejects(
        generateToolTypes({ oauth: false, url: server.url }),
        /MCP tool "invalid-pattern" has an outputSchema Zod cannot compile/u,
      );
    } finally {
      await server.close();
    }
  });
});

test("generates raw callers for tools without output schemas", async () => {
  const server = await startMcpServer(async () => ({
    tools: [
      {
        inputSchema: {
          properties: { query: { type: "string" } },
          required: ["query"],
          type: "object",
        },
        name: "raw-search",
      },
      SCHEMA_TOOLS[1],
    ],
  }));
  try {
    const generated = await generateToolTypes({ oauth: false, url: server.url });
    assert.match(generated, /import type \{ RawToolResult \} from "@belgie\/mcp";/u);
    assert.match(generated, /import \{ createGeneratedRawTool, createGeneratedTool \} from "@belgie\/mcp\/internal";/u);
    assert.match(generated, /export type RawSearchOutput = RawToolResult;/u);
    assert.match(generated, /export const rawSearch = createGeneratedRawTool<RawSearchInput>\(/u);
    assert.match(generated, /export const modelTool = createGeneratedTool<ModelToolInput, ModelToolOutput>\(/u);
  } finally {
    await server.close();
  }
});

test("imports only the raw factory for a raw-only server", async () => {
  const server = await startMcpServer(async () => ({
    tools: [
      {
        inputSchema: { properties: {}, type: "object" },
        name: "raw-only",
      },
    ],
  }));
  try {
    const generated = await generateToolTypes({ oauth: false, url: server.url });
    assert.match(generated, /import \{ createGeneratedRawTool \} from "@belgie\/mcp\/internal";/u);
    assert.doesNotMatch(generated, /createGeneratedTool/u);
  } finally {
    await server.close();
  }
});

test("validates malformed URLs and reports connection failures", async () => {
  await assert.rejects(generateToolTypes({ oauth: false, url: "not a url" }), /Invalid MCP URL/u);
  await assert.rejects(generateToolTypes({ oauth: false, url: "ftp://example.com/mcp" }), /must use http or https/u);
  await assert.rejects(
    generateToolTypes({ oauth: false, url: "https://user:secret@example.com/mcp" }),
    /must not contain credentials/u,
  );
  await assert.rejects(
    generateToolTypes({ oauth: false, url: "https://127.0.0.1:1/mcp" }),
    /Failed to generate MCP tool types/u,
  );
  const unavailable = createHttpServer();
  await new Promise((resolve) => unavailable.listen(0, "127.0.0.1", resolve));
  const address = unavailable.address();
  assert.ok(address && typeof address !== "string");
  await new Promise((resolve, reject) =>
    unavailable.close((error) => {
      error ? reject(error) : resolve();
    }),
  );
  await assert.rejects(
    generateToolTypes({ oauth: false, url: `http://127.0.0.1:${address.port}/mcp` }),
    /Failed to generate MCP tool types/u,
  );
  const cliFailure = await runCli([
    "generate",
    `http://127.0.0.1:${address.port}/mcp`,
    "--output",
    join(tmpdir(), "belgie-unavailable-mcp.ts"),
    "--no-oauth",
  ]);
  assert.equal(cliFailure.code, 1);
  assert.match(cliFailure.stderr, /Failed to generate MCP tool types/u);
});

test("preserves non-Error connection failures", async () => {
  const connect = vi.spyOn(Client.prototype, "connect").mockRejectedValue("raw failure");
  const close = vi.spyOn(Client.prototype, "close").mockResolvedValue();
  try {
    await assert.rejects(
      generateToolTypes({ oauth: false, url: "http://127.0.0.1:1/mcp" }),
      (cause) => cause === "raw failure",
    );
  } finally {
    connect.mockRestore();
    close.mockRestore();
  }
});

test("cLI writes and checks generated files with direct and environment headers", async () => {
  const observedHeaders = [];
  const server = await startMcpServer(
    async () => ({ tools: [SCHEMA_TOOLS[1]] }),
    (request) => observedHeaders.push(request.headers),
  );
  const directory = await mkdtemp(join(tmpdir(), "belgie-mcp-codegen-"));
  const output = join(directory, "mcp-tools.ts");
  try {
    const args = [
      "generate",
      server.url,
      "--output",
      output,
      "--no-oauth",
      "--header",
      "x-direct:direct-value",
      "--header-env",
      "authorization=TEST_MCP_TOKEN",
    ];
    const missing = await runCli([...args, "--check"], {
      TEST_MCP_TOKEN: "Bearer secret",
    });
    assert.equal(missing.code, 1);
    assert.match(missing.stderr, /stale or missing/u);
    const generated = await runCli(args, { TEST_MCP_TOKEN: "Bearer secret" });
    assert.equal(generated.code, 0, generated.stderr);
    const generatedSource = await readFile(output, "utf8");
    assert.match(generatedSource, /export const modelTool =/u);
    assert.doesNotMatch(generatedSource, /export const callTool/u);
    assert.doesNotMatch(generatedSource, /export const useTool/u);
    assert.ok(observedHeaders.some((headers) => headers["x-direct"] === "direct-value"));
    assert.ok(observedHeaders.some((headers) => headers.authorization === "Bearer secret"));

    const current = await runCli([...args, "--check"], {
      TEST_MCP_TOKEN: "Bearer secret",
    });
    assert.equal(current.code, 0, current.stderr);
    await writeFile(output, "stale\n", "utf8");
    const stale = await runCli([...args, "--check"], {
      TEST_MCP_TOKEN: "Bearer secret",
    });
    assert.equal(stale.code, 1);
    assert.match(stale.stderr, /stale or missing/u);
  } finally {
    await server.close();
  }
});

test("cLI rejects malformed and missing header configuration before connecting", async () => {
  const malformed = await runCli([
    "generate",
    "http://127.0.0.1:1/mcp",
    "--output",
    "ignored.ts",
    "--header",
    "missing-separator",
  ]);
  assert.equal(malformed.code, 1);
  assert.match(malformed.stderr, /expected NAME:VALUE/u);

  const missingEnvironment = await runCli([
    "generate",
    "http://127.0.0.1:1/mcp",
    "--output",
    "ignored.ts",
    "--header-env",
    "authorization=BELGIE_MISSING_TEST_VALUE",
  ]);
  assert.equal(missingEnvironment.code, 1);
  assert.match(missingEnvironment.stderr, /is not set/u);
});

test("completes dynamic OAuth registration, PKCE, state validation, and token use", async () => {
  const server = await startOAuthMcpServer();
  const directory = await mkdtemp(join(tmpdir(), "belgie-mcp-oauth-"));
  const output = join(directory, "mcp-tools.ts");
  let callbackUrl;
  let authorizationFetch;
  try {
    const result = await runCli(["generate", server.url, "--output", output, "--no-open"], {}, (chunk) => {
      const match = /https?:\/\/[^\s]+/u.exec(chunk);
      if (match && authorizationFetch === undefined) {
        const authorizationUrl = new URL(match[0]);
        callbackUrl = authorizationUrl.searchParams.get("redirect_uri");
        authorizationFetch = fetch(authorizationUrl).then((response) => {
          assert.equal(response.status, 200);
        });
      }
    });
    assert.equal(result.code, 0, result.stderr);
    await authorizationFetch;
    const generated = await readFile(output, "utf8");
    assert.match(generated, /export const modelTool =/u);
    assert.deepEqual(server.metrics(), {
      authenticatedRequests: 3,
      registrationCount: 1,
      tokenCount: 1,
    });
    assert.ok(callbackUrl);
    await assert.rejects(fetch(callbackUrl), /fetch failed/u);
  } finally {
    await server.close();
  }
});

test("generates through the source OAuth authorization retry", async () => {
  const server = await startOAuthMcpServer();
  let authorizationFetch;
  const write = vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
    const match = /https?:\/\/[^\s]+/u.exec(String(chunk));
    if (match && authorizationFetch === undefined) {
      authorizationFetch = fetch(new URL(match[0])).then((response) => {
        assert.equal(response.status, 200);
      });
    }
    return true;
  });
  try {
    const generated = await generateToolTypes({
      openBrowser: false,
      url: server.url,
    });
    await authorizationFetch;
    assert.match(generated, /export const modelTool/u);
    assert.deepEqual(server.metrics(), {
      authenticatedRequests: 3,
      registrationCount: 1,
      tokenCount: 1,
    });
  } finally {
    write.mockRestore();
    await server.close();
  }
});
