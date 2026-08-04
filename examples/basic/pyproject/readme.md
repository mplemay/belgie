# Pyproject Example

<<<<<<< HEAD
This example declares Belgie package dependencies and a seven-day minimum dependency age in `pyproject.toml`:
=======
This example declares Belgie package dependencies in `pyproject.toml` and manages them with the CLI. Use it when a
project should keep JavaScript dependency declarations beside its Python configuration:
>>>>>>> origin/main

```toml
[tool.belgie]
minimum-dependency-age = "P7D"

[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
```

Use the optional CLI extra to inspect, add, lock, and install those dependencies:

```bash
uv run belgie list
uv run belgie add is-number npm:is-number@7.0.0
uv run belgie lock
uv run belgie install
uv run belgie update --minimum-dependency-age 0
uv run main
```

`uv run main` loads the same `[tool.belgie.dependencies]` table, creates a Belgie `Environment`, and imports
<<<<<<< HEAD
`std_path` from TypeScript. The project setting applies to all dependency-resolution commands; the `update` flag
overrides it for one update.
=======
`std_path` from TypeScript.

See the [CLI guide](../../../docs/cli.md) for the project workflow and frozen-install options.
>>>>>>> origin/main
