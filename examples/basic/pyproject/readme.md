# Pyproject Example

This example declares Belgie package dependencies and a seven-day minimum dependency age in `pyproject.toml`. Use it
when a project should keep JavaScript dependency declarations beside its Python configuration:

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
`std_path` from TypeScript. The project setting applies to all dependency-resolution commands; CLI flags such as
`--minimum-dependency-age` override it for one command.

See the [CLI guide](../../../docs/cli.md) for the project workflow and frozen-install options.
