# belgie

A minimal, secure JavaScript runtime for Python.

## Examples

- **[simple](examples/simple):** Async `Runtime` with a TypeScript script loaded from disk.
- **[jsr-deps](examples/jsr-deps):** `[belgie.dependencies]` locking and JSR imports through `Runtime`.
- **[task-scripts](examples/task-scripts):** `[belgie.scripts]` tasks run through `TaskRunner`.

## Package dependencies

Declare npm and JSR packages in `pyproject.toml` under `[belgie.dependencies]`. Top-level
entries belong to the `default` group. Additional groups use nested tables:

```toml
[belgie.dependencies]
react = "^19"
std_path = "jsr:@std/path@^1"

[belgie.dependencies.dev]
"@types/react" = "^19"

[belgie.dependencies.test]
vitest = "^1"
```

Each key is an import alias. Values are either a version requirement (for npm packages) or a
full `npm:` / `jsr:` specifier.

### Locking and installing

Use `belgie.dependencies.lock()` or `install()` to resolve packages and write `deno.lock`.
By default, only the `default` group is included. Pass `groups` to select one or more groups:

```python
from belgie.dependencies import lock

lock()  # default group only
lock(groups=["default", "dev"])  # default and dev groups
lock(groups=["dev"])  # dev group only
```

`PackageInstallResult.groups` reports how many dependencies were resolved per group.

Async helpers (`alock`, `ainstall`, `aupdate`) accept the same arguments.

### Runtime and tasks

When running JavaScript through `Runtime` or `[belgie.scripts]` tasks, belgie loads
dependencies from **all groups** so dev-only tooling remains available at runtime.

### Notes

- Duplicate import aliases are not allowed across included groups.
- Top-level string entries under `[belgie.dependencies]` map to the `default` group. A nested
  table whose key is literally `default` is treated as a separate named group.
- The legacy `[belgie.dev-dependencies]` table is not supported; use
  `[belgie.dependencies.dev]` instead.
