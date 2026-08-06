# Command

Use `Command` when Python needs to run an installed JavaScript package binary, such as Vite, through
a Belgie [`Runtime`](runtime.md). Commands use the same `Environment` dependency and permission
boundary as scripts.

Use a [`Script`](script.md) when Python needs a value from JavaScript. Use `Command` when the package
exposes a process-style tool whose output should be handled as command output.

## Run an installed binary

Declare the binary in an environment, install it, then invoke it through the runtime:

```python {title="run_vite.py"}
import asyncio

from belgie import Command, Environment, Runtime


async def main() -> None:
    async with Environment({"vite": "6", "rollup": "4.62.2"}) as environment:
        await environment.install()
        async with Runtime(env=environment) as runtime:
            await runtime(Command("vite"))("--version")


asyncio.run(main())
```

The command's stdout and stderr follow the runtime command behavior. Arguments are passed directly;
Belgie does not invoke a shell to parse them. Use the CLI's
[`belgie run`](cli.md#run-a-project-command) when the command belongs to a project manifest.

## Configure a command

`Command(name, cwd=None, env=None, module=False)` accepts:

| Argument | Purpose |
| --- | --- |
| `name` | Installed package binary or module name. |
| `cwd` | Working directory for the process. |
| `env` | Environment variables passed to the command. |
| `module` | Treat the target as a module entry instead of a binary. |

Keep `cwd` inside the intended workspace and pass only the environment variables the command needs.
Set `module=True` when the target should be run as a module instead of an installed binary.

## Use commands from a project

The CLI reads `[tool.belgie.dependencies]`, installs the project environment, and runs the command
with its project configuration:

```bash
uv run belgie run vite --version
```

See [CLI](cli.md) for lockfile and frozen-install behavior.

## See also

- [Environment](environment.md)
- [Runtime](runtime.md)
- [MCP Apps](mcp-apps.md)
