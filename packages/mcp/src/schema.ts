type JsonObject = Record<string, unknown>;
type JsonSchema = boolean | JsonObject;

const UNSUPPORTED_KEYWORDS = [
  "contains",
  "dependencies",
  "dependentSchemas",
  "definitions",
  "else",
  "if",
  "not",
  "patternProperties",
  "then",
  "unevaluatedItems",
  "unevaluatedProperties",
] as const;

const ANNOTATION_KEYWORDS = new Set([
  "$comment",
  "$defs",
  "$id",
  "$schema",
  "default",
  "deprecated",
  "description",
  "examples",
  "readOnly",
  "title",
  "writeOnly",
]);

const STRUCTURAL_KEYWORDS = new Set([
  "$ref",
  "additionalItems",
  "additionalProperties",
  "allOf",
  "anyOf",
  "const",
  "enum",
  "items",
  "nullable",
  "oneOf",
  "prefixItems",
  "properties",
  "required",
  "type",
]);

export class IdentifierAllocator {
  readonly #uses = new Map<string, number>();

  allocate(preferred: string): string {
    const safe = identifier(preferred);
    const count = (this.#uses.get(safe) ?? 0) + 1;
    this.#uses.set(safe, count);
    return count === 1 ? safe : `${safe}${count}`;
  }
}

export type CompiledSchema = {
  declarations: string[];
  rootName: string;
};

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function schemaObject(value: unknown, location: string): JsonObject {
  if (!isObject(value)) {
    throw new Error(`${location} must be a JSON Schema object`);
  }
  return value;
}

function schemaArray(value: unknown, location: string): JsonSchema[] {
  if (!Array.isArray(value)) {
    throw new Error(`${location} must be an array of JSON Schemas`);
  }
  return value.map((item, index) => {
    if (typeof item !== "boolean" && !isObject(item)) {
      throw new Error(`${location}[${index}] must be a JSON Schema`);
    }
    return item;
  });
}

function identifier(value: string): string {
  const words = value.match(/[\p{L}\p{N}]+/gu) ?? [];
  const joined = words
    .map((word) => `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`)
    .join("");
  const result = joined || "Schema";
  return /^\p{N}/u.test(result) ? `Schema${result}` : result;
}

export function typeIdentifier(value: string): string {
  return identifier(value);
}

function decodePointer(value: string): string {
  return decodeURIComponent(value).replaceAll("~1", "/").replaceAll("~0", "~");
}

function union(types: string[]): string {
  const unique = [...new Set(types)];
  if (unique.includes("unknown")) {
    return "unknown";
  }
  return unique.length === 0
    ? "never"
    : unique
        .map((type) => (hasTopLevelOperator(type, " & ") ? `(${type})` : type))
        .join(" | ");
}

function intersection(types: string[]): string {
  const unique = [...new Set(types.filter((type) => type !== "unknown"))];
  if (unique.includes("never")) {
    return "never";
  }
  if (unique.length <= 1) {
    return unique[0] ?? "unknown";
  }
  return unique.map((type) => parenthesize(type)).join(" & ");
}

function parenthesize(type: string): string {
  return hasTopLevelOperator(type, " | ") ? `(${type})` : type;
}

function arrayElement(type: string): string {
  return hasTopLevelOperator(type, " | ") || hasTopLevelOperator(type, " & ")
    ? `(${type})`
    : type;
}

function hasTopLevelOperator(type: string, operator: string): boolean {
  let depth = 0;
  let quote: string | undefined;
  for (let index = 0; index < type.length; index += 1) {
    const character = type[index]!;
    if (quote !== undefined) {
      if (character === "\\") {
        index += 1;
      } else if (character === quote) {
        quote = undefined;
      }
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
    } else if (character === "{" || character === "[" || character === "(") {
      depth += 1;
    } else if (character === "}" || character === "]" || character === ")") {
      depth -= 1;
    } else if (depth === 0 && type.startsWith(operator, index)) {
      return true;
    }
  }
  return false;
}

function indentType(type: string, spaces: number): string {
  return type.replaceAll("\n", `\n${" ".repeat(spaces)}`);
}

function literal(value: unknown, location: string): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`${location} contains a non-finite number`);
    }
    return String(value);
  }
  if (Array.isArray(value)) {
    return `readonly [${value
      .map((item, index) => literal(item, `${location}[${index}]`))
      .join(", ")}]`;
  }
  if (isObject(value)) {
    const properties = Object.keys(value)
      .sort()
      .map((key) => `readonly ${JSON.stringify(key)}: ${literal(value[key], `${location}.${key}`)}`);
    return `{ ${properties.join("; ")} }`;
  }
  throw new Error(`${location} is not a JSON value`);
}

function strip(schema: JsonObject, keys: Set<string>): JsonObject {
  return Object.fromEntries(Object.entries(schema).filter(([key]) => !keys.has(key)));
}

