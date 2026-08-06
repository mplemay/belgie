# Install Belgie

Install Belgie when an AI agent or Python application needs to run JavaScript, TypeScript, or TSX.
The base package embeds a Deno-powered runtime and does not install a separate Node.js runtime.

## Install the runtime

```bash
uv add belgie
```

Belgie supports Python 3.12 through 3.14. Start here if you want direct script execution or plan to
add an integration later.

## Choose an integration

Install only the integration dependencies your project uses.

| Extra | Adds | Use it when you need |
| --- | --- | --- |
| `cli` | `typer`, `rtoml`, and `tomlkit` | Project dependency commands such as `belgie lock` and `belgie run`. |
| `mcp` | MCP server and MCP Apps types | Python MCP tools with `BelgieExtension`. |
| `pydantic-ai` | Pydantic AI with the OpenAI provider | `BelgieSandbox`. |
| `langchain` | LangChain | `BelgieMiddleware`. |

Choose only the extras your application uses:

```bash
uv add "belgie[mcp,cli]"
```

For an agent project, install the framework you use:

```bash
uv add "belgie[pydantic-ai]"
uv add "belgie[langchain]"
```

!!! note "TypeScript package dependencies"
    The Python runtime does not require Node.js. MCP widget projects still declare their React,
    Vite, and `@belgie/mcp` dependencies in `[tool.belgie.dependencies]`; Belgie resolves and runs
    them through its embedded Deno environment.

## Verify the installation

Verify the runtime before adding an agent or UI integration:

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

The command should print `{'status': 'ok'}`. If it fails, confirm that you are running it inside the
project environment where Belgie was installed, then check [Troubleshooting](troubleshooting.md).

## Optional editor skill

If you use an editor or coding agent that supports the `use-belgie` skill, install the optional
skill with:

```bash
uvx library-skills install
```

The skill is optional. It is not required to import or run Belgie.

## Further reading

- [Runtime](runtime.md) for direct JavaScript and TypeScript execution.
- [Environment](environment.md) for named dependencies and lockfiles.
- [MCP Apps](mcp-apps.md) for widgets and Python MCP tools.
- [AI agents](agents/overview.md) for Pydantic AI `run_typescript` and LangChain `run_code` integrations.
