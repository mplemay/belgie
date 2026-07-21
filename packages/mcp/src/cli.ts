#!/usr/bin/env node

import { realpathSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { generateToolTypes } from "./codegen";

const USAGE = `Usage:
  belgie-mcp generate <url> --output <file> [options]

Options:
  --check                    Fail when the output file is missing or stale
  --header NAME:VALUE        Add an introspection header (repeatable)
  --header-env NAME=ENV_VAR  Read a header value from the environment (repeatable)
  --no-oauth                 Disable automatic OAuth discovery and PKCE
  --no-open                  Print the OAuth URL instead of opening a browser
`;

export function values(value: string | string[] | undefined): string[] {
  if (value === undefined) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

export function parseHeader(value: string): [string, string] {
  const separator = value.indexOf(":");
  if (separator <= 0) {
    throw new Error(`Invalid --header ${JSON.stringify(value)}; expected NAME:VALUE`);
  }
  const name = value.slice(0, separator).trim();
  const headerValue = value.slice(separator + 1).trim();
  if (name.length === 0 || !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/u.test(name)) {
    throw new Error(`Invalid header name ${JSON.stringify(name)}`);
  }
  return [name, headerValue];
}

export function parseEnvironmentHeader(value: string): [string, string] {
  const separator = value.indexOf("=");
  if (separator <= 0 || separator === value.length - 1) {
    throw new Error(`Invalid --header-env ${JSON.stringify(value)}; expected NAME=ENV_VAR`);
  }
  const name = value.slice(0, separator).trim();
  const environmentName = value.slice(separator + 1).trim();
  if (name.length === 0 || !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/u.test(name)) {
    throw new Error(`Invalid header name ${JSON.stringify(name)}`);
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/u.test(environmentName)) {
    throw new Error(`Invalid environment variable name ${JSON.stringify(environmentName)}`);
  }
  const headerValue = process.env[environmentName];
  if (headerValue === undefined) {
    throw new Error(`Environment variable ${environmentName} is not set`);
  }
  return [name, headerValue];
}

export async function runCli(args: string[] = process.argv.slice(2)): Promise<void> {
  const { positionals, values: options } = parseArgs({
    allowPositionals: true,
    args,
    options: {
      check: { default: false, type: "boolean" },
      header: { multiple: true, type: "string" },
      "header-env": { multiple: true, type: "string" },
      "no-oauth": { default: false, type: "boolean" },
      "no-open": { default: false, type: "boolean" },
      output: { short: "o", type: "string" },
    },
    strict: true,
  });

  if (positionals[0] !== "generate" || positionals.length !== 2) {
    throw new Error(USAGE);
  }
  if (options.output === undefined) {
    throw new Error(`--output is required\n\n${USAGE}`);
  }

  const headers = Object.fromEntries([
    ...values(options.header).map(parseHeader),
    ...values(options["header-env"]).map(parseEnvironmentHeader),
  ]);
  const output = resolve(options.output);
  const generated = await generateToolTypes({
    headers,
    oauth: !options["no-oauth"],
    openBrowser: !options["no-open"],
    url: positionals[1],
  });

  if (options.check) {
    let current: string | undefined;
    try {
      current = await readFile(output, "utf8");
    } catch (error: unknown) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) {
        throw error;
      }
    }
    if (current !== generated) {
      throw new Error(`Generated MCP tool types are stale or missing: ${output}`);
    }
    process.stdout.write(`MCP tool types are current: ${output}\n`);
    return;
  }

  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, generated, "utf8");
  process.stdout.write(`Generated MCP tool types: ${output}\n`);
}

export function isDirectExecution(moduleUrl: string, executable: string | undefined): boolean {
  if (executable === undefined) {
    return false;
  }
  const executionPath = (value: string) => {
    try {
      return realpathSync(value);
    } catch {
      return resolve(value);
    }
  };
  return executionPath(executable) === executionPath(fileURLToPath(moduleUrl));
}

export function reportCliError(cause: unknown): void {
  const message = cause instanceof Error ? cause.message : String(cause);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

if (isDirectExecution(import.meta.url, process.argv[1])) {
  runCli().catch(reportCliError);
}
