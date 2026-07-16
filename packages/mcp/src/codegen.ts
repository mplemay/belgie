import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";

import {
  MemoryOAuthProvider,
  oauthState,
  startOAuthCallbackServer,
} from "./oauth";
import { compileSchema, IdentifierAllocator, typeIdentifier } from "./schema";

export type GenerateToolTypesOptions = {
  url: string | URL;
  headers?: Readonly<Record<string, string>>;
  oauth?: boolean;
  openBrowser?: boolean;
};

type ToolNames = {
  input: string;
  output: string | undefined;
};

function endpoint(value: string | URL): URL {
  let url: URL;
  try {
    url = value instanceof URL ? new URL(value) : new URL(value);
  } catch (cause: unknown) {
    throw new Error(`Invalid MCP URL ${JSON.stringify(String(value))}`, { cause });
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`MCP URL must use http or https, received ${JSON.stringify(url.protocol)}`);
  }
  if (url.username || url.password) {
    throw new Error("MCP URL must not contain credentials; use headers instead");
  }
  return url;
}

function jsDoc(description: string): string[] {
  const sanitized = description.replaceAll("*/", "* /").replaceAll("\r", "");
  const lines = sanitized.split("\n");
  if (lines.length === 1) {
    return [`  /** ${lines[0]} */`];
  }
  return ["  /**", ...lines.map((line) => `   * ${line}`), "   */"];
}

function renderToolTypes(tools: Tool[]): string {
  const allocator = new IdentifierAllocator();
  const names = new Map<string, ToolNames>();
  for (const tool of tools) {
    const base = typeIdentifier(tool.name);
    names.set(tool.name, {
      input: allocator.allocate(`${base}Input`),
      output:
        tool.outputSchema === undefined
          ? undefined
          : allocator.allocate(`${base}Output`),
    });
  }

  const declarations: string[] = [];
  for (const tool of tools) {
    const toolNames = names.get(tool.name)!;
    declarations.push(
      ...compileSchema(tool.inputSchema, toolNames.input, allocator).declarations,
    );
    if (tool.outputSchema !== undefined && toolNames.output !== undefined) {
      declarations.push(
        ...compileSchema(tool.outputSchema, toolNames.output, allocator).declarations,
      );
    }
  }

  const hasRawTools = tools.some((tool) => tool.outputSchema === undefined);
  const imports = ["createCallTool", "createUseTool", "defineToolRegistry"];
  const typeImports = hasRawTools ? ", type RawToolResult" : "";
  const registryMembers: string[] = [];
  for (const tool of tools) {
    if (tool.description) {
      registryMembers.push(...jsDoc(tool.description));
    }
    const toolNames = names.get(tool.name)!;
    registryMembers.push(
      `  ${JSON.stringify(tool.name)}: {`,
      `    input: ${toolNames.input};`,
      `    output: ${toolNames.output ?? "RawToolResult"};`,
      "  };",
    );
  }

  const modes = tools
    .map(
      (tool) =>
        `  ${JSON.stringify(tool.name)}: ${JSON.stringify(
          tool.outputSchema === undefined ? "raw" : "structured",
        )},`,
    )
    .join("\n");

  return [
    `import { ${imports.join(", ")}${typeImports} } from "@belgie/mcp";`,
    "",
    ...declarations.flatMap((declaration) => [declaration, ""]),
    "export type McpTools = {",
    ...registryMembers,
    "};",
    "",
    "export const tools = defineToolRegistry<McpTools>({",
    modes,
    "});",
    "",
    "export const callTool = createCallTool(tools);",
    "",
    "export const useTool = createUseTool(tools);",
    "",
  ].join("\n");
}

function createConnection(
  url: URL,
  headers: Readonly<Record<string, string>>,
  provider: MemoryOAuthProvider | undefined,
) {
  const client = new Client(
    { name: "belgie-mcp-codegen", version: "0.1.0" },
    { capabilities: {} },
  );
  const transport = new StreamableHTTPClientTransport(url, {
    ...(provider === undefined ? {} : { authProvider: provider }),
    requestInit: { headers: new Headers(headers) },
  });
  return { client, transport };
}

async function discoverTools(client: Client): Promise<Tool[]> {
  const tools = new Map<string, Tool>();
  const cursors = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await client.listTools(cursor === undefined ? undefined : { cursor });
    for (const tool of page.tools) {
      if (tools.has(tool.name)) {
        throw new Error(`MCP server exposed duplicate tool name ${JSON.stringify(tool.name)}`);
      }
      tools.set(tool.name, tool);
    }
    cursor = page.nextCursor;
    if (cursor !== undefined && cursors.has(cursor)) {
      throw new Error(`MCP server repeated tools/list cursor ${JSON.stringify(cursor)}`);
    }
    if (cursor !== undefined) {
      cursors.add(cursor);
    }
  } while (cursor !== undefined);

  if (tools.size === 0) {
    throw new Error("MCP server exposed no tools");
  }
  return [...tools.values()].sort((left, right) => {
    if (left.name < right.name) return -1;
    if (left.name > right.name) return 1;
    return 0;
  });
}

export async function generateToolTypes(
  options: GenerateToolTypesOptions,
): Promise<string> {
  const url = endpoint(options.url);
  const headers = options.headers ?? {};
  const useOAuth = options.oauth ?? true;
  const state = oauthState();
  const callback = useOAuth ? await startOAuthCallbackServer(state) : undefined;
  const provider =
    callback === undefined
      ? undefined
      : new MemoryOAuthProvider({
          redirectUrl: callback.redirectUrl,
          state,
          openBrowser: options.openBrowser ?? true,
        });
  let connection: ReturnType<typeof createConnection> | undefined;

  try {
    connection = createConnection(url, headers, provider);
    try {
      await connection.client.connect(connection.transport as Transport);
    } catch (cause: unknown) {
      if (!(cause instanceof UnauthorizedError) || provider === undefined || callback === undefined) {
        throw cause;
      }
      const code = await callback.waitForCode();
      await connection.transport.finishAuth(code);
      await connection.client.close();
      connection = createConnection(url, headers, provider);
      await connection.client.connect(connection.transport as Transport);
    }
    return renderToolTypes(await discoverTools(connection.client));
  } catch (cause: unknown) {
    if (cause instanceof Error) {
      throw new Error(`Failed to generate MCP tool types from ${url.toString()}: ${cause.message}`, {
        cause,
      });
    }
    throw cause;
  } finally {
    await Promise.allSettled([connection?.client.close(), callback?.close()]);
  }
}
