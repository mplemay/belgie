# `@belgie/render`

`@belgie/render` lets an agent-authored TypeScript or TSX script request one self-contained HTML
document. Belgie evaluates the script in its restricted agent runtime, rebuilds the widget in a
separate renderer runtime, and returns the HTML as the ordinary framework tool result
(`run_typescript` for Pydantic AI and `run_code` for LangChain).

Use this page for inline agent-authored widgets. Use [MCP Apps](../mcp-apps.md) and
[`@belgie/mcp`](mcp.md) when a Python MCP server owns a path-based `widget.tsx` project.

## Choose the widget model

| Widget ownership | API | Delivery |
| --- | --- | --- |
| A Python MCP server project | [MCP Apps](../mcp-apps.md) and `@belgie/mcp` | A registered `Path` to `widget.tsx`, served by Vite in development or read from built output in production. |
| An agent run | `render(...)` | One self-contained HTML document returned as the framework tool result. |

The two APIs use React and Vite, but they have different lifecycles. `render()` does not register a
tool, open a development server, or create a reusable widget route.

## Render an inline widget

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

The result is a complete HTML document with a root element and inline JavaScript, CSS, and supported
assets. The built-in Pydantic AI and LangChain integrations replace the render request with this
HTML before returning the tool result. A normal `Runtime()` call without the Belgie agent session
does not provide that side channel.

## Options and source analysis

`render()` accepts the following options:

| Option | Required | Purpose |
| --- | --- | --- |
| `widget` | Yes | The React element to mount in the browser. |
| `plugins` | No | Vite plugins used during the server-side build. Use `[]` when no plugins are needed. |

Belgie analyzes the source so it can separate the server-side request from the browser widget
graph. The `widget` and `plugins` values must be visible in a statically analyzable options object.
These forms are supported:

```tsx
const widget = <main>Ready</main>;
const options = { widget, plugins: [] };

export default function run() {
  return render(options);
}
```

Static object spreads are also supported when their values remain analyzable. Computed option keys,
opaque spreads, post-declaration mutation, and dynamically imported render values are rejected:

```tsx
// Unsupported patterns:
const key = "widget";
const options = { [key]: <main>Not analyzable</main>, plugins: [] };
options.widget = <main>Mutated</main>;
```

These restrictions keep the browser graph and privileged plugin graph explicit. They are source
requirements, not TypeScript typing requirements.

## Imports and browser expressions

Package imports work in the browser widget graph:

```tsx
import { render } from "npm:@belgie/render";
import React from "npm:react";

const widget = <main>{React.createElement("strong", null, "Ready")}</main>;

export default function run() {
  return render({ widget, plugins: [] });
}
```

Relative imports are unsupported for the browser widget graph because the widget is extracted from
the inline module into the generated browser entry. Server-side Vite plugins may import workspace
modules relative to the inline module URL, but those imports are evaluated in the renderer and do
not become browser imports.

The browser mounts the extracted `widget` expression and does not execute `run()` again. Keep the
widget expression dependent only on module-level bindings. Side effects in `run()` therefore stay
in the server-side script; code needed by the browser must be reachable from the widget expression.

## Renderer boundary

The agent script and renderer have different responsibilities and permissions:

| Runtime | Responsibility | Permissions |
| --- | --- | --- |
| Agent script | Evaluate the module and construct the render request. | Workspace reads, with host system paths, FFI, and renderer-only system access unavailable. |
| Belgie renderer | Build the browser widget with Vite and return HTML. | Workspace-scoped read/write/FFI plus the limited system access required by Vite loaders. |

The renderer rebuilds from source. Script-side plugin expressions are not authoritative for the
privileged build, but the plugin expression is evaluated again there.

!!! warning "Plugins are a privilege boundary"
    A nonempty `plugins` value is extracted from the source and evaluated again in the privileged
    renderer. Vite plugin factories, hooks, and their imports run with the renderer's broader
    permissions. Treat plugin code as reviewed application code and use `plugins: []` for untrusted
    agents.

Prefer pure plugin factories or relative workspace plugin modules when plugin construction must
succeed in the restricted script. Plugin-only imports are removed from the browser bundle, but that
does not make the plugin factories or hooks unprivileged.

## Host-owned rendering

Applications that manage their own renderer can call `buildFromSource` from the `@belgie/render/host`
subpath:

```ts
import { buildFromSource } from "@belgie/render/host";

const html = await buildFromSource(source, inlineModuleUrl);
```

Call it only from a renderer worker with workspace FFI and system grants required by Vite. Do not
import `@belgie/render/host` into a restricted agent script: doing so would bring Vite's native
loader requirements into the model-visible runtime. The default export of this subpath is the same
`buildFromSource` function.

## Develop the package

The package is an ESM package for Node.js 22 or newer and keeps its npm lockfile in version control:

```bash
cd packages/render
npm ci
npm test
npm run check
npm pack --dry-run
```

`npm test` builds with tsdown, validates package metadata and declarations, and runs the Vitest
suite with V8 coverage.

## See also

- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
- [MCP Apps](../mcp-apps.md)
- [`@belgie/mcp`](mcp.md)
