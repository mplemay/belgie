import { types as utilTypes } from "node:util";

export type JsonPrimitive = boolean | null | number | string;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

const MAX_VALUE_DEPTH = 64;

export function serializeArguments(arguments_: readonly unknown[]): string {
  const seen = new Set<object>();
  for (const [index, argument] of arguments_.entries()) {
    validateJsonValue(argument, `$[${index}]`, 0, seen);
  }
  return JSON.stringify(arguments_);
}

function validateJsonValue(value: unknown, path: string, depth: number, seen: Set<object>): void {
  if (depth > MAX_VALUE_DEPTH) {
    throw new TypeError(`JSON value exceeds the maximum depth of ${MAX_VALUE_DEPTH} at ${path}`);
  }
  if (validatePrimitive(value, path)) {
    return;
  }
  const container = value as object;
  if (utilTypes.isProxy(container)) {
    throw new TypeError(`Proxy objects are not supported at ${path}`);
  }
  if (seen.has(container)) {
    throw new TypeError(`Cannot pass a data structure cycle as JSON at ${path}`);
  }
  seen.add(container);
  try {
    if (Array.isArray(container)) {
      if (Object.getPrototypeOf(container) !== Array.prototype) {
        throw new TypeError(`Only plain arrays are supported at ${path}`);
      }
      for (let index = 0; index < container.length; index += 1) {
        if (!Object.hasOwn(container, index)) {
          throw new TypeError(`Sparse arrays are not supported at ${path}[${index}]`);
        }
        validateJsonValue(container[index], `${path}[${index}]`, depth + 1, seen);
      }
      return;
    }
    const prototype = Object.getPrototypeOf(container);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new TypeError(`Only plain objects are supported at ${path}`);
    }
    for (const key of Reflect.ownKeys(container)) {
      if (typeof key !== "string") {
        throw new TypeError(`JSON object keys must be strings at ${path}`);
      }
      const descriptor = Object.getOwnPropertyDescriptor(container, key);
      if (!descriptor?.enumerable || !("value" in descriptor)) {
        throw new TypeError(`JSON object properties must be enumerable data properties at ${objectPath(path, key)}`);
      }
      validateJsonValue(descriptor.value, objectPath(path, key), depth + 1, seen);
    }
  } finally {
    seen.delete(container);
  }
}

function validatePrimitive(value: unknown, path: string): boolean {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return true;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError(`Number at ${path} must be finite`);
    }
    return true;
  }
  if (typeof value !== "object") {
    throw new TypeError(`Only JSON values can cross the sandbox boundary at ${path}; got ${typeof value}`);
  }
  return false;
}

function objectPath(path: string, key: string): string {
  return /^[$A-Z_a-z][$\w]*$/.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`;
}
