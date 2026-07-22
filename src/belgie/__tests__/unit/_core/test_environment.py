from __future__ import annotations

from typing import Any, cast

import pytest

from belgie import Environment, Runtime, Script, _core
from belgie.__tests__.unit._core.conftest import EMPTY_DENO_LOCK, StringPath
from belgie._core import AsyncEnvironment, SyncEnvironment


@pytest.mark.parametrize("project_path", ["project", StringPath("project")])
def test_environment_accepts_string_and_pathlike_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    project_path: str | StringPath,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    env = Environment(path=project_path)

    assert env.workspace == project
    assert repr(env) == f"Environment(path={project}, dependencies=0, active=False)"
    assert repr(Runtime(env=env)) == f"Runtime(env=Environment(path={project}, dependencies=0))"


def test_environment_workspace_defaults_to_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    env = Environment()

    assert env.workspace == tmp_path
    with env as active_env:
        assert active_env.workspace == tmp_path


def test_environment_path_is_keyword_only() -> None:
    environment_type = cast("Any", Environment)

    with pytest.raises(TypeError):
        environment_type(None, "project")


def test_environment_rejects_removed_dir_argument() -> None:
    environment_type = cast("Any", Environment)

    with pytest.raises(TypeError):
        environment_type(dir="project")


def test_lockfile_requires_dependencies(tmp_path) -> None:
    lockfile = tmp_path / "deno.lock"
    lockfile.write_text(EMPTY_DENO_LOCK, encoding="utf-8")

    with pytest.raises(ValueError, match="requires at least one dependency"):
        Environment(lockfile=lockfile)


def test_runtime_requires_an_active_external_environment() -> None:
    env = Environment()

    with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
        Runtime(env=env).__enter__()


def test_environment_rejects_nested_entry_and_can_be_reused() -> None:
    env = Environment()

    with env as active_env:
        assert isinstance(active_env, SyncEnvironment)
        assert "active=True" in repr(env)
        assert "SyncEnvironment" in repr(active_env)
        with pytest.raises(_core.BelgieRuntimeError, match="already active"):
            env.__enter__()
        with Runtime(env=active_env) as runtime:
            assert runtime(Script("export default () => 'ok';"))() == "ok"

    assert "active=False" in repr(env)
    with env as active_env, Runtime(env=active_env) as runtime:
        assert runtime(Script("export default () => 'again';"))() == "again"


async def test_async_environment_entry_returns_async_environment() -> None:
    async with Environment() as env:
        assert isinstance(env, AsyncEnvironment)
        assert "AsyncEnvironment" in repr(env)
        async with Runtime(env=env) as runtime:
            assert await runtime(Script("export default async () => 'ok';"))() == "ok"


def test_active_runtime_survives_environment_exit() -> None:
    env = Environment()
    active_env = env.__enter__()
    runtime = Runtime(env=active_env)
    active = runtime.__enter__()
    run = active(Script("export default () => 'still running';"))

    env.__exit__(None, None, None)

    assert run() == "still running"
    with pytest.raises(_core.BelgieRuntimeError, match="must be entered"):
        Runtime(env=env).__enter__()
    runtime.__exit__(None, None, None)


def test_environment_package_operations_require_active_context() -> None:
    env = Environment({"std_path": "jsr:@std/path@^1"})

    assert not hasattr(env, "lock")
    assert not hasattr(env, "install")
    assert not hasattr(env, "update")
    assert not hasattr(env, "lock_blocking")
    assert not hasattr(env, "install_blocking")
    assert not hasattr(env, "update_blocking")
