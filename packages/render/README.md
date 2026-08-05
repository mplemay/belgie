# `@belgie/render`

`@belgie/render` lets an agent-authored TypeScript or TSX script request one self-contained HTML
document. Belgie evaluates the script in its restricted agent runtime, rebuilds the widget in a
separate renderer runtime, and returns the HTML as the ordinary `run_code` result.

See the [full package guide](https://mplemay.github.io/belgie/packages/render/) and the
[AI agent overview](https://mplemay.github.io/belgie/agents/overview/) for integration details.
Use [`@belgie/mcp`](https://mplemay.github.io/belgie/packages/mcp/) for path-based widgets owned by
a Python MCP server.

## Render a widget

Import `render` with the Deno npm specifier and return it from the script's exported function:

```tsx
import { render } from "npm:@belgie/render";

function Widget() {
  return <main>Hello from Belgie</main>;
}

export default function run() {
  return render({
    widget: <Widget />,
    plugins: [],
  });
}
```

The result is one complete HTML document with inline JavaScript, CSS, and supported assets. The
built-in Pydantic AI and LangChain integrations provide the renderer side channel. A caller-owned
`Runtime()` does not provide that side channel by itself.

## Options and imports

`render()` accepts a required React `widget` and optional Vite `plugins`. Both values must be
visible to static source analysis in an inline options object, a static variable binding, or a
static object spread:

```tsx
const widget = <main>Ready</main>;
const options = { widget, plugins: [] };

export default function run() {
  return render(options);
}
```

Computed option keys, opaque spreads, post-declaration mutation, and dynamically imported render
values are rejected. Package imports work in the browser graph:

```tsx
import { render } from "npm:@belgie/render";
import React from "npm:react";

const widget = <main>{React.createElement("strong", null, "Ready")}</main>;

export default function run() {
  return render({ widget, plugins: [] });
}
```

Relative imports are unsupported for the browser widget graph. The browser mounts the extracted
widget expression and does not run `run()` again, so browser dependencies must be reachable from
module-level bindings.

## Renderer permissions

The agent script remains workspace-restricted. Vite builds the browser widget in a separate renderer
with workspace-scoped read/write/FFI and the limited system access required by native loaders.

Nonempty `plugins` values are evaluated again in that renderer. Plugin factories, hooks, and their
imports therefore run with the renderer's broader permissions. Treat plugins as reviewed application
code and use `plugins: []` for untrusted agents.

## Host-owned rendering

Applications that manage their own renderer can use the host entry from a privileged worker:

```ts
import { buildFromSource } from "@belgie/render/host";

const html = await buildFromSource(source, inlineModuleUrl);
```

Do not import `@belgie/render/host` into a restricted agent script. It brings Vite's native loader
requirements into the process and is intended for the renderer worker only.

## Development

```sh
npm ci
npm test
npm run check
npm pack --dry-run
```

The package is ESM-only, requires Node.js 22 or newer, and uses tsdown, publint, TypeScript, and
Vitest in its package validation workflow.
