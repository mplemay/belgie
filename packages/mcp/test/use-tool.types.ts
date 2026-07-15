import { expectTypeOf } from "vitest";

import { createUseTool, type UseToolResult } from "../src/use-tool";

interface EmptyInput {}

interface OptionalInput {
  value?: string;
}

interface RequiredInput {
  value: string;
  count?: number;
}

interface Tools {
  empty: { input: EmptyInput; output: undefined };
  optional: { input: OptionalInput; output: { result: number } };
  required: { input: RequiredInput; output: { result: string } };
}

const useTool = createUseTool<Tools>();

function verifyTypes(): void {
  const empty = useTool("empty");
  void empty.call();
  // @ts-expect-error Empty tool inputs do not accept an argument.
  void empty.call({});

  const optional = useTool("optional");
  void optional.call();
  void optional.call({ value: "value" });
  expectTypeOf(optional.data).toEqualTypeOf<{ result: number } | undefined>();

  const required = useTool("required");
  // @ts-expect-error Required tool fields require an input object.
  void required.call();
  void required.call({ value: "value" });
  // @ts-expect-error The generated input controls accepted field types.
  void required.call({ value: 42 });
  expectTypeOf(required).toEqualTypeOf<UseToolResult<Tools["required"]>>();

  // @ts-expect-error Tool names are constrained to generated registry keys.
  useTool("missing");
}

void verifyTypes;
