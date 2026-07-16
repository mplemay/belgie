import { createUseTool, defineToolRegistry } from "@belgie/mcp";

export type GetTimeInput = Record<string, never>;

export type GetTimeOutput = {
  "result": readonly GetTimeOutputTextContent[];
};

export type GetTimeOutputAnnotations = {
  "audience"?: readonly (("user" | "assistant") & string)[] | null;
  "lastModified"?: string | null;
  "priority"?: number | null;
};

export type GetTimeOutputTextContent = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: GetTimeOutputAnnotations | null;
  "text": string;
  "type"?: "text" & string;
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

export const useTool = createUseTool(tools);
