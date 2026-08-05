import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      enabled: true,
      exclude: ["src/cli.ts"],
      include: ["src/**/*.{ts,tsx}"],
      provider: "v8",
      reporter: ["text", "json-summary"],
      thresholds: {
        branches: 85,
        functions: 95,
        lines: 95,
        perFile: true,
        statements: 95,
      },
    },
    environment: "node",
    fileParallelism: false,
    globals: true,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
