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
    index: "src/index.ts",
  },
  exports: {
    bin: {
      "@belgie/vite": "src/cli.ts",
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
