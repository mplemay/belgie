import { describe, expect, test } from "vitest";

import { hasDefaultExport } from "../src/validate-widget.ts";

describe("widget source validation", () => {
  test.each([
    "export default function Widget() {}",
    "const Widget = () => null; export { Widget as default };",
    "const Widget = () => null; export { Widget as default, Widget };",
  ])("accepts a real default export", (source) => {
    expect(hasDefaultExport(source)).toBe(true);
  });

  test.each([
    "export const Widget = () => null;",
    "// export default function Fake() {}\nexport const Widget = true;",
    "/* export { Widget as default } */\nexport const Widget = true;",
  ])("rejects missing and commented default exports", (source) => {
    expect(hasDefaultExport(source)).toBe(false);
  });
});
