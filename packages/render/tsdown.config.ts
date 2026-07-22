import { defineConfig } from "tsdown";

export default defineConfig({
  attw: {
    level: "error",
    profile: "esm-only",
  },
  clean: true,
  dts: true,
  entry: {
    index: "src/index.ts",
  },
  exports: {
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
