# Pydantic AI

Use `BelgieSandbox` when a Pydantic AI agent needs a restricted `run_typescript` tool. It executes
complete JavaScript, TypeScript, or TSX modules in an embedded Deno runtime inside your Python
application.

## Install

```bash
uv add "belgie[pydantic-ai]"
```

Configure the model provider separately using the [Pydantic AI documentation](https://ai.pydantic.dev/).

## Add the sandbox

```python {title="agent.py"}
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent(
    "openai:gpt-5",
    capabilities=[BelgieSandbox()],
)

result = agent.run_sync("Use TypeScript to group ['ant', 'ape', 'bear'] by first letter.")
print(result.output)
```

The model supplies a complete module and exports either a default function or a named `run` function:

```typescript
export default function run(): Record<string, string[]> {
  const words = ["ant", "ape", "bear"];
  return Object.groupBy(words, (word) => word[0]);
}
```

The exported function receives no arguments and must return JSON-serializable data. Console output is not captured.

## Default isolation

Each agent run receives a separate temporary Belgie environment and Deno runtime. The runtime starts
lazily on the first `run_typescript` call, so an unused capability does not start a worker.

By default:

- npm, JSR, URL, and relative imports are disabled;
- runtime network access, including `fetch`, is denied;
- host files, environment variables, subprocesses, writes, FFI, and system information are denied;
- reads are limited to the temporary workspace;
- each call has a 30-second deadline and a 50 KiB JSON output limit;
- V8's old-generation heap is limited to 128 MiB.

Belgie is an embedded language sandbox, not a container or virtual machine. Use an OS- or cloud-isolated sandbox when
untrusted code requires a separate kernel, filesystem, or network namespace.

## Configure packages, network, and rendering

Package imports, network access, and rendering are separate options. Rendering also enables package
resolution because `@belgie/vite` must be installed:

```python
from belgie.pydantic_ai import BelgieSandbox

capability = BelgieSandbox(
    allow_package_imports=True,
    allow_network=True,
    enable_rendering=True,
    plugins=["npm:@tailwindcss/vite@latest"],
)
```

`allow_package_imports=True` permits npm, JSR, and URL module resolution, but does not enable
runtime `fetch`. `allow_network=True` grants unrestricted runtime network access without granting
host files or subprocesses.

With `enable_rendering=True`, the capability exposes a `render_widget` tool. Pass a complete TSX
module that default-exports a React component — do not call `render()`:

```tsx
export default function Widget() {
  return <main>Hello from Belgie</main>;
}
```

Rendering runs on a separate privileged renderer side channel. Model scripts remain
workspace-restricted; use `plugins=()` for untrusted agents because configured renderer plugins can
write under the workspace and load native code from installed packages. The returned HTML is
ordinary tool output. Raise `max_output_bytes` when the rendered document is larger than the default
limit.

## Reuse a session

A capability-owned runtime lasts for one agent run. Calls made during that run share the same Deno
worker. Separate or concurrent runs receive separate workers and workspaces.

For explicit reuse across runs, create and enter a session yourself:

```python
import asyncio

from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox, BelgieSandboxSession


async def main() -> None:
    async with BelgieSandboxSession(allow_package_imports=True) as session:
        agent = Agent(
            "openai:gpt-5",
            capabilities=[BelgieSandbox(session=session)],
        )
        await agent.run("Run a TypeScript transform.")
        await agent.run("Run another transform in the same Deno worker.")


asyncio.run(main())
```

An injected session must already be open. The capability does not enter or close it, and one session must not be used
by overlapping runs because runtime-global state is shared.

For a caller-configured permission profile, create a `belgie.Runtime` and pass it as
`BelgieSandboxSession(runtime=...)`. The session enters and exits that runtime without changing its options. Custom
runtimes do not provide the rendering side channel.

## Deferred loading and composition

Set `defer_loading=True` to hide the capability until the model explicitly loads it:

```python
BelgieSandbox(defer_loading=True)
```

The default deferred capability ID is `belgie_sandbox`; pass a stable `id` when several deferred capabilities are
present. The capability is additive: existing agent tools remain available alongside `run_typescript`, while code
running in the Deno sandbox cannot call those agent tools.

## Timeouts, output limits, and errors

`timeout` bounds each module execution. A timeout cancels and drains the script task before returning a retry prompt to
the model. Parent-run cancellation is preserved and owned cleanup is shielded from cancellation.

Results are serialized as compact JSON and measured in UTF-8 bytes. Results over `max_output_bytes` become a
`ModelRetry` asking the model for a smaller result; they are not silently truncated. Script, module, permission,
JavaScript, timeout, and invalid-JSON failures become `ModelRetry`. Missing Belgie, runtime startup failures, unopened
sessions, and lifecycle misuse raise typed errors:

- `BelgieSandboxError`
- `BelgieSandboxExecutionError`
- `BelgieSandboxTimeoutError`
- `BelgieSandboxUnavailableError`

## Configuration

```python
BelgieSandbox(
    allow_package_imports=False,
    allow_network=False,
    enable_rendering=False,
    plugins=(),
    max_old_generation_size_mb=128,
    timeout=30.0,
    max_output_bytes=50 * 1024,
    max_retries=3,
    session=None,
    instructions=None,
)
```

Set `max_old_generation_size_mb=None` to leave the V8 limit unset. Set `instructions=""` to suppress the built-in
capability instructions, or pass a string to replace them. Owned-runtime settings cannot be combined with an injected
session; configure those options on the session instead. `timeout`, `max_output_bytes`, and `max_retries` still apply
to an injected session.

## Limitations

- The capability requires asyncio; Belgie's async Python bindings do not run under Trio.
- Durable execution capabilities are rejected because a live Deno worker cannot cross activity, task, workflow, or
  replay boundaries.
- Streaming logs and incremental results are not exposed.
- Host-file module imports and direct filesystem tools are outside this capability's contract.
- Native npm add-ons may need permissions beyond the package-import profile; review them before using a
  caller-configured runtime.

## See also

- [AI agent overview](overview.md)
- [Runtime](../runtime.md)
- [@belgie/vite](../packages/vite.md)
