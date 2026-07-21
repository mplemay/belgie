import assert from "node:assert/strict";

afterEach(() => {
  vi.doUnmock("../src/scan-widgets.js");
  vi.resetModules();
});

test("reports non-Error widget rescan failures", async () => {
  vi.resetModules();
  vi.doMock(import("../src/scan-widgets.js"), () => ({
    assertNoInvalidWidgets: vi.fn(),
    assertUniqueWidgetNames: vi.fn(),
    scanWidgetsSync: () => {
      throw "raw rescan failure";
    },
  }));
  const { belgie } = await import("../src/vite.ts");
  const errors: string[] = [];
  const server = {
    config: {
      base: "/",
      logger: {
        error(message: string) {
          errors.push(message);
        },
        info() {},
        warn() {},
      },
      plugins: [],
      root: "",
    },
    middlewares: { use() {} },
    watcher: { add() {}, on() {} },
  };
  belgie().configureServer?.(server);
  assert.deepEqual(errors, ["[belgie] widget rescan failed: raw rescan failure"]);
});
