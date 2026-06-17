from __future__ import annotations

import sys
from json import dumps
from pathlib import Path
from typing import Any, cast

import pytest

from belgie import _core, tasks as public_tasks
from belgie._core import BelgieRuntimeError, RunTaskOptions, TaskProcess, TaskRunner


class TestTaskExports:
    def test_task_exports_are_available_from_core_module(self) -> None:
        assert _core.RunTaskOptions is RunTaskOptions
        assert _core.TaskProcess is TaskProcess
        assert _core.TaskRunner is TaskRunner

    def test_core_task_exports_are_identical_to_public_tasks(self) -> None:
        assert _core.RunTaskOptions is public_tasks.RunTaskOptions
        assert _core.TaskProcess is public_tasks.TaskProcess
        assert _core.TaskRunner is public_tasks.TaskRunner

    @pytest.mark.parametrize(
        "task_type",
        [
            RunTaskOptions,
            TaskProcess,
            TaskRunner,
        ],
    )
    def test_core_task_classes_use_public_tasks_module(self, task_type: type[object]) -> None:
        assert task_type.__module__ == "belgie.tasks"


class TestRunTaskOptions:
    def test_stores_task_cwd_script_and_copied_argv(self, tmp_path: Path) -> None:
        argv = ["--mode", "test"]
        options = RunTaskOptions(str(tmp_path), "build", argv=argv, env={"BELGIE_TEST": "1"}, install=True)
        argv.append("mutated")
        returned_argv = options.argv
        returned_argv.append("mutated-again")

        assert options.task_cwd == str(tmp_path)
        assert options.script == "build"
        assert options.argv == ["--mode", "test"]
        assert options.install is True
        expected_repr = (
            f"RunTaskOptions(task_cwd={dumps(str(tmp_path))}, "
            f"script={dumps('build')}, argv=[{dumps('--mode')}, {dumps('test')}])"
        )
        assert repr(options) == expected_repr

    def test_defaults_optional_collections(self, tmp_path: Path) -> None:
        options = RunTaskOptions(str(tmp_path), "build")

        assert options.argv == []
        assert options.install is False

    def test_validates_constructor_argument_types(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            RunTaskOptions(str(tmp_path), "build", argv=cast("Any", [1]))
        with pytest.raises(TypeError):
            RunTaskOptions(str(tmp_path), "build", env=cast("Any", {1: "value"}))
        with pytest.raises(OverflowError):
            RunTaskOptions(str(tmp_path), "build", port=65_536)


class TestTaskRunner:
    def test_repr_identifies_runner(self) -> None:
        assert repr(TaskRunner()) == "TaskRunner()"

    async def test_rejects_empty_task_script(self, tmp_path: Path) -> None:
        options = RunTaskOptions(str(tmp_path), "   ")

        with pytest.raises(BelgieRuntimeError, match="Task script name must not be empty"):
            await TaskRunner().run(options)

    async def test_rejects_missing_task_cwd(self, tmp_path: Path) -> None:
        options = RunTaskOptions(str(tmp_path / "missing"), "build")

        with pytest.raises(BelgieRuntimeError, match="Invalid task cwd"):
            await TaskRunner().run(options)

    async def test_rejects_file_task_cwd(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not-a-directory"
        file_path.write_text("", encoding="utf-8")
        options = RunTaskOptions(str(file_path), "build")

        with pytest.raises(BelgieRuntimeError, match="Task cwd must be a directory"):
            await TaskRunner().run(options)

    @pytest.mark.parametrize(
        ("host", "port"),
        [
            ("127.0.0.1", None),
            (None, 3000),
            ("   ", 3000),
        ],
    )
    async def test_rejects_partial_long_running_task_origin(
        self,
        tmp_path: Path,
        host: str | None,
        port: int | None,
    ) -> None:
        options = RunTaskOptions(str(tmp_path), "serve", host=host, port=port)

        with pytest.raises(BelgieRuntimeError, match="both host and port"):
            await TaskRunner().start(options)

    async def test_rejects_missing_belgie_script(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"build": "echo ok"})
        options = RunTaskOptions(str(pyproject.parent), "missing")

        with pytest.raises(BelgieRuntimeError, match=r"No \[belgie\.scripts\] entry 'missing'"):
            await TaskRunner().run(options)

    async def test_rejects_missing_belgie_script_on_start(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"build": "echo ok"})
        options = RunTaskOptions(str(pyproject.parent), "missing")

        with pytest.raises(BelgieRuntimeError, match=r"No \[belgie\.scripts\] entry 'missing'"):
            await TaskRunner().start(options)

    async def test_requires_project_lockfile(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"build": "echo ok"})
        (pyproject.parent / "deno.lock").unlink()
        options = RunTaskOptions(str(pyproject.parent), "build")

        with pytest.raises(BelgieRuntimeError, match="belgie.dependencies.install"):
            await TaskRunner().run(options)

    async def test_requires_npm_install_by_default(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(dependencies={"vite": "^8"}, scripts={"build": "vite build"})
        options = RunTaskOptions(str(pyproject.parent), "build")

        with pytest.raises(BelgieRuntimeError, match=r"node_modules.*install=True"):
            await TaskRunner().run(options)

    async def test_failed_task_includes_captured_stderr(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"fail": "sh -c 'echo task exploded >&2; exit 7'"})
        options = RunTaskOptions(str(pyproject.parent), "fail")

        with pytest.raises(BelgieRuntimeError, match="task exploded"):
            await TaskRunner().run(options)

    async def test_successful_task_ignores_stderr_output(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"ok": "sh -c 'echo warn >&2; exit 0'"})
        options = RunTaskOptions(str(pyproject.parent), "ok")

        await TaskRunner().run(options)

    async def test_task_argv_is_forwarded_to_script(
        self,
        write_belgie_pyproject,
        tmp_path: Path,
    ) -> None:
        argv_out = tmp_path / "argv.txt"
        pyproject = write_belgie_pyproject(
            scripts={"args": 'sh -c \'printf "%s\\n" "$@" > "$BELGIE_ARGV_OUT"\' _'},
        )
        options = RunTaskOptions(
            str(pyproject.parent),
            "args",
            argv=["--outDir", "dist"],
            env={"BELGIE_ARGV_OUT": str(argv_out)},
        )

        await TaskRunner().run(options)

        assert argv_out.read_text(encoding="utf-8").splitlines() == ["--outDir", "dist"]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX single-quote argv escaping is Unix-specific")
    async def test_task_argv_handles_single_quotes(
        self,
        write_belgie_pyproject,
        tmp_path: Path,
    ) -> None:
        argv_out = tmp_path / "argv.txt"
        pyproject = write_belgie_pyproject(
            scripts={"args": 'sh -c \'printf "%s\\n" "$@" > "$BELGIE_ARGV_OUT"\' _'},
        )
        options = RunTaskOptions(
            str(pyproject.parent),
            "args",
            argv=["it's"],
            env={"BELGIE_ARGV_OUT": str(argv_out)},
        )

        await TaskRunner().run(options)

        assert argv_out.read_text(encoding="utf-8").splitlines() == ["it's"]

    async def test_task_runs_from_nested_task_cwd(
        self,
        tmp_path: Path,
    ) -> None:
        project = tmp_path / "project"
        nested = project / "apps" / "web"
        nested.mkdir(parents=True)
        cwd_out = tmp_path / "cwd.txt"
        check_script = (
            'python -c "import os, pathlib; '
            "pathlib.Path(os.environ['BELGIE_CWD_OUT']).write_text("
            "str(pathlib.Path.cwd().resolve()), encoding='utf-8')\""
        )
        (project / "pyproject.toml").write_text(
            '[belgie]\n\n[belgie.dependencies]\nstub = "jsr:@std/assert@^1"\n\n'
            f"[belgie.scripts]\ncheck = {dumps(check_script)}\n",
            encoding="utf-8",
        )
        (project / "deno.lock").write_text('{"version":"5"}\n', encoding="utf-8")
        options = RunTaskOptions(
            str(nested),
            "check",
            env={"BELGIE_CWD_OUT": str(cwd_out)},
        )
        expected_cwd = str(nested.resolve())

        await TaskRunner().run(options)

        assert cwd_out.read_text(encoding="utf-8").strip() == expected_cwd

    @pytest.mark.skipif(sys.platform == "win32", reason="TERM trap behavior is Unix-specific")
    async def test_stop_completes_for_term_ignoring_task(
        self,
        write_belgie_pyproject,
    ) -> None:
        pyproject = write_belgie_pyproject(
            scripts={"serve": "sh -c 'trap '' TERM; while true; do sleep 0.05; done'"},
        )
        options = RunTaskOptions(str(pyproject.parent), "serve")

        process = await TaskRunner().start(options)

        await process.stop()

        assert not process.is_running

    async def test_background_task_failure_surfaces_on_stop(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"fail": "sh -c 'echo task exploded >&2; exit 7'"})
        options = RunTaskOptions(str(pyproject.parent), "fail")

        process = await TaskRunner().start(options)

        while process.is_running:
            pass

        with pytest.raises(BelgieRuntimeError, match=r"status 7"):
            await process.stop()

    async def test_task_environment_is_passed_to_subprocess(self, write_belgie_pyproject) -> None:
        command = "sh -c 'test \"$BELGIE_TEST_FLAG\" = set'"
        pyproject = write_belgie_pyproject(scripts={"check": command})
        options = RunTaskOptions(str(pyproject.parent), "check", env={"BELGIE_TEST_FLAG": "set"})

        await TaskRunner().run(options)

    async def test_task_process_reports_origin_running_state_and_stops(
        self,
        write_belgie_pyproject,
        free_port: int,
    ) -> None:
        pyproject = write_belgie_pyproject(scripts={"serve": "sh -c 'while true; do sleep 1; done'"})
        options = RunTaskOptions(str(pyproject.parent), "serve", host="127.0.0.1", port=free_port)

        process = await TaskRunner().start(options)

        try:
            assert isinstance(process, TaskProcess)
            assert process.origin == f"http://127.0.0.1:{free_port}"
            assert process.is_running
            assert "TaskProcess(origin=" in repr(process)
        finally:
            await process.stop()

        assert not process.is_running
