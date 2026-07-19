# `@belgie/mcp`

TypeScript helpers for building Belgie MCP Apps, generating typed MCP tool callers, and packaging path-based React
widgets with Vite.

## Installation

Install the package and its MCP Apps peer dependency with npm:

```sh
npm install @belgie/mcp @modelcontextprotocol/ext-apps
```

Install Vite when using the widget plugin:

```sh
npm install --save-dev vite
```

## Package exports

- `@belgie/mcp` exports `Widget`, `mountWidget`, widget host-context hooks, `useWidget`, `useToolResult`, context-bound
  App helpers, and MCP tool errors.
- `@belgie/mcp/builder` exports the trusted programmatic `buildWidget()` compiler used by Python's isolated virtual
  widget builder.
- `@belgie/mcp/codegen` exports programmatic MCP tool-type generation.
- `@belgie/mcp/internal` contains the runtime factories used by generated callers.
- `@belgie/mcp/vite` exports the `belgie()` Vite plugin.
- `@belgie/mcp/package.json` exposes the package metadata.

The package is ESM-only and requires Node.js 22 or newer.

## Generate typed tool callers

Run the CLI against a streamable HTTP MCP endpoint:

```sh
npx belgie-mcp generate https://example.com/mcp --output src/mcp-tools.ts
```

OAuth is enabled by default. Use `--no-oauth` for an endpoint that does not require it, `--no-open` to print the
authorization URL, `--header NAME:VALUE` for a direct header, or `--header-env NAME=ENV_VAR` to read a secret from the
environment. `--check` verifies that an existing output file is current without rewriting it.

Generated callers execute only when called, use the connected widget App by default, and accept an explicit App as the
optional second argument:

```ts
import { getWeather } from "./mcp-tools.ts";

const { result, error } = await getWeather({ city: "Austin" });
```

## Build a widget

Widgets are discovered at `<srcDir>/<name>/widget.tsx` and must have a default export:

```tsx
import { Widget, mountWidget, useToolResult } from "@belgie/mcp";
import { getWeather } from "../../../mcp-tools.ts";

function Weather() {
  const weather = useToolResult(getWeather);
  return (
    <Widget metadata={{ name: "weather", version: "1.0.0" }}>
      {weather.data?.summary ?? "Waiting for weather"}
    </Widget>
  );
}

mountWidget(Weather);
```

## Read widget host context

Host-context hooks read the current MCP Apps environment and update when the host changes it. Use them inside a
connected `<Widget>` child:

```tsx
import {
  useDisplayMode,
  useLayout,
  useLocale,
  useTheme,
  useUserAgent,
} from "@belgie/mcp";

function Environment() {
  const [displayMode, setDisplayMode] = useDisplayMode();
  const { maxHeight, safeArea } = useLayout();
  const locale = useLocale();
  const theme = useTheme();
  const userAgent = useUserAgent();

  return (
    <section
      data-theme={theme}
      style={{ maxHeight, paddingTop: safeArea.insets.top }}
    >
      <p>{locale}</p>
      <p>{userAgent.device.type}</p>
      <button onClick={() => void setDisplayMode("fullscreen")}>
        {displayMode === "fullscreen" ? "Fullscreen" : "Expand"}
      </button>
    </section>
  );
}
```

`useLayout()` contains only container height and safe-area information. Theme, locale, and the normalized device and
input-capability value are exposed separately through `useTheme()`, `useLocale()`, and `useUserAgent()`.

Add the plugin to a normal Vite configuration. Development serves each widget at `/widgets/<name>/index.html`;
production emits a self-contained `dist/widgets/<name>/index.html` with JavaScript, CSS, and assets inlined.

```ts
import { defineConfig } from "vite";
import { belgie } from "@belgie/mcp/vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Agent-authored widgets use Python's separate `belgie.widget.WidgetBuilder` API. It supplies source through virtual
modules, disables Vite config discovery and disk output, and limits bare imports to dependencies chosen by the host.
The path-based plugin above remains the normal workflow for checked-in widget projects.

## Development

This package uses npm and keeps its lockfile in version control:

```sh
npm ci
npm run dev
npm run check
npm run test:watch
npm test
npm pack --dry-run
```

`npm test` builds with tsdown, validates the package with publint and `@arethetypeswrong/cli` rules, runs the serialized
Vitest suite with V8 coverage, and checks TypeScript 7 declarations and API fixtures.