function hasStructuralKeywords(schema: JsonObject): boolean {
  return Object.keys(schema).some((key) => STRUCTURAL_KEYWORDS.has(key));
}

class SchemaCompiler {
  readonly #rootName: string;
  readonly #definitions: Map<string, JsonSchema>;
  readonly #definitionNames: Map<string, string>;

  constructor(
    rootName: string,
    schema: JsonObject,
    allocator: IdentifierAllocator,
  ) {
    this.#rootName = rootName;
    const definitionsValue = schema.$defs;
    if (definitionsValue === undefined) {
      this.#definitions = new Map();
    } else {
      const definitions = schemaObject(definitionsValue, "$defs");
      this.#definitions = new Map(
        Object.keys(definitions)
          .sort()
          .map((name) => {
            const value = definitions[name];
            if (typeof value !== "boolean" && !isObject(value)) {
              throw new Error(`$defs.${name} must be a JSON Schema`);
            }
            return [name, value] as const;
          }),
      );
    }
    this.#definitionNames = new Map(
      [...this.#definitions].map(([name]) => [
        name,
        allocator.allocate(`${rootName}${identifier(name)}`),
      ]),
    );
  }

  declarations(schema: JsonObject): string[] {
    const rootSchema = { ...schema };
    delete rootSchema.$defs;
    const declarations = [`export type ${this.#rootName} = ${this.compile(rootSchema, this.#rootName)};`];
    for (const [name, definition] of this.#definitions) {
      declarations.push(
        `export type ${this.#definitionNames.get(name)!} = ${this.compile(
          definition,
          `$defs.${name}`,
        )};`,
      );
    }
    return declarations;
  }

  compile(schema: JsonSchema, location: string): string {
    if (schema === true) {
      return "unknown";
    }
    if (schema === false) {
      return "never";
    }
    for (const keyword of UNSUPPORTED_KEYWORDS) {
      if (keyword in schema) {
        throw new Error(`${location} uses unsupported JSON Schema keyword ${JSON.stringify(keyword)}`);
      }
    }

    const parts: string[] = [];
    if (schema.$ref !== undefined) {
      parts.push(this.reference(schema.$ref, location));
      const rest = strip(schema, new Set(["$ref", ...ANNOTATION_KEYWORDS]));
      if (hasStructuralKeywords(rest)) {
        parts.push(this.compile(rest, location));
      }
      return this.nullable(intersection(parts), schema);
    }

    if (schema.const !== undefined) {
      parts.push(literal(schema.const, `${location}.const`));
    } else if (schema.enum !== undefined) {
      if (!Array.isArray(schema.enum) || schema.enum.length === 0) {
        throw new Error(`${location}.enum must be a non-empty array`);
      }
      parts.push(
        union(schema.enum.map((item, index) => literal(item, `${location}.enum[${index}]`))),
      );
    }

    for (const keyword of ["oneOf", "anyOf"] as const) {
      if (schema[keyword] !== undefined) {
        parts.push(
          union(
            schemaArray(schema[keyword], `${location}.${keyword}`).map((item, index) =>
              this.compile(item, `${location}.${keyword}[${index}]`),
            ),
          ),
        );
      }
    }
    if (schema.allOf !== undefined) {
      parts.push(
        intersection(
          schemaArray(schema.allOf, `${location}.allOf`).map((item, index) =>
            this.compile(item, `${location}.allOf[${index}]`),
          ),
        ),
      );
    }

    const typeSchema = strip(
      schema,
      new Set(["allOf", "anyOf", "const", "enum", "nullable", "oneOf", ...ANNOTATION_KEYWORDS]),
    );
    if (typeSchema.type !== undefined) {
      parts.push(this.explicitType(typeSchema, location));
    } else if (
      typeSchema.properties !== undefined ||
      typeSchema.additionalProperties !== undefined ||
      typeSchema.required !== undefined
    ) {
      parts.push(this.object(typeSchema, location));
    } else if (typeSchema.items !== undefined || typeSchema.prefixItems !== undefined) {
      parts.push(this.array(typeSchema, location));
    }

    const result = intersection(parts);
    return this.nullable(result, schema);
  }

  explicitType(schema: JsonObject, location: string): string {
    const value = schema.type;
    const types = Array.isArray(value) ? value : [value];
    if (types.length === 0 || types.some((type) => typeof type !== "string")) {
      throw new Error(`${location}.type must be a string or non-empty string array`);
    }
    return union(types.map((type) => this.singleType(type as string, schema, location)));
  }

  singleType(type: string, schema: JsonObject, location: string): string {
    switch (type) {
      case "array":
        return this.array(schema, location);
      case "boolean":
        return "boolean";
      case "integer":
      case "number":
        return "number";
      case "null":
        return "null";
      case "object":
        return this.object(schema, location);
      case "string":
        return "string";
      default:
        throw new Error(`${location}.type contains unsupported type ${JSON.stringify(type)}`);
    }
  }

  object(schema: JsonObject, location: string): string {
    const propertiesValue = schema.properties;
    const properties =
      propertiesValue === undefined ? {} : schemaObject(propertiesValue, `${location}.properties`);
    const requiredValue = schema.required;
    if (
      requiredValue !== undefined &&
      (!Array.isArray(requiredValue) || requiredValue.some((item) => typeof item !== "string"))
    ) {
      throw new Error(`${location}.required must be an array of property names`);
    }
    const required = new Set((requiredValue as string[] | undefined) ?? []);
    for (const name of required) {
      if (!(name in properties)) {
        throw new Error(`${location}.required references missing property ${JSON.stringify(name)}`);
      }
    }

    const propertyTypes: string[] = [];
    let hasOptional = false;
    const members = Object.keys(properties)
      .sort()
      .map((name) => {
        const property = properties[name];
        if (typeof property !== "boolean" && !isObject(property)) {
          throw new Error(`${location}.properties.${name} must be a JSON Schema`);
        }
        const optional = !required.has(name);
        if (optional) {
          hasOptional = true;
        }
        const propertyType = this.compile(property, `${location}.properties.${name}`);
        propertyTypes.push(propertyType);
        return `  ${JSON.stringify(name)}${optional ? "?" : ""}: ${indentType(propertyType, 2)};`;
      });
    const objectType =
      members.length === 0 ? "Record<string, never>" : `{\n${members.join("\n")}\n}`;

    const additional = schema.additionalProperties;
    if (additional === undefined || additional === false) {
      return objectType;
    }
    const valueType =
      additional === true
        ? "unknown"
        : this.compile(
            schemaObject(additional, `${location}.additionalProperties`),
            `${location}.additionalProperties`,
          );
    if (members.length === 0) {
      return `Record<string, ${valueType}>`;
    }
    // Index signature must accept every named field type (and undefined if any are optional).
    const indexTypes = [...propertyTypes, valueType];
    if (hasOptional) {
      indexTypes.push("undefined");
    }
    const indexType = union(indexTypes);
    return `{\n${members.join("\n")}\n  [key: string]: ${indentType(indexType, 2)};\n}`;
  }

  array(schema: JsonObject, location: string): string {
    if (schema.prefixItems !== undefined) {
      const prefixItems = schemaArray(schema.prefixItems, `${location}.prefixItems`);
      const elements = prefixItems.map((item, index) =>
        this.compile(item, `${location}.prefixItems[${index}]`),
      );
      const rest = schema.items;
      const fixedLength = schema.maxItems === prefixItems.length;
      if (!fixedLength && rest !== false) {
        const restType =
          rest === undefined || rest === true
            ? "unknown"
            : this.compile(schemaObject(rest, `${location}.items`), `${location}.items`);
        elements.push(`...${arrayElement(restType)}[]`);
      }
      return `readonly [${elements.join(", ")}]`;
    }
    const items = schema.items;
    if (Array.isArray(items)) {
      const elements = schemaArray(items, `${location}.items`).map((item, index) =>
        this.compile(item, `${location}.items[${index}]`),
      );
      const additional = schema.additionalItems;
      const fixedLength = schema.maxItems === elements.length;
      if (!fixedLength && additional !== false) {
        const restType =
          additional === undefined || additional === true
            ? "unknown"
            : this.compile(
                schemaObject(additional, `${location}.additionalItems`),
                `${location}.additionalItems`,
              );
        elements.push(`...${arrayElement(restType)}[]`);
      }
      return `readonly [${elements.join(", ")}]`;
    }
    if (schema.additionalItems !== undefined) {
      throw new Error(
        `${location} uses additionalItems without a tuple-form items schema`,
      );
    }
    if (items === undefined || items === true) {
      return "readonly unknown[]";
    }
    if (items === false) {
      return "readonly never[]";
    }
    return `readonly ${arrayElement(
      this.compile(schemaObject(items, `${location}.items`), `${location}.items`),
    )}[]`;
  }

  reference(value: unknown, location: string): string {
    if (typeof value !== "string") {
      throw new Error(`${location}.$ref must be a string`);
    }
    if (value === "#") {
      return this.#rootName;
    }
    const prefix = "#/$defs/";
    if (!value.startsWith(prefix)) {
      throw new Error(`${location} contains unsupported external or non-$defs reference ${JSON.stringify(value)}`);
    }
    const name = decodePointer(value.slice(prefix.length));
    const reference = this.#definitionNames.get(name);
    if (reference === undefined) {
      throw new Error(`${location} references missing $defs entry ${JSON.stringify(name)}`);
    }
    return reference;
  }

  nullable(type: string, schema: JsonObject): string {
    return schema.nullable === true ? union([type, "null"]) : type;
  }
}

export function compileSchema(
  schema: unknown,
  rootName: string,
  allocator: IdentifierAllocator,
): CompiledSchema {
  const root = schemaObject(schema, rootName);
  const compiler = new SchemaCompiler(rootName, root, allocator);
  return {
    declarations: compiler.declarations(root),
    rootName,
  };
}
