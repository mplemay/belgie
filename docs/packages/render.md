# `@belgie/render`

`@belgie/render` lets an agent-authored TSX script request one self-contained HTML document. The
Belgie host completes the request in a separate renderer runtime with Vite, then returns the HTML as
the ordinary framework tool result (`run_typescript` for Pydantic AI and `run_code` for LangChain).

This API is independent from the path-based `widget.tsx` flow in [`@belgie/mcp`](mcp.md).

Choose the API based on ownership of the widget:

| If the widget... | Use | Delivery model |
| --- | --- | --- |
| Belongs to a Python MCP server project | [MCP Apps](../mcp-apps.md) | A `Path` to `widget.tsx`, with Vite development or built HTML in production. |
| Is authored during an agent run | `render(...)` | One self-contained HTML document returned as the framework tool result. |

## Render a widget

Import `render` from the npm package and return its promise from the script's exported function:

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

The result is a complete HTML document with inline JavaScript, CSS, and supported assets. A host
that owns its own runtime should use `buildFromSource` from `@belgie/render/host` only from a
privileged renderer worker, not from the restricted agent script. A caller-owned Belgie `runtime`
does not provide the renderer side channel used by the built-in agent integrations.

## Renderer boundary

The model-visible script and the renderer have different responsibilities:

| Runtime | Responsibility | Permissions |
| --- | --- | --- |
| Agent script | Evaluate the module and construct the render request. | Workspace reads, no host system paths, no FFI, and no renderer-only system access. |
| Belgie renderer | Build the browser widget with Vite and return HTML. | Workspace-scoped read/write/FFI plus the limited system access required by Vite loaders. Plugin code runs here. |

The renderer rebuilds from source. Script-side plugin expressions are not authoritative for the
privileged build, but the plugin expression is evaluated again there.

!!! warning "Plugins are a privilege boundary"
    Returning `render(...)` keeps the model-visible script in its restricted worker, but a nonempty
    `plugins` value is extracted from the source and evaluated again in the privileged renderer.
    Vite plugin factories, hooks, and their imports run with the renderer's broader permissions.
    Treat plugin code as reviewed application code and use `plugins: []` for untrusted agents.

## Options

`render` accepts:

| Option | Required | Purpose |
| --- | --- | --- |
| `widget` | Yes | A React element to mount in the browser. |
| `plugins` | No | Vite plugins used during the server-side build. |

Both keys must be visible to Belgie's static source analysis. Use an inline options object, a
statically bound variable, or a static object spread. Computed keys, opaque spreads, and mutations
after declaration are rejected.

## Imports and widget expressions

Package imports work in the browser graph:

```tsx
import { render } from "npm:@belgie/render";
import React from "npm:react";

const widget = <main>{React.createElement("strong", null, "Ready")}</main>;

export default function run() {
  return render({ widget, plugins: [] });
}
```

Relative imports are unsupported for the browser widget graph. Server-side Vite plugins may import
workspace modules relative to the inline module URL, but those plugin imports are evaluated in the
privileged renderer and plugin-only imports are removed before the browser bundle is produced.

The browser mounts the extracted `widget` expression and does not execute `run()` again. Keep
browser widget expressions dependent only on module-level bindings.

## See also

- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
- [MCP Apps](../mcp-apps.md)
