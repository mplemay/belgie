import assert from "node:assert/strict";

import { afterEach, test, vi } from "vitest";

afterEach(() => {
  vi.doUnmock("../src/scan-widgets.js");
  vi.resetModules();
});

test("reports non-Error widget rescan failures", async () => {
  vi.resetModules();
  vi.doMock("../src/scan-widgets.js", () => ({
    scanWidgetsSync: () => {
      throw "raw rescan failure";
    },
    assertNoInvalidWidgets: vi.fn(),
    assertUniqueWidgetNames: vi.fn(),
  }));
  const { belgie } = await import("../src/vite.ts");
  const errors: string[] = [];
  const server = {
    config: {
      root: "",
      base: "/",
      plugins: [],
      logger: {
        warn() {},
        info() {},
        error(message: string) {
          errors.push(message);
        },
      },
    },
    watcher: { add() {}, on() {} },
    middlewares: { use() {} },
  };
  belgie().configureServer?.(server as never);
  assert.deepEqual(errors, ["[belgie] widget rescan failed: raw rescan failure"]);
});
