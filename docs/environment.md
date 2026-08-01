# Environment

Use `Environment` when a group of scripts or commands shares JavaScript dependencies, a workspace,
or a lockfile. It resolves npm, JSR, URL, and local file dependencies through the embedded Deno
environment.

## Declare dependencies

Pass a mapping of import aliases to specifiers:

```python
from belgie import Environment, Runtime, Script

source = """
import { join } from "std_path";
export default () => join("src", "index.ts");
"""

with Environment({"std_path": "jsr:@std/path@^1"}) as environment:
    result = environment.install()
    with Runtime(env=environment) as runtime:
        path = runtime(Script(source))()
```

`install()` resolves dependencies and returns an `EnvironmentInstallResult` with the lockfile path
and dependency count.

## Use a project workspace

Set `path` to keep the environment’s workspace alongside a project:

```python
from pathlib import Path

from belgie import Environment

with Environment(
    {"std_path": "jsr:@std/path@^1"},
    path=Path("examples/basic/environment"),
) as environment:
    environment.install()
```

Relative file dependencies and relative permissions resolve from this workspace.

## Lock and update dependencies

Use the environment methods directly when your Python application owns dependency setup:

| Method | Purpose |
| --- | --- |
| `lock()` | Resolve dependencies and write a lockfile. |
| `install()` | Install from the dependency declaration and use the current lockfile when available. |
| `update()` | Update selected aliases, or all aliases when no package list is supplied. |

`update(packages, latest=True)` requests the latest versions. `lockfile_only=True` updates the
lockfile without replacing the manifest declarations.

The [CLI](cli.md) provides the same workflow for projects that keep dependencies in
`pyproject.toml`.

## Environment options

Pass `EnvironmentOptions` to tune caching, remote access, imports, node modules, npm caching, and
installation cleanup.

| Option | Default | Purpose |
| --- | --- | --- |
| `cache_setting` | `"use"` | Use, reload, or require the dependency cache. |
| `allow_remote` | `True` | Permit remote module resolution. |
| `allow_json_imports` | `"with_attribute"` | Control JSON import syntax. |
| `npm_caching` | `"eager"` | Choose eager, lazy, or manual npm caching. |
| `clean_on_install` | `True` | Remove stale installed packages during installation. |
| `production` | `False` | Install production dependencies only. |
| `skip_types` | `False` | Skip type information when resolving packages. |
| `node_modules_dir` | `None` | Select automatic, manual, or disabled node modules behavior. |

Additional options support reload patterns, node module linking, package-lock imports, certificate
exceptions, and minimum dependency age. Use the typed constructor in Python for those cases.

## Sync and async use

`Environment` supports both context-manager styles. The entered value exposes the matching sync or
async environment methods:

```python
async with Environment({"std_path": "jsr:@std/path@^1"}) as environment:
    await environment.install()
```

Choose the style that matches the surrounding runtime. Do not close an environment while a runtime
or command that uses it is still active.

## Local packages

Use `file:` specifiers for local packages. Belgie resolves relative file paths from the environment
workspace before installing them. Keep local package boundaries inside the project directory when
the runtime is used for untrusted code.

## See also

- [Runtime](runtime.md)
- [Command](command.md)
- [CLI](cli.md)
