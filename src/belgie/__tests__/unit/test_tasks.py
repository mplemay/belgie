from __future__ import annotations

from belgie import tasks
from belgie.tasks import RunTaskOptions, TaskProcess, TaskRunner


def test_task_api_is_exported_from_tasks_module() -> None:
    assert tasks.RunTaskOptions is RunTaskOptions
    assert tasks.TaskProcess is TaskProcess
    assert tasks.TaskRunner is TaskRunner
