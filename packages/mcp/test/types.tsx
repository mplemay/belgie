import {
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
const useTool = createUseTool(tools);

export function TypeFixture() {
  const empty = useTool("empty");
  const optional = useTool("optional");
  const required = useTool("required");

  empty.mutate();
  optional.mutate();
  optional.mutate({ limit: 1 });
  required.mutate({ id: "example" });
  void required.mutateAsync({ id: "example" });

  // @ts-expect-error inputs are supplied when the mutation is triggered
  useTool("required", { id: "example" });
  // @ts-expect-error required tool input cannot be omitted when triggering
  required.mutate();
  // @ts-expect-error required input property has the wrong type
  required.mutate({ id: 1 });
  // @ts-expect-error undeclared input properties are rejected
  required.mutate({ id: "example", extra: true });
  // @ts-expect-error empty tool inputs reject undeclared properties
  empty.mutate({ extra: true });
  // @ts-expect-error unknown tool names are rejected
  useTool("missing");

  const structured: number | undefined = required.data?.value;
  const raw: RawToolResult | undefined = optional.data;
  const pending: boolean = required.isPending;
  return <>{structured ?? raw?.content.length ?? String(pending)}</>;
}
