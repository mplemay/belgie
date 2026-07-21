import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { Tool } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { MemoryOAuthProvider, oauthState, startOAuthCallbackServer } from "./oauth";
import { IdentifierAllocator, ValueIdentifierAllocator, compileSchema, typeIdentifier } from "./schema";

export interface GenerateToolTypesOptions {
  url: string | URL;
  headers?: Readonly<Record<string, string>>;
  oauth?: boolean;
  openBrowser?: boolean;
}

interface ToolNames {
  call: string;
  input: string;
  output: string;
}

type OutputSchema = NonNullable<Tool["outputSchema"]>;
type ZodJsonSchema = Parameters<typeof z.fromJSONSchema>[0];

function endpoint(value: string | URL): URL {
  let url: URL;
  try {
    url = value instanceof URL ? new URL(value) : new URL(value);
  } catch (error: unknown) {
    throw new Error(`Invalid MCP URL ${JSON.stringify(String(value))}`, { cause: error });
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
    return [`/** ${lines[0]} */`];
  }
  return ["/**", ...lines.map((line) => ` * ${line}`), " */"];
}

function compareStrings(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => canonicalize(item));
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value)
        .toSorted(([left], [right]) => compareStrings(left, right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

function renderSchema(schema: OutputSchema): string[] {
  return JSON.stringify(canonicalize(schema), null, 2)
    .split("\n")
    .map((line) => `  ${line}`);
}

function compileToolSchema(
  tool: Tool,
  schemaName: "inputSchema" | "outputSchema",
  schema: unknown,
  rootName: string,
  allocator: IdentifierAllocator,
): string[] {
  try {
    return compileSchema(schema, rootName, allocator).declarations;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `MCP tool ${JSON.stringify(tool.name)} has an ${schemaName} TypeScript cannot compile: ${message}`,
      { cause: error },
    );
  }
}

function renderToolTypes(tools: Tool[]): string {
  const allocator = new IdentifierAllocator();
  const valueAllocator = new ValueIdentifierAllocator();
  const names = new Map<string, ToolNames>();
  for (const tool of tools) {
    const base = typeIdentifier(tool.name);
    names.set(tool.name, {
      call: valueAllocator.allocate(tool.name),
      input: allocator.allocate(`${base}Input`),
      output: allocator.allocate(`${base}Output`),
    });
  }

  let hasRawTools = false;
  let hasStructuredTools = false;
  const declarations: string[] = [];
  for (const tool of tools) {
    const toolNames = names.get(tool.name)!;
    declarations.push(...compileToolSchema(tool, "inputSchema", tool.inputSchema, toolNames.input, allocator));
    if (tool.outputSchema === undefined) {
      hasRawTools = true;
      declarations.push(`export type ${toolNames.output} = RawToolResult;`);
    } else {
      hasStructuredTools = true;
      try {
        z.fromJSONSchema(tool.outputSchema as ZodJsonSchema);
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`MCP tool ${JSON.stringify(tool.name)} has an outputSchema Zod cannot compile: ${message}`, {
          cause: error,
        });
      }
      declarations.push(...compileToolSchema(tool, "outputSchema", tool.outputSchema, toolNames.output, allocator));
    }
  }

  const calls: string[] = [];
  for (const tool of tools) {
    if (tool.description) {
      calls.push(...jsDoc(tool.description));
    }
    const toolNames = names.get(tool.name)!;
    if (tool.outputSchema === undefined) {
      calls.push(
        `export const ${toolNames.call} = createGeneratedRawTool<${toolNames.input}>(`,
        `  ${JSON.stringify(tool.name)},`,
        ");",
        "",
      );
    } else {
      calls.push(
        `export const ${toolNames.call} = createGeneratedTool<${toolNames.input}, ${toolNames.output}>(`,
        `  ${JSON.stringify(tool.name)},`,
        ...renderSchema(tool.outputSchema),
        ");",
        "",
      );
    }
  }

  const factoryImports = [
    ...(hasRawTools ? ["createGeneratedRawTool"] : []),
    ...(hasStructuredTools ? ["createGeneratedTool"] : []),
  ].join(", ");

  return [
    ...(hasRawTools ? ['import type { RawToolResult } from "@belgie/mcp";'] : []),
    `import { ${factoryImports} } from "@belgie/mcp/internal";`,
    "",
    ...declarations.flatMap((declaration) => [declaration, ""]),
    ...calls,
  ].join("\n");
}

function createConnection(
  url: URL,
  headers: Readonly<Record<string, string>>,
  provider: MemoryOAuthProvider | undefined,
) {
  const client = new Client({ name: "belgie-mcp-codegen", version: "0.1.0" }, { capabilities: {} });
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
  return [...tools.values()].toSorted((left, right) => compareStrings(left.name, right.name));
}

export async function generateToolTypes(options: GenerateToolTypesOptions): Promise<string> {
  const url = endpoint(options.url);
  const headers = options.headers ?? {};
  const useOAuth = options.oauth ?? true;
  const state = oauthState();
  const callback = useOAuth ? await startOAuthCallbackServer(state) : undefined;
  const provider =
    callback === undefined
      ? undefined
      : new MemoryOAuthProvider({
          openBrowser: options.openBrowser ?? true,
          redirectUrl: callback.redirectUrl,
          state,
        });
  let connection: ReturnType<typeof createConnection> | undefined;

  try {
    connection = createConnection(url, headers, provider);
    try {
      await connection.client.connect(connection.transport as Transport);
    } catch (error: unknown) {
      if (!(error instanceof UnauthorizedError) || provider === undefined || callback === undefined) {
        throw error;
      }
      const code = await callback.waitForCode();
      await connection.transport.finishAuth(code);
      await connection.client.close();
      connection = createConnection(url, headers, provider);
      await connection.client.connect(connection.transport as Transport);
    }
    return renderToolTypes(await discoverTools(connection.client));
  } catch (error: unknown) {
    if (error instanceof Error) {
      throw new TypeError(`Failed to generate MCP tool types from ${url.toString()}: ${error.message}`, {
        cause: error,
      });
    }
    throw error;
  } finally {
    await Promise.allSettled([connection?.client.close(), callback?.close()]);
  }
}
