import { defineConfig } from "tsdown";

export default defineConfig({
  attw: {
    level: "error",
    profile: "esm-only",
  },
  clean: true,
  deps: {
    alwaysBundle: [/^@modelcontextprotocol\/sdk(?:\/|$)/, /^zod(?:\/|$)/, /^open(?:\/|$)/],
    onlyBundle: false,
  },
  dts: true,
  entry: {
    cli: "src/cli.ts",
    codegen: "src/codegen.ts",
    index: "src/index.tsx",
    internal: "src/internal.ts",
  },
  exports: {
    bin: {
      "belgie-mcp": "src/cli.ts",
    },
    exclude: ["cli"],
    inlinedDependencies: false,
    legacy: true,
    packageJson: true,
  },
  fixedExtension: false,
  format: "esm",
  platform: "node",
  publint: {
    level: "error",
  },
  sourcemap: true,
});
