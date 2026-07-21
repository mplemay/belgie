import assert from "node:assert/strict";

import { IdentifierAllocator, ValueIdentifierAllocator, compileSchema, typeIdentifier } from "../src/schema.ts";

function compile(schema: unknown, rootName = "Example"): string[] {
  return compileSchema(schema, rootName, new IdentifierAllocator()).declarations;
}

describe("schema identifiers", () => {
  it("normalizes type names and allocates collisions", () => {
    const allocator = new IdentifierAllocator();
    assert.equal(typeIdentifier("weather-result"), "WeatherResult");
    assert.equal(typeIdentifier("123 result"), "Schema123Result");
    assert.equal(typeIdentifier("---"), "Schema");
    assert.equal(allocator.allocate("same-name"), "SameName");
    assert.equal(allocator.allocate("same name"), "SameName2");
  });

  it("normalizes value names, reserved words, numbers, and collisions", () => {
    const allocator = new ValueIdentifierAllocator();
    assert.equal(allocator.allocate("Get Weather"), "getWeather");
    assert.equal(allocator.allocate("class"), "toolClass");
    assert.equal(allocator.allocate("123"), "tool123");
    assert.equal(allocator.allocate("---"), "tool");
    assert.equal(allocator.allocate("get-weather"), "getWeather2");
  });
});

describe("schema compilation", () => {
  it("compiles primitives, nullable types, and type unions", () => {
    assert.deepEqual(compile({ nullable: true, type: "string" }), ["export type Example = string | null;"]);
    assert.deepEqual(compile({ type: ["string", "number", "integer", "boolean", "null"] }), [
      "export type Example = string | number | boolean | null;",
    ]);
    assert.deepEqual(compile({ type: "object" }), ["export type Example = Record<string, never>;"]);
    assert.deepEqual(compile({ type: "array" }), ["export type Example = readonly unknown[];"]);
  });

  it("compiles constants and enum JSON literals", () => {
    assert.deepEqual(
      compile({
        enum: [null, "ok", true, 2, ["x", false], { a: "first", z: 1 }],
      }),
      [
        'export type Example = null | "ok" | true | 2 | readonly ["x", false] | { readonly "a": "first"; readonly "z": 1 };',
      ],
    );
    assert.deepEqual(compile({ const: false }), ["export type Example = false;"]);
  });

  it("compiles unions, intersections, and boolean schemas", () => {
    assert.deepEqual(
      compile({
        allOf: [{ oneOf: [{ type: "string" }, { type: "number" }] }, { anyOf: [true, { type: "boolean" }] }],
      }),
      ["export type Example = string | number;"],
    );
    assert.deepEqual(compile({ allOf: [false, { type: "string" }] }), ["export type Example = never;"]);
    assert.deepEqual(compile({ anyOf: [] }), ["export type Example = never;"]);
  });

  it("compiles objects with required, optional, and index properties", () => {
    const [declaration] = compile({
      additionalProperties: { type: "boolean" },
      properties: {
        optional: { type: "number" },
        required: { type: "string" },
      },
      required: ["required"],
    });
    assert.match(declaration, /"optional"\?: number/u);
    assert.match(declaration, /"required": string/u);
    assert.match(declaration, /\[key: string\]: number \| string \| boolean \| undefined/u);
    assert.deepEqual(compile({ additionalProperties: true }), ["export type Example = Record<string, unknown>;"]);
    assert.deepEqual(compile({ additionalProperties: { type: "string" } }), [
      "export type Example = Record<string, string>;",
    ]);
  });

  it("compiles homogeneous arrays and parenthesizes compound elements", () => {
    assert.deepEqual(compile({ items: false }), ["export type Example = readonly never[];"]);
    assert.deepEqual(compile({ items: true }), ["export type Example = readonly unknown[];"]);
    assert.deepEqual(compile({ items: { oneOf: [{ type: "string" }, { type: "number" }] } }), [
      "export type Example = readonly (string | number)[];",
    ]);
  });

  it("compiles prefix and legacy tuple arrays", () => {
    assert.deepEqual(compile({ maxItems: 2, prefixItems: [{ type: "string" }, { type: "number" }] }), [
      "export type Example = readonly [string, number];",
    ]);
    assert.deepEqual(compile({ items: { type: "boolean" }, prefixItems: [{ type: "string" }] }), [
      "export type Example = readonly [string, ...boolean[]];",
    ]);
    assert.deepEqual(compile({ items: false, prefixItems: [{ type: "string" }] }), [
      "export type Example = readonly [string];",
    ]);
    assert.deepEqual(compile({ additionalItems: true, items: [{ type: "string" }] }), [
      "export type Example = readonly [string, ...unknown[]];",
    ]);
    assert.deepEqual(compile({ additionalItems: { type: "number" }, items: [{ type: "string" }] }), [
      "export type Example = readonly [string, ...number[]];",
    ]);
    assert.deepEqual(compile({ additionalItems: false, items: [{ type: "string" }] }), [
      "export type Example = readonly [string];",
    ]);
    assert.deepEqual(compile({ items: [{ type: "string" }], maxItems: 1 }), [
      "export type Example = readonly [string];",
    ]);
  });

  it("compiles local definitions and JSON pointer references", () => {
    const declarations = compile({
      $defs: {
        "a/b~c": { type: "string" },
        recursive: { $ref: "#" },
      },
      allOf: [
        { $ref: "#/$defs/a~1b~0c", nullable: true },
        { $ref: "#/$defs/a~1b~0c", description: "sibling", type: "string" },
      ],
    });
    assert.equal(declarations.length, 3);
    assert.match(declarations[0], /ExampleABC \| null/u);
    assert.match(declarations[0], /ExampleABC & string/u);
    assert.equal(declarations[1], "export type ExampleABC = string;");
    assert.equal(declarations[2], "export type ExampleRecursive = Example;");
  });

  it("keeps definitions globally collision-free", () => {
    const allocator = new IdentifierAllocator();
    allocator.allocate("Example Item");
    const compiled = compileSchema({ $defs: { item: true }, $ref: "#/$defs/item" }, "Example", allocator);
    assert.equal(compiled.rootName, "Example");
    assert.deepEqual(compiled.declarations, [
      "export type Example = ExampleItem2;",
      "export type ExampleItem2 = unknown;",
    ]);
  });
});

