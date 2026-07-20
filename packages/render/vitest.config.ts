import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      enabled: true,
      include: ["src/**/*.{ts,tsx}"],
      provider: "v8",
      reporter: ["text", "json-summary"],
      thresholds: {
        branches: 90,
        functions: 95,
        lines: 95,
        perFile: true,
        statements: 95,
      },
    },
    environment: "node",
    fileParallelism: false,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
