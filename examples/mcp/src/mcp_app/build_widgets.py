import tomllib
from pathlib import Path

from belgie import Command, Environment, Runtime

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        document = tomllib.load(file)
    raw_dependencies = document["tool"]["belgie"]["dependencies"]
    dependencies: dict[str, str] = {}
    for alias, specifier in raw_dependencies.items():
        if specifier.startswith("file:"):
            path = (PROJECT_ROOT / specifier.removeprefix("file:")).resolve()
            dependencies[alias] = f"file:{path.as_posix()}"
        else:
            dependencies[alias] = specifier

    with (
        Environment(dependencies, path=PROJECT_ROOT, lockfile=PROJECT_ROOT / "deno.lock") as env,
        Runtime(env=env) as run,
    ):
        run(Command("vite", cwd=str(PROJECT_ROOT)))("build")


if __name__ == "__main__":
    main()
