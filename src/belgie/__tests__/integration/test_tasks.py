from __future__ import annotations

from shutil import rmtree
from typing import Final

import pytest

from belgie.dependencies import install
from belgie.errors import BelgieRuntimeError
from belgie.tasks import RunTaskOptions, TaskRunner

pytestmark = pytest.mark.integration

GET_TIME_DEPENDENCIES: Final[dict[str, str]] = {
    "vite": "8.0.8",
    "@gdansk/vite": "^0.1.0",
    "@modelcontextprotocol/ext-apps": "^1.7.2",
    "@modelcontextprotocol/sdk": "^1.29.0",
    "@vitejs/plugin-react": "6.0.2",
    "react": "19.2.6",
    "react-dom": "19.2.6",
}
GET_TIME_DEV_DEPENDENCIES: Final[dict[str, str]] = {
    "@types/react": "^19.2.15",
    "@types/react-dom": "^19.2.3",
}


async def test_task_runs_npm_bin_command(
    write_belgie_pyproject,
) -> None:
    pyproject = write_belgie_pyproject(
        dependencies={"vite": "^6"},
        scripts={"version": "vite --version"},
    )
    install(cwd=pyproject.parent)
    await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "version"))
    rmtree(pyproject.parent / "node_modules")
    await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "version", install=True))
    assert (pyproject.parent / "node_modules").is_dir()


async def test_task_rejects_explicit_deno_command(
    write_belgie_pyproject,
) -> None:
    pyproject = write_belgie_pyproject(scripts={"deno": "deno --version"})

    with pytest.raises(BelgieRuntimeError, match=r"deno.*not supported"):
        await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "deno"))


async def test_get_time_dependencies_install_and_build_without_deno(
    write_belgie_pyproject,
) -> None:
    pyproject = write_belgie_pyproject(
        dependencies=GET_TIME_DEPENDENCIES,
        dependency_groups={"dev": GET_TIME_DEV_DEPENDENCIES},
        scripts={"build": "vite build", "version": "vite --version"},
    )
    (pyproject.parent / "index.html").write_text(
        "<main>Belgie task runtime</main>\n",
        encoding="utf-8",
    )

    result = install(cwd=pyproject.parent, groups=["default", "dev"])

    assert result.groups == {"default": 7, "dev": 2}
    assert (pyproject.parent / "node_modules").is_dir()
    assert (pyproject.parent / "node_modules" / ".bin" / "vite").exists()
    await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "version"))
    await TaskRunner().run(
        RunTaskOptions(
            str(pyproject.parent),
            "build",
            argv=["--outDir", "custom-dist"],
        ),
    )
    assert (pyproject.parent / "custom-dist" / "index.html").is_file()
