import { defineConfig } from "tsdown";

const shared = {
  fixedExtension: false,
  format: "esm" as const,
  platform: "node" as const,
  sourcemap: true,
};

export default defineConfig([
  {
    ...shared,
    attw: {
      level: "error",
      profile: "esm-only",
    },
    clean: true,
    dts: true,
    entry: {
      codegen: "src/codegen.ts",
      index: "src/index.tsx",
      internal: "src/internal.ts",
      vite: "src/vite.ts",
    },
    exports: {
      exclude: ["cli"],
      inlinedDependencies: false,
      legacy: true,
      packageJson: true,
    },
    publint: {
      level: "error",
    },
  },
  {
    ...shared,
    clean: false,
    dts: true,
    entry: {
      cli: "src/cli.ts",
    },
    deps: {
      alwaysBundle: [/^@modelcontextprotocol\/sdk(?:\/|$)/, /^zod(?:\/|$)/, /^open(?:\/|$)/],
      onlyBundle: false,
    },
  },
]);
