# `@belgie/render`

`@belgie/render` lets an agent-authored TSX script request one self-contained HTML document. The
Belgie host completes the request in a separate renderer runtime with Vite, then returns the HTML as
the ordinary `run_code` result.

This API is independent from the path-based `widget.tsx` flow in [`@belgie/mcp`](mcp.md).

## Render a widget

Import `render` from the npm package and return its promise from the script’s exported function:

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
privileged renderer worker, not from the restricted agent script.

## Renderer boundary

The model-visible script and the renderer have different responsibilities:

| Runtime | Responsibility | Permissions |
| --- | --- | --- |
| Agent script | Evaluate the module and construct the render request. | Workspace reads, no host system paths, no FFI, and no renderer-only system access. |
| Belgie renderer | Build the browser widget with Vite and return HTML. | Workspace-scoped read/write/FFI plus the limited system access required by Vite loaders. |

The renderer rebuilds from sealed source. Script-side plugin expressions are not authoritative for
the privileged build.

!!! warning "Rendering is not a permission escalation"
    Returning `render(...)` does not give the model-visible script host filesystem, FFI, or broad
    system permissions. Keep secrets and sensitive files outside the renderer workspace.

## Options

`render` accepts:

| Option | Required | Purpose |
| --- | --- | --- |
| `widget` | Yes | A React element to mount in the browser. |
| `plugins` | No | Vite plugins used during the server-side build. |

Both keys must be visible to Belgie’s static source analysis. Use an inline options object, a
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
workspace modules relative to the inline module URL, but plugin-only imports are removed before the
browser bundle is produced.

The browser mounts the extracted `widget` expression and does not execute `run()` again. Keep
browser widget expressions dependent only on module-level bindings.

## See also

- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
- [MCP Apps](../mcp-apps.md)
