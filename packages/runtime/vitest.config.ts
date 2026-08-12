import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    fileParallelism: false,
    globals: true,
    include: ["__tests__/**/*.test.ts"],
    testTimeout: 10_000,
  },
});
