import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("../src/codegen.ts", () => ({
  generateToolTypes: vi.fn(async () => "generated\n"),
}));

import { generateToolTypes } from "../src/codegen.ts";
import {
  isDirectExecution,
  parseEnvironmentHeader,
  parseHeader,
  reportCliError,
  runCli,
  values,
} from "../src/cli.ts";

const temporaryDirectories: string[] = [];
const originalExitCode = process.exitCode;

beforeEach(() => {
  vi.mocked(generateToolTypes).mockClear();
  vi.mocked(generateToolTypes).mockResolvedValue("generated\n");
  process.exitCode = originalExitCode;
});

afterEach(async () => {
  vi.restoreAllMocks();
  delete process.env.BELGIE_TEST_TOKEN;
  process.exitCode = originalExitCode;
  const { rm } = await import("node:fs/promises");
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { force: true, recursive: true }),
    ),
  );
});

async function temporaryOutput(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "belgie-mcp-cli-"));
  temporaryDirectories.push(directory);
  return join(directory, "generated", "tools.ts");
}

describe("CLI parsing", () => {
  test("normalizes repeated values", () => {
    expect(values(undefined)).toEqual([]);
    expect(values("one")).toEqual(["one"]);
    expect(values(["one", "two"])).toEqual(["one", "two"]);
  });

  test("parses direct and environment headers", () => {
    process.env.BELGIE_TEST_TOKEN = "secret";
    expect(parseHeader(" Authorization : Bearer token ")).toEqual([
      "Authorization",
      "Bearer token",
    ]);
    expect(parseEnvironmentHeader("X-Token=BELGIE_TEST_TOKEN")).toEqual([
      "X-Token",
      "secret",
    ]);
  });

  test.each([
    [() => parseHeader("missing"), /expected NAME:VALUE/u],
    [() => parseHeader(": value"), /expected NAME:VALUE/u],
    [() => parseHeader("bad name:value"), /Invalid header name/u],
    [() => parseEnvironmentHeader("missing"), /expected NAME=ENV_VAR/u],
    [() => parseEnvironmentHeader("X-Token="), /expected NAME=ENV_VAR/u],
    [() => parseEnvironmentHeader("bad name=TOKEN"), /Invalid header name/u],
    [() => parseEnvironmentHeader("X-Token=bad-name"), /Invalid environment variable/u],
    [() => parseEnvironmentHeader("X-Token=MISSING_TOKEN"), /is not set/u],
  ])("rejects malformed header configuration", (operation, message) => {
    expect(operation).toThrow(message);
  });
});

describe("CLI execution", () => {
  test("writes generated output and forwards all options", async () => {
    const output = await temporaryOutput();
    process.env.BELGIE_TEST_TOKEN = "environment-secret";
    const stdout = vi.spyOn(process.stdout, "write").mockReturnValue(true);

    await runCli([
      "generate",
      "https://example.com/mcp",
      "--output",
      output,
      "--header",
      "Authorization:Bearer direct",
      "--header-env",
      "X-Token=BELGIE_TEST_TOKEN",
      "--no-oauth",
      "--no-open",
    ]);

    expect(await readFile(output, "utf8")).toBe("generated\n");
    expect(generateToolTypes).toHaveBeenCalledWith({
      headers: {
        Authorization: "Bearer direct",
        "X-Token": "environment-secret",
      },
      oauth: false,
      openBrowser: false,
      url: "https://example.com/mcp",
    });
    expect(stdout).toHaveBeenCalledWith(
      `Generated MCP tool types: ${resolve(output)}\n`,
    );
  });

  test("checks current, stale, and missing generated output", async () => {
    const output = await temporaryOutput();
    const stdout = vi.spyOn(process.stdout, "write").mockReturnValue(true);

    await expect(
      runCli([
        "generate",
        "https://example.com/mcp",
        "--output",
        output,
        "--check",
      ]),
    ).rejects.toThrow(/stale or missing/u);

    await mkdir(resolve(output, ".."), { recursive: true });
    await writeFile(output, "stale\n");
    await expect(
      runCli([
        "generate",
        "https://example.com/mcp",
        "--output",
        output,
        "--check",
      ]),
    ).rejects.toThrow(/stale or missing/u);

    await writeFile(output, "generated\n");
    await runCli([
      "generate",
      "https://example.com/mcp",
      "--output",
      output,
      "--check",
    ]);
    expect(stdout).toHaveBeenCalledWith(
      `MCP tool types are current: ${resolve(output)}\n`,
    );
  });

  test.each([
    [[], /Usage:/u],
    [["generate", "https://example.com/mcp"], /--output is required/u],
    [["other", "https://example.com/mcp", "--output", "tools.ts"], /Usage:/u],
  ])("rejects invalid command shapes", async (args, message) => {
    await expect(runCli(args)).rejects.toThrow(message);
  });

  test("detects direct execution and reports errors", () => {
    const modulePath = resolve(tmpdir(), "belgie-cli.js");
    const moduleUrl = pathToFileURL(modulePath).href;
    expect(isDirectExecution(moduleUrl, modulePath)).toBe(true);
    expect(isDirectExecution(moduleUrl, undefined)).toBe(false);
    expect(isDirectExecution(moduleUrl, `${modulePath}.other`)).toBe(false);
    expect(isDirectExecution(import.meta.url, import.meta.filename)).toBe(true);

    const stderr = vi.spyOn(process.stderr, "write").mockReturnValue(true);
    reportCliError(new Error("failed"));
    reportCliError("string failure");
    expect(stderr).toHaveBeenNthCalledWith(1, "failed\n");
    expect(stderr).toHaveBeenNthCalledWith(2, "string failure\n");
    expect(process.exitCode).toBe(1);
  });
});
