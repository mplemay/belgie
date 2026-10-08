# Examples

Belgie ships small runnable projects under `examples/` so you can try each workflow in isolation.
Each project has its own `pyproject.toml` and can run independently from the repository checkout.

## Choose a path

| Path | Start here | Demonstrates |
| --- | --- | --- |
| MCP Apps | [MCP Apps](mcp.md) | Python MCP tools with React widgets for Claude, ChatGPT, and other hosts. |
| AI agents | [AI Agents](ai-agents.md) | Agent-authored UI, Pydantic AI `run_typescript`, and LangChain `run_code`. |
| Basic runtime | [Basic Runtime](basic.md) | Scripts, imports, environments, and commands. |

## Run an example

From an example directory, sync its Python dependencies and run its module:

```bash
cd examples/basic/simple
uv run main
```

MCP examples expose local HTTP servers. Start a server from its example directory and use the
endpoint documented in that project's README.

## Examples in the repository

### UI

- `examples/ui/mcp`: a minimal MCP Apps widget.
- `examples/ui/shadcn`: an MCP Apps widget using Tailwind CSS and shadcn/ui components.
- `examples/ui/tanstack`: a TanStack Start frontend and MCP endpoint served through FastAPI.
- `examples/ui/pydantic-ai`: a FastAPI SPA that renders agent-authored UI from a prompt.

### AI

- `examples/ai/pydantic-ai`: Pydantic AI with `BelgieSandbox`.
- `examples/ai/langchain`: LangChain with `BelgieMiddleware`.

### Basic

- `examples/basic/simple`: file-based TypeScript with `Runtime.from_folder`.
- `examples/basic/inline-deps`: inline npm, JSR, and URL imports.
- `examples/basic/jsr-deps`: a named JSR dependency in an `Environment`.
- `examples/basic/pyproject`: project dependency management with the CLI.
- `examples/basic/environment`: sync and async environments with a project path.
- `examples/basic/commands`: installed package binaries through `Command`.

## See also

- [Install](../install.md)
- [Runtime](../runtime.md)
- [MCP Apps](../mcp-apps.md)
- [AI agents](../agents/overview.md)
