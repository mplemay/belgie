import { defineConfig } from "tsdown";

export default defineConfig({
  attw: {
    level: "error",
    profile: "esm-only",
  },
  clean: true,
  dts: true,
  entry: {
    cli: "src/cli.ts",
    codegen: "src/codegen.ts",
    index: "src/index.tsx",
    internal: "src/internal.ts",
    vite: "src/vite.ts",
  },
  exports: {
    bin: {
      "belgie-mcp": "src/cli.ts",
    },
    exclude: ["cli"],
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
