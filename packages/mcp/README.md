# `@belgie/mcp`

`@belgie/mcp` provides the browser-side pieces of a Belgie MCP App: a connected React widget,
typed MCP tool callers, host-context hooks, host actions, modal support, and a Vite plugin.

For the full guide, see the [package documentation](https://mplemay.github.io/belgie/packages/mcp/).
The [MCP Apps guide](https://mplemay.github.io/belgie/mcp-apps/) covers Python registration and
Belgie project setup.

## Installation

```sh
npm install @belgie/mcp @modelcontextprotocol/ext-apps
npm install --save-dev vite
```

The package is ESM-only and requires Node.js 22 or newer for its development and CLI workflows.

## Package exports

- `@belgie/mcp` exports `Widget`, `mountWidget`, tool-result and host-context hooks, host actions,
  modal helpers, and MCP tool errors.
- `@belgie/mcp/codegen` exports `generateToolTypes()` for programmatic MCP caller generation.
- `@belgie/mcp/internal` contains the runtime factories used by generated callers.
- `@belgie/mcp/vite` exports the `belgie()` Vite plugin.
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

The generated Vite entry calls `mountWidget` for discovered widgets. Use `mountWidget` directly
only when you own the HTML entry and are not using the `<srcDir>/<name>/widget.tsx` convention.

Configure the plugin in a normal Vite configuration:

```ts
import { belgie } from "@belgie/mcp/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Development serves `/widgets/<name>/index.html`. Inline production builds emit self-contained
`dist/widgets/<name>/index.html` files with supported assets inlined. Use shared output when the
widgets should reuse a normal Vite asset graph:

```ts
plugins: [belgie({ srcDir: "src/widgets", bundle: "shared" })],
```

Shared output requires serving the Vite output directory and configuring `base` so widget asset
URLs resolve. Inline mode rejects retained JavaScript chunks and unsupported non-CSS assets.

## Generate typed callers

```sh
npx belgie-mcp generate \
  https://example.com/mcp \
  --output src/mcp-tools.ts
```

The generated functions use the active connected widget by default and accept an explicit `App` as
their optional second argument:

```ts
import { getWeather } from "./mcp-tools.ts";

const response = await getWeather({ city: "Austin" });
if (response.error !== undefined) {
  console.error(response.error.message);
} else {
  console.log(response.result);
}
```

Calls resolve to `{ result, error: undefined }` or `{ result: undefined, error }` and do not reject
for MCP, transport, context, or validation failures. Output-schema tools return typed Zod-validated
structured content. Tools without an output schema return `RawToolResult`, preserving `content`,
optional `structuredContent`, and `_meta`. MCP `isError` responses become `McpToolError` instances.

OAuth is enabled by default. Use `--no-oauth`, `--no-open`, `--header NAME:VALUE`, or
`--header-env NAME=ENV_VAR` as needed. Use `--check` to fail when the generated file is missing or
stale without rewriting it:

```sh
npx belgie-mcp generate https://example.com/mcp \
  --header-env Authorization=AUTH_HEADER \
  --output src/mcp-tools.ts \
  --check \
  --no-open
```

## Consume tool results

Use a generated caller with `useToolResult` inside a connected widget:

```tsx
import { Widget, useToolResult } from "@belgie/mcp";
import { getWeather } from "./mcp-tools";

function WeatherView() {
  const { data, error, isLoading, isFetching, execute } = useToolResult(getWeather);

  if (isLoading) return <p>Waiting for the tool result...</p>;
  if (error !== undefined) return <p>{error.message}</p>;

  return (
    <section>
      <p>{data?.summary ?? "No result"}</p>
      <button disabled={isFetching} onClick={() => void execute({ city: "Austin" })}>
        {isFetching ? "Refreshing..." : "Refresh"}
      </button>
    </section>
  );
}

export default function Weather() {
  return (
    <Widget metadata={{ name: "Weather", version: "1.0.0" }}>
      <WeatherView />
    </Widget>
  );
}
```

The hook exposes `data`, `error`, `rawResult`, `status`, loading flags, and `execute`. It consumes
the opening host result, reuses the latest input for no-argument executions, and keeps existing data
visible during refreshes. It does not add caching, retries, deduplication, or input-change
revalidation.

## Host context, actions, and modals

Use `useDisplayMode`, `useLayout`, `useLocale`, `useTheme`, `useUserAgent`, and `useWidget` inside a
connected `<Widget>`. Context-bound helpers such as `sendMessage`, `sendLog`, `openLink`,
`downloadFile`, `requestDisplayMode`, `requestTeardown`, and `updateModelContext` use the active
widget automatically. Call an explicit `App` method when context is unavailable.

`useModal()` returns `isOpen`, `params`, and `open`; `requestModal()` and `closeModal()` provide the
imperative form. Open modals from a user action. Apps SDK hosts receive the complete modal options,
while other hosts use the in-iframe fallback with `params`, a backdrop, and Escape handling.

The [shipped MCP Apps example](https://github.com/mplemay/belgie/tree/main/examples/ui/mcp) combines
the widget, generated caller, tool-result hook, and host actions in one runnable project.

## Development

```sh
npm ci
npm test
npm run check
npm pack --dry-run
```

`npm test` builds with tsdown, validates package metadata and declarations, runs Vitest with V8
coverage, and checks TypeScript API fixtures.
