from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING, Any, cast

import pytest

from belgie import _core, tasks as public_tasks
from belgie._core import BelgieRuntimeError, RunTaskOptions, TaskProcess, TaskRunner

if TYPE_CHECKING:
    from pathlib import Path


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
        options = RunTaskOptions(str(tmp_path), "build", argv=argv, env={"BELGIE_TEST": "1"})
        argv.append("mutated")
        returned_argv = options.argv
        returned_argv.append("mutated-again")

        assert options.task_cwd == str(tmp_path)
        assert options.script == "build"
        assert options.argv == ["--mode", "test"]
        expected_repr = (
            f"RunTaskOptions(task_cwd={dumps(str(tmp_path))}, "
            f"script={dumps('build')}, argv=[{dumps('--mode')}, {dumps('test')}])"
        )
        assert repr(options) == expected_repr

    def test_defaults_optional_collections(self, tmp_path: Path) -> None:
        options = RunTaskOptions(str(tmp_path), "build")

        assert options.argv == []

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

    async def test_failed_task_includes_captured_stderr(self, write_belgie_pyproject) -> None:
        pyproject = write_belgie_pyproject(scripts={"fail": "sh -c 'echo task exploded >&2; exit 7'"})
        options = RunTaskOptions(str(pyproject.parent), "fail")

        with pytest.raises(BelgieRuntimeError, match="task exploded"):
            await TaskRunner().run(options)

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
