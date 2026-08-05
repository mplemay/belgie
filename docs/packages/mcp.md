# `@belgie/mcp`

`@belgie/mcp` provides the browser-side pieces of a Belgie MCP App: a connected React widget,
typed MCP tool callers, host-context hooks, host actions, modal support, and a Vite plugin.

Use this page for TypeScript and React APIs. Use [MCP Apps](../mcp-apps.md) for Python tool
registration, Belgie project dependencies, and the server development and production workflow.

## Install

For a standalone TypeScript widget project, install the package, its MCP Apps peer dependency, and
Vite:

```bash
npm install @belgie/mcp @modelcontextprotocol/ext-apps
npm install --save-dev vite
```

The package is ESM-only and requires Node.js 22 or newer for its development and CLI workflows.
The Python Belgie runtime itself does not require Node.js. In a Belgie Python project, declare the
same JavaScript dependencies in `[tool.belgie.dependencies]` and install them with `belgie install`.

## Choose an import

| Import | Use |
| --- | --- |
| `@belgie/mcp` | `Widget`, `mountWidget`, tool-result hooks, host-context hooks, host actions, modals, and errors. |
| `@belgie/mcp/codegen` | Generate typed caller source programmatically with `generateToolTypes()`. |
| `@belgie/mcp/internal` | Runtime factories used by generated callers. Import this only when building compatible generated code. |
| `@belgie/mcp/vite` | The `belgie()` Vite plugin. |
| `@belgie/mcp/package.json` | Package metadata. |

The public application surface is `@belgie/mcp`. Generated files import their runtime helpers from
`@belgie/mcp/internal`; application code normally imports the generated functions and types instead.

## Build a widget

Widgets are discovered below the configured source directory at `<name>/widget.tsx`. The file must
have a default export. The generated Vite entry imports that component and calls `mountWidget` for
you:

```tsx {title="src/widgets/weather/widget.tsx"}
import { Widget } from "@belgie/mcp";

export default function Weather() {
  return (
    <Widget metadata={{ name: "Weather", version: "1.0.0" }}>
      <main>Ready</main>
    </Widget>
  );
}
```

For a React entry that is mounted by another application, export the component instead and let the
application render it:

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

Use `mountWidget` directly only when you own the HTML entry and are not using the discovered
`<srcDir>/<name>/widget.tsx` convention.

`Widget` connects to the MCP Apps host before rendering its children. Children that use host-bound
hooks or helpers must be descendants of `Widget`. Use `fallback` for the connecting state and
`error` for a connection error:

```tsx
<Widget
  metadata={{ name: "Weather", version: "1.0.0" }}
  fallback={<p>Connecting to the host...</p>}
  error={(error) => <p>Unable to connect: {error.message}</p>}
>
  <WeatherView />
</Widget>
```

Configure the plugin in a normal Vite configuration:

```ts {title="vite.config.ts"}
import { belgie } from "@belgie/mcp/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Development serves each widget at `/widgets/<name>/index.html`. The default production build
emits a self-contained file at `dist/widgets/<name>/index.html` for every widget. JavaScript, CSS,
fonts, images, and supported dynamic imports are inlined so the widget does not need a separate
asset server.

The plugin rejects duplicate widget names, missing default exports, retained JavaScript chunks, and
unsupported non-CSS assets in the default inline mode. The Python extension owns widget `Path`
registration and HTML delivery; this package owns the browser bundle and host bridge.

### Share Vite assets

Use shared mode when the widget should participate in the existing Vite input graph and reuse host
application code or dependencies:

```ts
export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets", bundle: "shared" })],
  base: "/assets/",
});
```

Shared mode leaves JavaScript, CSS, fonts, images, and dynamic-import chunks as normal Vite output.
The widget HTML remains under `dist/widgets`, references those assets through the configured
`base`, and must be served with the rest of the Vite output. Use the default inline mode when each
widget must be a completely self-contained HTML document.

## Generate typed tool callers

Generate callers from the MCP server's `tools/list` response instead of hand-writing input and
output schemas:

```bash
npx belgie-mcp generate \
  http://127.0.0.1:3001/mcp \
  --output src/widgets/tools.ts
```

The command writes one camelCase function per tool and TypeScript declarations for its input and,
when available, structured output. Commit the generated file. Vite and widget startup do not
regenerate it, so the widget can build without contacting the MCP server.

Generated functions use the active connected widget by default and accept an explicit MCP Apps
`App` as the optional second argument:

```ts
import { getWeather } from "./tools";

const current = await getWeather({ city: "Austin" });
const fromExplicitApp = await getWeather({ city: "Austin" }, app);
```

Calls resolve to exactly one of these branches and do not reject for MCP, transport, context, or
validation failures:

```ts
const response = await getWeather({ city: "Austin" });
if (response.error !== undefined) {
  console.error(response.error.message);
} else {
  console.log(response.result);
}
```

Tools with an MCP `outputSchema` produce a parsed, typed `result` validated with Zod. Tools without
an output schema return `RawToolResult`, which retains the complete MCP response, including
`content`, optional `structuredContent`, and `_meta`. MCP `isError` responses become
`McpToolError`; its `result` property keeps the raw error response.

The CLI supports streamable HTTP endpoints, automatic OAuth discovery and PKCE, direct headers,
environment-backed headers, and deterministic freshness checks:

```bash
npx belgie-mcp generate https://example.com/mcp \
  --header-env Authorization=AUTH_HEADER \
  --output src/mcp-tools.ts \
  --check \
  --no-open
