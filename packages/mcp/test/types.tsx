import type { App } from "@modelcontextprotocol/ext-apps";

import {
  McpToolError,
  downloadFile,
  openLink,
  requestDisplayMode,
  requestTeardown,
  sendLog,
  sendMessage,
  updateModelContext,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "@belgie/mcp";
import {
  createGeneratedRawTool,
  createGeneratedTool,
} from "@belgie/mcp/internal";

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
const raw = createGeneratedRawTool<{ query: string }>("raw");

declare const app: App;

const message = {
  role: "user" as const,
  content: [{ type: "text" as const, text: "hello" }],
};
const log = { level: "info" as const, data: "hello" };
const modelContext = {
  content: [{ type: "text" as const, text: "context" }],
};
const link = { url: "https://example.com" };
const download = {
  contents: [
    {
      type: "resource_link" as const,
      uri: "https://example.com/file",
      name: "file",
    },
  ],
};
const displayMode = { mode: "fullscreen" as const };
const requestOptions = { signal: new AbortController().signal };

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
const rawCall: Promise<ToolCallResult<RawToolResult>> = raw({ query: "example" });

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
  const messageResult: ReturnType<App["sendMessage"]> = sendMessage(
    message,
    requestOptions,
  );
  const logResult: ReturnType<App["sendLog"]> = sendLog(log);
  const modelContextResult: ReturnType<App["updateModelContext"]> =
    updateModelContext(modelContext, requestOptions);
  const openLinkResult: ReturnType<App["openLink"]> = openLink(
    link,
    requestOptions,
  );
  const downloadResult: ReturnType<App["downloadFile"]> = downloadFile(
    download,
    requestOptions,
  );
  const displayModeResult: ReturnType<App["requestDisplayMode"]> =
    requestDisplayMode(displayMode, requestOptions);
  const teardownResult: ReturnType<App["requestTeardown"]> = requestTeardown();

  void empty();
  void empty(undefined, app);
  void optional();
  void optional({ limit: 1 });
  void optional({ limit: 1 }, app);
  void optional(undefined, app);
  void required({ id: "example" });
  void required({ id: "example" }, app);
  void raw({ query: "example" });
  void raw({ query: "example" }, app);

  // @ts-expect-error required input cannot be omitted
  void required();
  // @ts-expect-error required input property has the wrong type
  void required({ id: 1 });
  // @ts-expect-error raw callers preserve required input typing
  void raw();
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
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void sendMessage(message, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void sendLog(log, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void updateModelContext(modelContext, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void openLink(link, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void downloadFile(download, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void requestDisplayMode(displayMode, app);
  // @ts-expect-error context-bound helpers do not accept an explicit app
  void requestTeardown(undefined, app);

  void genericCallersAreAbsent;
  void messageResult;
  void logResult;
  void modelContextResult;
  void openLinkResult;
  void downloadResult;
  void displayModeResult;
  void teardownResult;
  void requiredCall;
  void rawCall;
  void narrowResult();
  return null;
}
