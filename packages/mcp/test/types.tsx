import type { App } from "@modelcontextprotocol/ext-apps";

import {
  McpToolError,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "@belgie/mcp";
import { createGeneratedTool } from "@belgie/mcp/internal";

type EmptyOutput = { value: string };
type OptionalOutput = { count: number };
type RequiredOutput = { value: number };

const empty = createGeneratedTool<Record<string, never>, EmptyOutput>("empty", {
  type: "object",
  properties: { value: { type: "string" } },
  required: ["value"],
});
const optional = createGeneratedTool<{ limit?: number }, OptionalOutput>(
  "optional",
  {
    type: "object",
    properties: { count: { type: "integer" } },
    required: ["count"],
  },
);
const required = createGeneratedTool<{ id: string }, RequiredOutput>("required", {
  type: "object",
  properties: { value: { type: "number" } },
  required: ["value"],
});

declare const app: App;

type PublicMcpExports = keyof typeof import("@belgie/mcp");
type GenericCallersAreAbsent = Extract<
  PublicMcpExports,
  "callTool" | "useTool"
> extends never
  ? true
  : false;

const genericCallersAreAbsent: GenericCallersAreAbsent = true;
const requiredCall: Promise<ToolCallResult<RequiredOutput>> = required({
  id: "example",
});

function narrowToolError(error: ToolCallError): void {
  const standardError: Error = error;
  if (error instanceof McpToolError) {
    const toolName: string = error.toolName;
    const result: RawToolResult = error.result;
    const isError: true = error.result.isError;
    const cause: unknown = error.cause;
    void toolName;
    void result;
    void isError;
    void cause;
  }
  void standardError;
}

async function narrowResult(): Promise<number> {
  const response = await required({ id: "example" });
  if (response.error !== undefined) {
    const error: ToolCallError = response.error;
    const result: undefined = response.result;
    narrowToolError(error);
    void error;
    void result;
    return 0;
  }

  const error: undefined = response.error;
  const result: RequiredOutput = response.result;
  void error;
  return result.value;
}

export function TypeFixture() {
  void empty();
  void empty(undefined, app);
  void optional();
  void optional({ limit: 1 });
  void optional({ limit: 1 }, app);
  void optional(undefined, app);
  void required({ id: "example" });
  void required({ id: "example" }, app);

  // @ts-expect-error required input cannot be omitted
  void required();
  // @ts-expect-error required input property has the wrong type
  void required({ id: 1 });
  // @ts-expect-error undeclared input properties are rejected
  void required({ id: "example", extra: true });
  // @ts-expect-error empty inputs reject undeclared properties
  void empty({ extra: true });
  // @ts-expect-error the explicit app is the second argument
  void required(app);
  // @ts-expect-error app options wrappers are no longer accepted
  void required({ id: "example" }, { app });
  // @ts-expect-error a third argument is never accepted
  void required({ id: "example" }, app, app);

  void genericCallersAreAbsent;
  void requiredCall;
  void narrowResult();
  return null;
}
