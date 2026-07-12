import { describe, expect, it } from "vitest";

import { hasDefaultExport } from "./validate-widget.js";

describe("hasDefaultExport", () => {
  it("detects export default", () => {
    expect(hasDefaultExport("export default function Widget() {}")).toBe(true);
    expect(hasDefaultExport("export default class Widget {}")).toBe(true);
    expect(hasDefaultExport("const Widget = () => null;\nexport default Widget;")).toBe(true);
  });

  it("detects export { Foo as default }", () => {
    expect(hasDefaultExport("export { Widget as default };")).toBe(true);
    expect(hasDefaultExport("export { Foo, Widget as default, Bar };")).toBe(true);
  });

  it("returns false for named-only exports", () => {
    expect(hasDefaultExport("export function Widget() {}")).toBe(false);
    expect(hasDefaultExport("export const Widget = () => null;")).toBe(false);
  });

  it("returns false when there is no export", () => {
    expect(hasDefaultExport("function Widget() {}")).toBe(false);
    expect(hasDefaultExport("")).toBe(false);
  });

  it("ignores default exports in line comments", () => {
    expect(hasDefaultExport("// export default function Widget() {}")).toBe(false);
    expect(hasDefaultExport("export function Widget() {}\n// export default Widget;")).toBe(false);
  });

  it("ignores default exports in block comments", () => {
    expect(hasDefaultExport("/* export default function Widget() {} */")).toBe(false);
    expect(
      hasDefaultExport("/*\nexport default function Widget() {}\n*/\nexport function Named() {}"),
    ).toBe(false);
  });

  it("still detects a real default export when commented decoys exist", () => {
    expect(
      hasDefaultExport("// export default Fake;\nexport default function Widget() {}"),
    ).toBe(true);
    expect(
      hasDefaultExport("/* export default Fake; */\nexport { Widget as default };"),
    ).toBe(true);
  });
});
