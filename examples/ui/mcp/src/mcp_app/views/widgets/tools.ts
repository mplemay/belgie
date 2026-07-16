import { createCallTool, createUseTool, defineToolRegistry } from "@belgie/mcp";

export type GetTimeInput = Record<string, never>;

export type GetTimeOutput = {
  "time": string;
};

export type McpTools = {
  /** Get the current server time in ISO 8601 format. */
  "get-time": {
    input: GetTimeInput;
    output: GetTimeOutput;
  };
};

export const tools = defineToolRegistry<McpTools>({
  "get-time": "structured",
});

export const callTool = createCallTool(tools);

export const useTool = createUseTool(tools);
