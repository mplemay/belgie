import { describe, expect, test } from "vitest";

import { generateTypes, type ToolSchema } from "../src/generate";

const payloadSchema = {
  type: "object",
  $defs: {
    Payload: {
      title: "Payload",
      type: "object",
      properties: {
        value: { type: "string" },
      },
      required: ["value"],
    },
  },
  properties: {
    payload: { $ref: "#/$defs/Payload" },
    count: { title: "Count", type: "integer", default: 1 },
  },
  required: ["payload"],
};

describe("generateTypes", () => {
  test("sorts tools and namespaces colliding definitions deterministically", async () => {
    const tools: ToolSchema[] = [
      {
        name: "zeta",
        inputSchema: payloadSchema,
        outputSchema: {
          ...payloadSchema,
          properties: { result: { $ref: "#/$defs/Payload" } },
          required: ["result"],
        },
      },
      {
        name: "alpha",
        inputSchema: payloadSchema,
        outputSchema: null,
      },
    ];

    const source = await generateTypes(tools);

    expect(source).toBe(await generateTypes([...tools].reverse()));
    expect(source.indexOf('"alpha"')).toBeLessThan(source.indexOf('"zeta"'));
    expect(source).toContain("export interface AlphaInputPayload");
    expect(source).toContain("export interface ZetaInputPayload");
    expect(source).toContain("export interface ZetaOutputPayload");
    expect(source).not.toContain("export type AlphaInputCount = number;");
    expect(source).not.toContain("export type ZetaInputCount = number;");
    expect(source).not.toContain("export type Count = number;");
    expect(source).toContain("output: undefined;");
    expect(source).toContain("count?: number;");
  });

  test("preserves exact tool names while avoiding TypeScript name collisions", async () => {
    const source = await generateTypes([
      { name: "get-time", inputSchema: { type: "object", properties: {} }, outputSchema: null },
      { name: "get_time", inputSchema: { type: "object", properties: {} }, outputSchema: null },
    ]);

    expect(source).toContain("export interface GetTimeInput {}");
    expect(source).toContain("export interface GetTime2Input {}");
    expect(source).toContain('"get-time": {');
    expect(source).toContain('"get_time": {');
  });

  test("rejects empty registries, duplicate names, and external references", async () => {
    await expect(generateTypes([])).rejects.toThrow("empty tool registry");
    await expect(
      generateTypes([
        { name: "same", inputSchema: { type: "object" }, outputSchema: null },
        { name: "same", inputSchema: { type: "object" }, outputSchema: null },
      ]),
    ).rejects.toThrow("Duplicate tool name");
    await expect(
      generateTypes([
        {
          name: "external",
          inputSchema: { type: "object", properties: { value: { $ref: "https://example.com/schema.json" } } },
          outputSchema: null,
        },
      ]),
    ).rejects.toThrow("External JSON Schema references are not supported");
  });
});
