import {
  createUseTool,
  defineToolRegistry,
  type RawToolResult,
} from "@belgie/mcp";

type ExampleTools = {
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
  optional: "raw",
  required: "structured",
});
const useTool = createUseTool(tools);

export function TypeFixture() {
  const optional = useTool("optional");
  const required = useTool("required");

  void optional.call();
  void optional.call({ limit: 1 });
  void required.call({ id: "example" });

  // @ts-expect-error required tool input cannot be omitted
  void required.call();
  // @ts-expect-error required input property has the wrong type
  void required.call({ id: 1 });
  // @ts-expect-error undeclared input properties are rejected
  void required.call({ id: "example", extra: true });
  // @ts-expect-error unknown tool names are rejected
  useTool("missing");

  const structured: number | undefined = required.result?.value;
  const raw: RawToolResult | null = optional.result;
  return <>{structured ?? raw?.content.length}</>;
}
