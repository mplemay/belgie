import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

test("publishes the expected ESM export map and declarations", async () => {
  const packageJson = JSON.parse(readFileSync("package.json", "utf8"));
  assert.deepEqual(packageJson.exports, {
    ".": "./dist/index.js",
    "./codegen": "./dist/codegen.js",
    "./internal": "./dist/internal.js",
    "./package.json": "./package.json",
    "./vite": "./dist/vite.js",
  });
  assert.equal(packageJson.bin["belgie-mcp"], "./dist/cli.js");
  assert.equal(packageJson.main, "./dist/index.js");
  assert.equal(packageJson.module, "./dist/index.js");
  assert.equal(packageJson.types, "./dist/index.d.ts");
  assert.equal(packageJson.publishConfig.access, "public");

  for (const entry of ["index", "codegen", "internal", "vite", "cli"]) {
    assert.equal(existsSync(`dist/${entry}.js`), true);
    assert.equal(existsSync(`dist/${entry}.d.ts`), true);
  }
  const mcp = await import("@belgie/mcp");
  assert.equal(typeof mcp.Widget, "function");
  assert.equal(typeof mcp.useDisplayMode, "function");
  assert.equal(typeof mcp.useLayout, "function");
  assert.equal(typeof mcp.useLocale, "function");
  assert.equal(typeof mcp.useTheme, "function");
  assert.equal(typeof mcp.useUserAgent, "function");
  assert.equal(typeof (await import("@belgie/mcp/codegen")).generateToolTypes, "function");
  assert.equal(typeof (await import("@belgie/mcp/internal")).createGeneratedTool, "function");
  assert.equal(typeof (await import("@belgie/mcp/vite")).belgie, "function");
});

test("resolves declarations from every built package subpath", () => {
  const directory = mkdtempSync(join(process.cwd(), ".package-types-"));
  try {
    const fixture = join(directory, "fixture.tsx");
    writeFileSync(
      fixture,
      [
        'import { Widget, type ToolCallResult } from "@belgie/mcp";',
        'import { generateToolTypes } from "@belgie/mcp/codegen";',
        'import { createGeneratedRawTool } from "@belgie/mcp/internal";',
        'import { belgie } from "@belgie/mcp/vite";',
        'const result: ToolCallResult<string> = { result: "ok", error: undefined };',
        'void <Widget metadata={{ name: "fixture", version: "1.0.0" }}>{result.result}</Widget>;',
        "void generateToolTypes; void createGeneratedRawTool; void belgie;",
      ].join("\n"),
    );
    const result = spawnSync(
      process.execPath,
      [
        "node_modules/typescript/bin/tsc",
        "--ignoreConfig",
        "--noEmit",
        "--strict",
        "--skipLibCheck",
        "--target",
        "ESNext",
        "--module",
        "ESNext",
        "--moduleResolution",
        "Bundler",
        "--jsx",
        "react-jsx",
        fixture,
      ],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});

test("npm pack dry run contains only publishable package files", () => {
  const npmCli = process.env.npm_execpath;
  assert.ok(npmCli, "expected npm_execpath when tests are run via npm");
  const output = execFileSync(process.execPath, [npmCli, "pack", "--dry-run", "--json", "--ignore-scripts"], {
    encoding: "utf8",
  });
  const result = JSON.parse(output)[0];
  const files = result.files.map((file: { path: string }) => file.path);
  assert.ok(files.includes("README.md"));
  assert.ok(files.includes("package.json"));
  assert.ok(files.includes("dist/index.js"));
  assert.ok(files.includes("dist/index.d.ts"));
  assert.ok(files.includes("dist/cli.js"));
  assert.equal(
    files.some((file: string) => file.startsWith("src/")),
    false,
  );
  assert.equal(
    files.some((file: string) => file.startsWith("tests/")),
    false,
  );
  assert.equal(
    files.some((file: string) => file.startsWith("coverage/")),
    false,
  );
  assert.equal(
    files.some((file: string) => file.startsWith("types/")),
    false,
  );
});

test.skipIf(process.platform === "win32")("executes the packaged CLI through an npm-style symlink", () => {
  const directory = mkdtempSync(join(process.cwd(), ".package-bin-"));
  try {
    const executable = join(directory, "belgie-mcp");
    symlinkSync(join(process.cwd(), "dist", "cli.js"), executable);
    const result = spawnSync(process.execPath, [executable], { encoding: "utf8" });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Usage:\s+belgie-mcp generate/u);
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});
