import type { App } from "@modelcontextprotocol/ext-apps";

import {
  createCallTool,
  createUseTool,
  defineToolRegistry,
  type RawToolResult,
} from "@belgie/mcp";

type ExampleTools = {
  empty: {
    input: Record<string, never>;
    output: { value: string };
  };
  optional: {
    input: { limit?: number };
    output: RawToolResult;
  };
  required: {
    input: { id: string };
    output: { value: number };
  };
};

const tools = defineToolRegistry<ExampleTools>({
  empty: "structured",
  optional: "raw",
  required: "structured",
});
const callTool = createCallTool(tools);
const useTool = createUseTool(tools);

declare const app: App;

export function TypeFixture() {
  const empty = useTool("empty");
  const optional = useTool("optional");
  const limited = useTool("optional", { limit: 1 });
  const required = useTool("required", { id: "example" });
  const withApp = useTool("required", { id: "example" }, { app });
  const emptyWithApp = useTool("empty", undefined, { app });

  void empty.mutate();
  void optional.mutate();
  void limited.mutate();
  void required.mutate();
  void withApp.mutate();
  void emptyWithApp.mutate();
  const called: Promise<{ value: number }> = callTool("required", {
    id: "example",
  });
  void called;
  void callTool("empty");
  void callTool("optional");
  void callTool("optional", { limit: 1 });
  void callTool("required", { id: "example" }, { app });
  void callTool("empty", undefined, { app });
  void callTool("optional", undefined, { app });

  // @ts-expect-error required hook input cannot be omitted
  useTool("required");
  // @ts-expect-error required hook input property has the wrong type
  useTool("required", { id: 1 });
  // @ts-expect-error undeclared hook input properties are rejected
  useTool("required", { id: "example", extra: true });
  // @ts-expect-error empty hook inputs reject undeclared properties
  useTool("empty", { extra: true });
  // @ts-expect-error inputs are bound to the hook rather than mutate
  void required.mutate({ id: "example" });
  // @ts-expect-error required caller input cannot be omitted
  void callTool("required");
  // @ts-expect-error required caller input property has the wrong type
  void callTool("required", { id: 1 });
  // @ts-expect-error undeclared caller input properties are rejected
  void callTool("required", { id: "example", extra: true });
  // @ts-expect-error unknown hook tool names are rejected
  useTool("missing");
  // @ts-expect-error unknown caller tool names are rejected
  void callTool("missing");
  // @ts-expect-error options cannot replace required input
  void callTool("required", { app });
  // @ts-expect-error unknown option keys are rejected
  void callTool("empty", undefined, { app, extra: true });
  // @ts-expect-error options cannot replace required hook input
  useTool("required", { app });
  // @ts-expect-error unknown option keys are rejected on the hook
  useTool("empty", undefined, { app, extra: true });

  const structured: number | undefined = required.data?.value;
  const raw: RawToolResult | undefined = optional.data;
  const loading: boolean = required.isLoading;
  return <>{structured ?? raw?.content.length ?? String(loading)}</>;
}