describe("schema validation", () => {
  it.each([
    [null, /Example must be a JSON Schema object/u],
    [{ type: [] }, /type must be a string or non-empty string array/u],
    [{ type: ["string", 1] }, /type must be a string or non-empty string array/u],
    [{ type: "date" }, /unsupported type "date"/u],
    [{ enum: [] }, /enum must be a non-empty array/u],
    [{ enum: "x" }, /enum must be a non-empty array/u],
    [{ const: Number.POSITIVE_INFINITY }, /non-finite number/u],
    [{ const: Symbol("invalid") }, /is not a JSON value/u],
    [{ oneOf: "x" }, /oneOf must be an array of JSON Schemas/u],
    [{ anyOf: [1] }, /anyOf\[0\] must be a JSON Schema/u],
    [{ properties: [] }, /properties must be a JSON Schema object/u],
    [{ properties: { bad: 1 } }, /properties.bad must be a JSON Schema/u],
    [{ properties: {}, required: "bad" }, /required must be an array of property names/u],
    [{ properties: {}, required: [1] }, /required must be an array of property names/u],
    [{ properties: {}, required: ["missing"] }, /references missing property "missing"/u],
    [{ additionalProperties: [] }, /additionalProperties must be a JSON Schema object/u],
    [{ prefixItems: "bad" }, /prefixItems must be an array/u],
    [{ items: [], prefixItems: [] }, /items must be a JSON Schema object/u],
    [{ additionalItems: [], items: [] }, /additionalItems must be a JSON Schema object/u],
    [{ additionalItems: false, items: { type: "string" } }, /uses additionalItems without/u],
    [{ $ref: 1 }, /\$ref must be a string/u],
    [{ $ref: "https://example.com/schema" }, /unsupported external or non-\$defs reference/u],
    [{ $ref: "#/$defs/missing" }, /references missing \$defs entry/u],
    [{ contains: { type: "string" } }, /unsupported JSON Schema keyword "contains"/u],
    [{ $defs: [] }, /\$defs must be a JSON Schema object/u],
    [{ $defs: { bad: 1 } }, /\$defs.bad must be a JSON Schema/u],
  ])("rejects invalid schema %#", (schema, pattern) => {
    assert.throws(() => compile(schema), pattern);
  });
});
