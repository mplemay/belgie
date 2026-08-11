import { BelgieModuleError } from "./errors.ts";

export function validateScriptSource(source: string): void {
  const code = maskCommentsAndStrings(source);
  if (/\bimport\s*(?!\.)/.test(code) || /\bexport\b[^;]*\bfrom\b/.test(code)) {
    throw new BelgieModuleError("Static and dynamic imports are disabled in @belgie/runtime", "imports_disabled");
  }
  if (
    /<([A-Z_a-z][\w.-]*)\b[^>]*>[\s\S]*<\/\1\s*>/.test(code) ||
    /<[A-Z_a-z][\w.-]*\b[^>]*\/>/.test(code) ||
    /<>[\s\S]*<\/>/.test(code)
  ) {
    throw new BelgieModuleError("Script must be JavaScript or TypeScript; TSX is not supported", "tsx_not_supported");
  }
}

function maskCommentsAndStrings(source: string): string {
  const output = Array.from({ length: source.length }, (_, index) => source[index] ?? "");
  let index = 0;
  while (index < source.length) {
    const character = source[index];
    const next = source[index + 1];
    if (character === "/" && next === "/") {
      index = maskUntil(source, output, index, "\n");
      continue;
    }
    if (character === "/" && next === "*") {
      index = maskUntil(source, output, index, "*/");
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      index = maskQuoted(source, output, index, character);
      continue;
    }
    index += 1;
  }
  return output.join("");
}

function maskUntil(source: string, output: string[], start: number, terminator: string): number {
  const end = source.indexOf(terminator, start + terminator.length);
  const stop = end === -1 ? source.length : end + terminator.length;
  for (let index = start; index < stop; index += 1) {
    if (source[index] !== "\n") {
      output[index] = " ";
    }
  }
  return stop;
}

function maskQuoted(source: string, output: string[], start: number, quote: string): number {
  let index = start;
  while (index < source.length) {
    if (source[index] !== "\n") {
      output[index] = " ";
    }
    if (index > start && source[index] === quote && source[index - 1] !== "\\") {
      return index + 1;
    }
    index += 1;
  }
  return index;
}
