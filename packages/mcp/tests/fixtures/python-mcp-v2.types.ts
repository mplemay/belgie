import type { RawToolResult, ToolCallResult } from "@belgie/mcp";

import {
  annotatedClassOutput,
  anyOutput,
  audioHelper,
  commonInputs,
  contentBlocks,
  dataclassOutput,
  dictionaryOutput,
  directResult,
  disabledOutput,
  genericOutput,
  imageHelper,
  primitiveOutput,
  typedDictOutput,
  type AnnotatedClassOutputOutput,
  type AnyOutputOutput,
  type AudioHelperOutput,
  type CommonInputsInput,
  type CommonInputsOutput,
  type ContentBlocksOutput,
  type DataclassOutputOutput,
  type DictionaryOutputOutput,
  type DirectResultOutput,
  type DisabledOutputOutput,
  type GenericOutputOutput,
  type ImageHelperOutput,
  type PrimitiveOutputOutput,
  type TypedDictOutputOutput,
} from "./python-mcp-v2.golden";

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  <Value>() => Value extends Right ? 1 : 2
    ? true
    : false;
type Assert<Value extends true> = Value;

export type AnyIsRaw = Assert<Equal<AnyOutputOutput, RawToolResult>>;
export type AudioIsRaw = Assert<Equal<AudioHelperOutput, RawToolResult>>;
export type DirectResultIsRaw = Assert<Equal<DirectResultOutput, RawToolResult>>;
export type DisabledIsRaw = Assert<Equal<DisabledOutputOutput, RawToolResult>>;
export type ImageIsRaw = Assert<Equal<ImageHelperOutput, RawToolResult>>;

declare const input: CommonInputsInput;
declare const output: CommonInputsOutput;
declare const content: ContentBlocksOutput;
declare const annotatedPoint: AnnotatedClassOutputOutput;
declare const dataclassPoint: DataclassOutputOutput;
declare const dictionary: DictionaryOutputOutput;
declare const generic: GenericOutputOutput;
declare const primitive: PrimitiveOutputOutput;
declare const typedDictionary: TypedDictOutputOutput;

const requiredString: string = input.required;
const optionalString: string | null | undefined = input.optional;
const defaultedNumber: number | undefined = input.limit;
const bytesAsJson: string = input.raw;
const nullableNumber: number | null = input.ratio;
const stringList: readonly string[] = input.items;
const stringSet: readonly string[] = input.tags;
const frozenNumbers: readonly number[] = input.frozen;
const fixedTuple: readonly [string, number] = input.pair;
const variadicTuple: readonly number[] = input.variable;
const typedMapping: Record<string, number> = input.mapping;
const openMapping: Record<string, unknown> = input.anything;
const jsonValue: unknown = input.json_value;
const optionalTypedDictKey: number | undefined = input.payload.count;
const recursiveNode: CommonInputsInput["node"] | null | undefined = input.node.child;
const discriminatedPet: "cat" | "dog" = input.zoo.pet.kind;
const decimalJson: number | string = input.amount;
const pathJson: string = input.path;
const urlJson: string = input.url;

const nestedOptionalTypedDictKey: number | undefined = output.payload.count;
const nestedRecursiveNode: CommonInputsOutput["node"] | null | undefined = output.node.child;
const annotatedCoordinate: number = annotatedPoint.x;
const dataclassCoordinate: number = dataclassPoint.y;
const dictionaryValue: number | undefined = dictionary.key;
const genericValue: string | undefined = generic.result[0];
const primitiveValue: string = primitive.result;
const typedDictionaryValue: number = typedDictionary.count;

function inspectContentBlock(
  block: ContentBlocksOutput["result"][number],
): string {
  const metadata: Record<string, unknown> | null | undefined = block._meta;
  const priority: number | null | undefined = block.annotations?.priority;
  void metadata;
  void priority;

  switch (block.type) {
    case "text":
      return block.text;
    case "image":
    case "audio":
      return `${block.mimeType}:${block.data}`;
    case "resource_link": {
      const iconSource: string | undefined = block.icons?.[0]?.src;
      return iconSource ?? block.uri;
    }
    case "resource":
      if ("text" in block.resource) {
        return `${block.resource.uri}:${block.resource.text}`;
      }
      return `${block.resource.uri}:${block.resource.blob}`;
    default:
      return "unknown";
  }
}

const rawCall: Promise<ToolCallResult<RawToolResult>> = imageHelper();

void annotatedClassOutput();
void anyOutput();
void audioHelper();
void commonInputs(input);
void contentBlocks();
void dataclassOutput();
void dictionaryOutput();
void directResult();
void disabledOutput();
void genericOutput();
void primitiveOutput();
void typedDictOutput();

// @ts-expect-error required tool inputs cannot be omitted
void commonInputs();
// @ts-expect-error empty tool inputs reject undeclared properties
void contentBlocks({ unexpected: true });
// @ts-expect-error literal choices remain closed
const invalidChoice: CommonInputsInput["choice"] = "c";
// @ts-expect-error fixed tuples retain their length and element types
const invalidPair: CommonInputsInput["pair"] = ["only-one"];

void requiredString;
void optionalString;
void defaultedNumber;
void bytesAsJson;
void nullableNumber;
void stringList;
void stringSet;
void frozenNumbers;
void fixedTuple;
void variadicTuple;
void typedMapping;
void openMapping;
void jsonValue;
void optionalTypedDictKey;
void recursiveNode;
void discriminatedPet;
void decimalJson;
void pathJson;
void urlJson;
void nestedOptionalTypedDictKey;
void nestedRecursiveNode;
void annotatedCoordinate;
void dataclassCoordinate;
void dictionaryValue;
void genericValue;
void primitiveValue;
void typedDictionaryValue;
void inspectContentBlock(content.result[0]);
void rawCall;
