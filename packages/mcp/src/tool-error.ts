import type { App } from "@modelcontextprotocol/ext-apps";

export type RawToolResult = Awaited<ReturnType<App["callServerTool"]>>;

export type McpToolErrorResult = RawToolResult & { isError: true };

function mcpToolErrorMessage(
  toolName: string,
  result: McpToolErrorResult,
): string {
  return (
    result.content
      .map((content) => (content.type === "text" ? content.text : ""))
      .filter(Boolean)
      .join("\n") || `MCP tool ${JSON.stringify(toolName)} returned an error`
  );
}

export class McpToolError extends Error {
  readonly toolName: string;
  readonly result: McpToolErrorResult;

  constructor(toolName: string, result: McpToolErrorResult) {
    super(mcpToolErrorMessage(toolName, result), { cause: result });
    this.name = "McpToolError";
    this.toolName = toolName;
    this.result = result;
  }
}

export type ToolCallError = Error;

export type ToolCallResult<Output> =
  | { result: Output; error: undefined }
  | { result: undefined; error: ToolCallError };
