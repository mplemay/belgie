import type { App } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";

import { getActiveWidget } from "./widget-context";

export type RawToolResult = Awaited<ReturnType<App["callServerTool"]>>;

export type McpToolError = RawToolResult & { isError: true };

export type ToolCallError = Error | McpToolError;

export type ToolCallResult<Output> =
  | { result: Output; error: undefined }
  | { result: undefined; error: ToolCallError };

type GeneratedTool<Input extends object, Output> = {} extends Input
  ? (input?: Input, app?: App) => Promise<ToolCallResult<Output>>
  : (input: Input, app?: App) => Promise<ToolCallResult<Output>>;

type OutputSchema = Parameters<typeof z.fromJSONSchema>[0];

function errorResult(error: ToolCallError): ToolCallResult<never> {
  return { result: undefined, error };
}

export function createGeneratedTool<Input extends object, Output>(
  name: string,
  outputSchema: OutputSchema,
): GeneratedTool<Input, Output> {
  const schema = z.fromJSONSchema(outputSchema) as z.ZodType<Output>;

  return (async (
    input?: Input,
    explicitApp?: App,
  ): Promise<ToolCallResult<Output>> => {
    try {
      const app = explicitApp ?? getActiveWidget();
      const response = await app.callServerTool({
        name,
        ...(input === undefined
          ? {}
          : { arguments: input as Record<string, unknown> }),
      });
      if (response.isError) {
        return errorResult(response as McpToolError);
      }

      const parsed = schema.safeParse(response.structuredContent);
      if (!parsed.success) {
        return errorResult(parsed.error);
      }
      return { result: parsed.data, error: undefined };
    } catch (cause: unknown) {
      return errorResult(
        cause instanceof Error ? cause : new Error(String(cause)),
      );
    }
  }) as GeneratedTool<Input, Output>;
}
