# `@belgie/vite`

`@belgie/vite` is Belgie's Vite package for React widgets. It covers three modes:

- a Vite plugin for path-based MCP App widgets;
- a CLI that builds one widget file into self-contained HTML;
- the host renderer used by agent `render_widget` tools.

Use this page for the Vite plugin, CLI, and agent rendering contract. Use [`@belgie/mcp`](mcp.md)
for browser Widget APIs (`Widget`, host hooks, modals, typed tool callers). Use
[MCP Apps](../mcp-apps.md) for Python `BelgieExtension` registration.

## Choose the widget model

| Widget ownership | Package / tool | Delivery |
| --- | --- | --- |
| A Python MCP server project | `@belgie/vite` plugin + [`@belgie/mcp`](mcp.md) browser APIs | A registered `Path` to `widget.tsx`, served by Vite in development or read from built output in production. |
| An agent run | `render_widget` (backed by `@belgie/vite`) | One self-contained HTML document returned as the framework tool result. |

The two flows share React and Vite, but they have different lifecycles. `render_widget` does not
register an MCP tool, open a development server, or create a reusable widget route.

## Vite plugin mode

Configure the plugin in a normal Vite configuration:

```ts {title="vite.config.ts"}
import { belgie } from "@belgie/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Widgets live at `<srcDir>/<name>/widget.tsx` and must default-export a React component. Development
serves each widget at `/widgets/<name>/index.html`. The default production build emits a
self-contained file at `dist/widgets/<name>/index.html`.

Use `bundle: "shared"` when widget HTML should reference the host Vite asset graph instead of
inlining everything. See [MCP Apps](../mcp-apps.md) and [`@belgie/mcp`](mcp.md) for the full
path-based workflow.

## CLI mode

Build one widget file to HTML without a Vite config:

```bash
@belgie/vite --widget path/to/widget.tsx --out widget.html --plugins npm:@tailwindcss/vite@latest
```

From Belgie Python:

```python
await runtime(Command("@belgie/vite"))(
    "--widget",
    "path/to/widget.tsx",
    "--out",
    "widget.html",
    "--plugins",
    "npm:@tailwindcss/vite@latest",
)
```

The widget file must default-export a React component. Host-configured plugin specifiers are loaded
for the server-side Vite build; do not call a `render()` helper from widget source.

## Agent rendering

Agent integrations expose a dedicated `render_widget` tool. Enable it on the sandbox or middleware,
optionally with Vite plugin specifiers:

```python
from belgie.pydantic_ai import BelgieSandbox

capability = BelgieSandbox(
    enable_rendering=True,
    plugins=["npm:@tailwindcss/vite@latest"],
)
```

```python
from belgie.langchain import BelgieMiddleware

middleware = BelgieMiddleware(
    enable_rendering=True,
    plugins=["npm:@tailwindcss/vite@latest"],
)
```

`plugins` requires `enable_rendering=True`. Rendering also installs `@belgie/vite` (same remote
package resolution as `allow_package_imports=True` on Pydantic AI). Pass the complete TSX module
source to `render_widget`. Default-export a React component — do not import or call `render()`:

```tsx
export default function Widget() {
  return <main>Hello from Belgie</main>;
}
```

Belgie writes that source to a temporary widget file and runs `@belgie/vite` on a privileged
renderer side channel. The tool result is one self-contained HTML document with inline JavaScript,
CSS, and supported assets.

!!! warning "Plugins are a privilege boundary"
    Configured `plugins` run in the renderer with workspace read/write/FFI and the limited system
    access Vite loaders need. Treat plugin code as reviewed application code. Use `plugins=()` for
    untrusted agents.

Model-visible `run_typescript` / `run_code` scripts stay workspace-restricted. They do not receive
host system paths, FFI, or renderer-only grants. Custom caller-owned runtimes do not provide the
rendering side channel.

## Contrast with `@belgie/mcp`

| Concern | `@belgie/vite` | `@belgie/mcp` |
| --- | --- | --- |
| Role | Vite plugin, CLI, and agent HTML build | Browser MCP Apps bridge |
| Typical import | `import { belgie } from "@belgie/vite"` | `import { Widget, useCallTool } from "@belgie/mcp"` |
| Widget source | Default-export React component | Default-export component wrapped in `Widget` for host connection |
| Host bridge | Not included | Tool results, host context, modals, host actions |
| Agent inline HTML | `render_widget` tool | Not used |

Keep path-based MCP widgets on `@belgie/mcp` plus the `@belgie/vite` plugin. Keep agent-authored
inline widgets on `render_widget`.

## Develop the package

The package is an ESM package for Node.js 22 or newer and keeps its npm lockfile in version control:

```bash
cd packages/vite
npm ci
npm test
npm run check
npm pack --dry-run
```

## See also

- [MCP Apps](../mcp-apps.md)
- [`@belgie/mcp`](mcp.md)
- [AI agent overview](../agents/overview.md)
- [Pydantic AI](../agents/pydantic-ai.md)
- [LangChain](../agents/langchain.md)
