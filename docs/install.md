# Install Belgie

Install Belgie when Python needs to run JavaScript, TypeScript, or TSX. The base package contains
the embedded Deno-powered runtime and does not install a separate Node.js runtime.

## Core installation

```bash
uv add belgie
```

Belgie supports Python 3.12 through 3.14.

## Choose an extra

Install only the integration dependencies your project uses.

| Extra | Adds | Use it for |
| --- | --- | --- |
| `cli` | `typer`, `rtoml`, and `tomlkit` | Project dependency commands such as `belgie lock` and `belgie run`. |
| `mcp` | MCP server and MCP Apps types | Python MCP tools with `BelgieExtension`. |
| `pydantic-ai` | Pydantic AI with the OpenAI provider | `BelgieSandbox`. |
| `langchain` | LangChain | `BelgieMiddleware`. |

Choose the smallest extra set that covers your workflow:

```bash
uv add "belgie[mcp,cli]"
```

For an agent project, select the framework extra:

```bash
uv add "belgie[pydantic-ai]"
uv add "belgie[langchain]"
```

!!! note "TypeScript package dependencies"
    The Python runtime does not require Node.js. MCP widget projects still declare their React,
    Vite, and `@belgie/mcp` dependencies in `[tool.belgie.dependencies]`; Belgie installs and
    runs them through its embedded Deno environment.

## Verify the installation

Run a small script before adding a framework integration:

```bash
uv run python - <<'PY'
import asyncio

from belgie import Runtime, Script


async def main() -> None:
    async with Runtime() as runtime:
        result = await runtime(Script("export default () => ({ status: 'ok' });"))()
    print(result)


asyncio.run(main())
PY
```

The command should print `{'status': 'ok'}`. If the command fails, confirm that you are running it
inside the project environment where Belgie was installed before adding an integration.

## Optional tooling skill

If you use an editor or coding agent that supports the `use-belgie` skill, install the optional
skill with:

```bash
uvx library-skills install
```

The skill is not required to import or run Belgie.

## Further reading

- [Runtime](runtime.md) for direct JavaScript and TypeScript execution.
- [Environment](environment.md) for named dependencies and lockfiles.
- [MCP Apps](mcp-apps.md) for widgets and Python MCP tools.
- [AI agents](agents/overview.md) for Pydantic AI `run_typescript` and LangChain `run_code` integrations.
