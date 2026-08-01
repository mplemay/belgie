# Examples

Belgie ships small runnable projects under `examples/`. Each project has its own `pyproject.toml`
and can be run independently from the repository checkout.

## Choose a path

| Path | Start here | Demonstrates |
| --- | --- | --- |
| Basic runtime | [Basic Runtime](basic.md) | Scripts, imports, environments, and commands. |
| MCP Apps | [MCP Apps](mcp.md) | Python MCP tools, React widgets, and Vite. |
| AI agents | [AI Agents](ai-agents.md) | Pydantic AI and LangChain `run_code`. |

## Run an example

From the example directory, sync its Python dependencies and run its module:

```bash
cd examples/basic/simple
uv run main
```

MCP examples expose local HTTP servers. Start the server from the example directory and use the
endpoint documented by that project’s README.

## Examples in the repository

### Basic

- `examples/basic/simple`: file-based TypeScript with `Runtime.from_folder`.
- `examples/basic/inline-deps`: inline npm, JSR, and URL imports.
- `examples/basic/jsr-deps`: a named JSR dependency in an `Environment`.
- `examples/basic/pyproject`: project dependency management with the CLI.
- `examples/basic/environment`: sync and async environments with a project path.
- `examples/basic/commands`: installed package binaries through `Command`.

### UI

- `examples/ui/mcp`: a minimal MCP Apps widget.
- `examples/ui/shadcn`: an MCP Apps widget using Tailwind CSS and shadcn/ui components.
- `examples/ui/tanstack`: a TanStack Start frontend and MCP endpoint served through FastAPI.

### AI

- `examples/ai/pydantic-ai`: Pydantic AI with `BelgieCapability`.
- `examples/ai/langchain`: LangChain with `BelgieMiddleware`.

## See also

- [Install](../install.md)
- [Runtime](../runtime.md)
- [MCP Apps](../mcp-apps.md)
- [AI agents](../agents/overview.md)