```

Use `--no-oauth` for an endpoint that must not attempt OAuth, `--no-open` to print the OAuth URL
instead of opening a browser, `--header NAME:VALUE` for a non-secret header, and repeatable
`--header-env NAME=ENV_VAR` options for secrets. `--check` fails when the output is missing or
stale without rewriting it.

If a build system needs to own generation, call `generateToolTypes({ url, headers, oauth,
openBrowser })` from `@belgie/mcp/codegen` and write the returned TypeScript source itself.

## Use tool results in a widget

`useToolResult` connects a generated caller to both the opening tool result and later executions:

```tsx
import { Widget, useToolResult } from "@belgie/mcp";
import { getWeather } from "./tools";

function WeatherView() {
  const { data, error, isLoading, isFetching, execute } = useToolResult(getWeather);

  if (isLoading) {
    return <p>Waiting for the tool result...</p>;
  }
  if (error !== undefined) {
    return <p>{error.message}</p>;
  }

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

The hook returns `data`, `error`, `rawResult`, `status`, `isLoading`, `isFetching`, `isSuccess`,
`isError`, and `execute`. The opening result is consumed from the host without requiring a separate
event handler. `execute()` reuses the latest input, while `execute(nextInput)` replaces it for
later no-argument executions. Existing data remains visible while a refresh is in flight.

Direct generated calls and `useToolResult` are separate: a direct call does not update hook state,
and the hook does not add caching, retries, deduplication, or input-change revalidation.

For a schema-less tool, `data` is the raw MCP response. For a schema-backed tool, malformed
structured output is returned as an error. Opening cancellation becomes `McpToolCancelledError`.

The shipped [MCP Apps example](../examples/mcp.md) combines this hook with `Widget`, connection
fallbacks, raw-result inspection, and host actions:

```tsx
--8<-- "examples/ui/mcp/src/mcp_app/views/widgets/get-time/widget.tsx"
```

## Read host context

Use these hooks inside a connected `<Widget>` child. They subscribe to host-context changes:

| Hook | Returns |
| --- | --- |
| `useDisplayMode()` | `[displayMode, setDisplayMode]` for the current mode and a host request. |
| `useLayout()` | Container `maxHeight` and safe-area insets. |
| `useLocale()` | The host locale, defaulting to `en-US`. |
| `useTheme()` | The host theme, defaulting to `light`. |
| `useUserAgent()` | Normalized device type and input capabilities. |
| `useWidget()` | The active MCP Apps `App` object. |

```tsx
import { useDisplayMode, useLayout, useLocale, useTheme, useUserAgent } from "@belgie/mcp";

function Environment() {
  const [displayMode, setDisplayMode] = useDisplayMode();
  const { maxHeight, safeArea } = useLayout();
  const locale = useLocale();
  const theme = useTheme();
  const userAgent = useUserAgent();

  return (
    <section data-theme={theme} style={{ maxHeight, paddingTop: safeArea.insets.top }}>
      <p>{locale}</p>
      <p>{userAgent.device.type}</p>
      <button onClick={() => void setDisplayMode("fullscreen")}>
        {displayMode === "fullscreen" ? "Fullscreen" : "Expand"}
      </button>
    </section>
  );
}
```

## Call host actions

The context-bound helpers use the active widget automatically and preserve the MCP Apps method
signatures:

```tsx
import { openLink, sendLog, sendMessage, updateModelContext } from "@belgie/mcp";

async function notifyHost() {
  await sendMessage({ role: "user", content: [{ type: "text", text: "Hello" }] });
  await sendLog({ level: "info", data: "Sent a message" });
  await openLink({ url: "https://modelcontextprotocol.io" });
  await updateModelContext({ content: [{ type: "text", text: "The user opened the weather view." }] });
}
```

Other helpers include `downloadFile`, `requestDisplayMode`, and `requestTeardown`. If code already
holds a specific `App`, call that object's method directly instead of using a context-bound helper.
All context-bound helpers require a connected widget and throw when called outside one.

## Open a modal

`useModal()` returns `isOpen`, the host-provided `params`, and an `open` callback:

```tsx
import { useModal } from "@belgie/mcp";

function Cart() {
  const { isOpen, params, open } = useModal();

  if (isOpen) {
    return <p>Confirm product {String(params?.productId)}</p>;
  }

  return (
    <button onClick={() => open({ title: "Confirm", params: { productId: 42 } })}>
      Add to cart
    </button>
  );
}
```

Use `requestModal()` and `closeModal()` for imperative code. Apps SDK hosts receive `title`,
`template`, and `anchor`; hosts without the Apps SDK use the in-iframe fallback, which applies
`params` and handles the backdrop and Escape key. Open modals from a user action such as a click,
not from a mount effect.

## Develop the package

The package uses npm and keeps its lockfile in version control:

```bash
cd packages/mcp
npm ci
npm test
npm run check
npm pack --dry-run
```

`npm test` builds with tsdown, validates package metadata and declarations, runs the serialized
Vitest suite with V8 coverage, and checks the TypeScript API fixtures.

## See also

- [MCP Apps](../mcp-apps.md)
- [MCP Apps example](../examples/mcp.md)
- [@belgie/render](render.md)
- [CLI](../cli.md)
