#!/usr/bin/env node
import { mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Must load before vite so rolldown's requireNative libc probe hits the sanitized report.
import "./process-report.js";
import { buildWidgetFile, loadVitePlugins } from "./build.js";

function printUsage(): never {
  console.error("Usage: @belgie/vite --widget <path.tsx> [--out <path.html>] [--plugins <spec> ...]");
  process.exit(1);
}

function parseArgs(argv: string[]): { out?: string; plugins: string[]; widget?: string } {
  let widget: string | undefined;
  let out: string | undefined;
  const plugins: string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--widget") {
      widget = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--out") {
      out = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--plugins") {
      const value = argv[index + 1];
      if (value === undefined) {
        printUsage();
      }
      plugins.push(value);
      index += 1;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      printUsage();
    }
    console.error(`@belgie/vite: unknown argument ${arg}`);
    printUsage();
  }
  const result: { out?: string; plugins: string[]; widget?: string } = { plugins };
  if (widget !== undefined) {
    result.widget = widget;
  }
  if (out !== undefined) {
    result.out = out;
  }
  return result;
}

async function main(): Promise<void> {
  const { out, plugins: pluginSpecs, widget } = parseArgs(process.argv.slice(2));
  if (widget === undefined) {
    printUsage();
  }
  const plugins = await loadVitePlugins(pluginSpecs);
  const html = await buildWidgetFile(resolve(widget), plugins);
  if (out === undefined) {
    process.stdout.write(html);
    return;
  }
  const outPath = resolve(out);
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, html, "utf8");
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
  main().catch(reportCliError);
}
