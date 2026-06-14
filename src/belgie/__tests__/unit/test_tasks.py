from __future__ import annotations

import pytest

from belgie import tasks
from belgie.tasks import RunTaskOptions, TaskProcess, TaskRunner


def test_task_api_is_exported_from_tasks_module() -> None:
    assert tasks.RunTaskOptions is RunTaskOptions
    assert tasks.TaskProcess is TaskProcess
    assert tasks.TaskRunner is TaskRunner


@pytest.mark.parametrize(
    "task_type",
    [
        RunTaskOptions,
        TaskProcess,
        TaskRunner,
    ],
)
def test_task_classes_live_in_tasks_module(task_type: type[object]) -> None:
    assert task_type.__module__ == "belgie.tasks"
