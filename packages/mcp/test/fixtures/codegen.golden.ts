import { createCallTool, createUseTool, defineToolRegistry, type RawToolResult } from "@belgie/mcp";

export type ModelToolInput = {
  "choices"?: readonly ("a" | "b")[];
  "labels"?: Record<string, string>;
  "metrics"?: {
    "name": string;
    [key: string]: string | number;
  };
  "node": ModelToolInputNode;
  "pair": readonly [string, number];
  "value"?: "auto" | number | null;
};

export type ModelToolInputNode = {
  "name": string;
  "next"?: ModelToolInputNode | null;
};

export type ModelToolOutput = {
  "payload": {
    "id": string;
  } & {
    "active": boolean;
  };
};

export type ModelToolInput2 = {
  "limit"?: number;
};

export type McpTools = {
  /**
   * Build a model.
   * This closes * / safely.
   */
  "model-tool": {
    input: ModelToolInput;
    output: ModelToolOutput;
  };
  "model_tool": {
    input: ModelToolInput2;
    output: RawToolResult;
  };
};

export const tools = defineToolRegistry<McpTools>({
  "model-tool": "structured",
  "model_tool": "raw",
});

export const callTool = createCallTool(tools);

export const useTool = createUseTool(tools);
