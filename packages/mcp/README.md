# `@belgie/mcp`

`@belgie/mcp` provides the browser-side pieces of a Belgie MCP App: a connected React widget,
typed MCP tool callers, host-context hooks, host actions, and modal support.

For the full guide, see the [package documentation](https://mplemay.github.io/belgie/packages/mcp/).
The [MCP Apps guide](https://mplemay.github.io/belgie/mcp-apps/) covers Python registration and
Belgie project setup. Use [`@belgie/vite`](https://mplemay.github.io/belgie/packages/vite/) for the
`belgie()` Vite plugin that discovers and builds widgets.

## Installation

```sh
npm install @belgie/mcp @modelcontextprotocol/ext-apps
npm install --save-dev vite @belgie/vite
```

The package is ESM-only and requires Node.js 22 or newer for its development and CLI workflows.

## Package exports

- `@belgie/mcp` exports `Widget`, `mountWidget`, tool-result and host-context hooks, host actions,
  modal helpers, and MCP tool errors.
- `@belgie/mcp/codegen` exports `generateToolTypes()` for programmatic MCP caller generation.
- `@belgie/mcp/internal` contains the runtime factories used by generated callers.
- `@belgie/mcp/package.json` exposes package metadata.

## Build a widget

Widgets are discovered at `<srcDir>/<name>/widget.tsx` and must have a default export:

```tsx
import { Widget } from "@belgie/mcp";

export default function Weather() {
  return (
    <Widget metadata={{ name: "Weather", version: "1.0.0" }}>
      <main>Ready</main>
    </Widget>
  );
}
```

Configure `@belgie/vite` in a normal Vite configuration:

```ts
import { belgie } from "@belgie/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Development serves `/widgets/<name>/index.html`. Inline production builds emit self-contained
`dist/widgets/<name>/index.html` files. See the `@belgie/vite` docs for shared bundle mode and CLI
one-shot builds.

## Generate typed tool clients

```sh
npx belgie-mcp generate <mcp-url> --output ./src/generated/tools.ts
```
