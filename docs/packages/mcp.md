# `@belgie/mcp`

`@belgie/mcp` is the ESM TypeScript package for MCP Apps widgets. It provides the React widget
wrapper, typed tool-call helpers, host-context hooks, modal support, and the Vite plugin used by
[MCP Apps](../mcp-apps.md).

Use this page for browser-side APIs and generated callers. Use [MCP Apps](../mcp-apps.md) for the
Python registration, project dependency setup, and development/production workflow.

## Install

Install the package and its MCP Apps peer dependency with npm:

```bash
npm install @belgie/mcp @modelcontextprotocol/ext-apps
npm install --save-dev vite
```

The package requires Node.js 22 or newer for its development and CLI workflows. The Python Belgie
runtime itself does not require Node.js.

## Package exports

| Import | Purpose |
| --- | --- |
| `@belgie/mcp` | React widget, host context, tool-result, modal, and App helpers. |
| `@belgie/mcp/codegen` | Programmatic typed MCP caller generation. |
| `@belgie/mcp/internal` | Runtime factories used by generated callers. |
| `@belgie/mcp/vite` | The `belgie()` Vite plugin. |
| `@belgie/mcp/package.json` | Package metadata. |

## Build a widget

Widgets are discovered below the configured source directory at `<name>/widget.tsx`:

```tsx
import { Widget } from "@belgie/mcp";

export default function Status() {
  return (
    <Widget metadata={{ name: "Status", version: "1.0.0" }}>
      <main>Ready</main>
    </Widget>
  );
}
```

The component must have a default export. Configure the plugin in Vite:

```ts
import { belgie } from "@belgie/mcp/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Development serves `/widgets/<name>/index.html`. By default, production emits one self-contained HTML file at
`dist/widgets/<name>/index.html` for each widget. The plugin rejects duplicate widget names, missing default exports,
retained JavaScript chunks, and unsupported non-CSS assets in this inline mode.

Use `belgie({ bundle: "shared" })` for traditional Vite bundling. This adds widget entries to the existing Vite input
graph so host application code and dependencies can be reused. Widget HTML remains under `dist/widgets`, while Vite
emits shared JavaScript, CSS, and other assets normally; serve the configured Vite output directory and configure
`base` so those URLs are reachable by the widget host.

The widget entry is always named `widget.tsx` below the configured source directory. The Python
extension owns the `Path` registration; this package owns the browser bundle and host bridge.

## Use typed tool results

Generate callers from the MCP server rather than hand-writing schemas:

```bash
npx belgie-mcp generate https://example.com/mcp --output src/mcp-tools.ts
```

Then use the generated caller with `useToolResult`:

```tsx
import { Widget, useToolResult } from "@belgie/mcp";
import { getWeather } from "./mcp-tools";

function WeatherView() {
  const { data, error, isLoading, isFetching, execute } = useToolResult(getWeather);

  return (
    <section>
      <p>{error?.message ?? data?.summary ?? (isLoading ? "Loading..." : "No result")}</p>
      <button disabled={isFetching} onClick={() => void execute({ city: "Austin" })}>
        Refresh
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

`useToolResult` exposes `data`, `error`, `rawResult`, `status`, loading flags, and an `execute`
function. It reads the opening tool result supplied by the MCP Apps host and can issue later calls.

## Read host context

Use the hooks inside a connected widget:

| Hook | Returns |
| --- | --- |
| `useDisplayMode()` | Current display mode and a setter for requesting a new mode. |
| `useLayout()` | Maximum height and safe-area insets. |
| `useLocale()` | Normalized host locale, defaulting to `en-US`. |
| `useTheme()` | Host theme, defaulting to `light`. |
| `useUserAgent()` | Normalized device type and input capabilities. |
| `useWidget()` | The active MCP Apps `App` object. |

The hooks subscribe to host context changes. Call them after the `<Widget>` has established the
host connection.

## Open modals and call host actions

`useModal()` returns `isOpen`, modal `params`, and an `open` callback. The imperative helpers
`requestModal()` and `closeModal()` are available when a React hook is not convenient. Additional
host helpers include `sendMessage`, `sendLog`, `openLink`, `downloadFile`, `requestDisplayMode`,
`requestTeardown`, and `updateModelContext`.

Modal opening should be triggered by a user action, such as a button click. Hosts that support Apps
SDK modals receive the request directly; other hosts use the package's in-iframe fallback.

## Generate callers with authentication

The generator accepts OAuth by default and supports direct headers:

```bash
npx belgie-mcp generate https://example.com/mcp \
  --header-env Authorization=AUTH_HEADER \
  --output src/mcp-tools.ts
```

Use `--no-oauth` for an endpoint without OAuth, `--no-open` to print rather than open an
authorization URL, and `--check` to verify an existing output file without rewriting it.

## Development commands

The package uses npm and keeps `package-lock.json` in version control:

```bash
npm ci
npm test
npm run check
npm pack --dry-run
```

## See also

- [MCP Apps](../mcp-apps.md)
- [@belgie/render](render.md)
- [MCP example](../examples/mcp.md)
