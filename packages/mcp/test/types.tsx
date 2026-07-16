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
  const limited = useTool("optional", { limit: 1 });
  const required = useTool("required", { id: "example" });

  void empty.call();
  void optional.call();
  void limited.call();
  void required.call();

  // @ts-expect-error required tool input cannot be omitted
  useTool("required");
  // @ts-expect-error required input property has the wrong type
  useTool("required", { id: 1 });
  // @ts-expect-error undeclared input properties are rejected
  useTool("required", { id: "example", extra: true });
  // @ts-expect-error empty tool inputs reject undeclared properties
  useTool("empty", { extra: true });
  // @ts-expect-error inputs are bound when the hook is created
  void required.call({ id: "example" });
  // @ts-expect-error unknown tool names are rejected
  useTool("missing");

  const structured: number | undefined = required.result?.value;
  const raw: RawToolResult | null = optional.result;
  return <>{structured ?? raw?.content.length}</>;
}
