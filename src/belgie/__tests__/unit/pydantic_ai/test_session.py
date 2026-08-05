from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from belgie.errors import BelgieError
from belgie.pydantic_ai import (
    BelgieSandboxError,
    BelgieSandboxExecutionError,
    BelgieSandboxSession,
    BelgieSandboxTimeoutError,
    BelgieSandboxUnavailableError,
    _session,
)
from belgie.pydantic_ai._session import (
    DEFAULT_RENDER_DEPENDENCIES,
    DEFAULT_VITE_SYS_PERMISSIONS,
    package_name_from_specifier,
)


async def test_default_session_is_restricted_and_temporary(fake_belgie) -> None:
    session = BelgieSandboxSession()

    async with session:
        workspace = session.workspace
        assert workspace is not None
        assert workspace.exists()
        assert session.is_open
        assert await session.run_script("export default () => ({ ok: true })") == {"ok": True}
        environment = fake_belgie.environments[0]
        assert environment.dependencies is None
        assert environment.options.allow_remote is False
        assert environment.options.no_npm is True
        assert environment.install_calls == 0
        options = fake_belgie.runtimes[0].options
        assert options.max_old_generation_size_mb == 128
        assert options.permissions.kwargs == {"allow_read": [str(workspace)]}

    assert not session.is_open
    assert session.workspace is None
    assert not workspace.exists()
    assert fake_belgie.environments[0].exited
    assert fake_belgie.runtimes[0].exited


async def test_package_imports_and_network_are_explicit(fake_belgie) -> None:
    session = BelgieSandboxSession(
        allow_package_imports=True,
        allow_network=True,
        max_old_generation_size_mb=None,
    )
    async with session:
        environment = fake_belgie.environments[0]
        assert environment.options.allow_remote is True
        assert environment.options.no_npm is False
        assert environment.install_calls == 0
        options = fake_belgie.runtimes[0].options
        assert options.max_old_generation_size_mb is None
        assert options.permissions.kwargs["allow_read"] == [str(session.workspace)]
        assert options.permissions.kwargs["allow_net"] == []


async def test_package_imports_do_not_enable_runtime_network(fake_belgie) -> None:
    async with BelgieSandboxSession(allow_package_imports=True):
        options = fake_belgie.runtimes[0].options
        assert "allow_net" not in options.permissions.kwargs


async def test_rendering_uses_side_channel_without_script_ffi(fake_belgie) -> None:
    source = "export default function Widget() { return null; }"

    async with BelgieSandboxSession(enable_rendering=True) as session:
        workspace = session.workspace
        assert workspace is not None
        assert await session.render_widget(source) == "<html>rendered</html>"
        environment = fake_belgie.environments[0]
        assert environment.dependencies == DEFAULT_RENDER_DEPENDENCIES
        assert environment.options.allow_remote is True
        assert environment.options.no_npm is False
        assert environment.install_calls == 1
        assert len(fake_belgie.runtimes) == 2
        script_permissions = fake_belgie.runtimes[0].options.permissions.kwargs
        assert script_permissions == {"allow_read": [str(workspace)]}
        render_permissions = fake_belgie.runtimes[1].options.permissions.kwargs
        assert render_permissions == {
            "allow_read": [str(workspace)],
            "allow_env": [],
            "allow_net": ["localhost"],
            "allow_ffi": [str(workspace / "node_modules")],
            "allow_sys": list(DEFAULT_VITE_SYS_PERMISSIONS),
            "allow_write": [str(workspace)],
        }
        assert len(fake_belgie.command_calls) == 1
        command_name, argv = fake_belgie.command_calls[0]
        assert command_name == "@belgie/vite"
        assert argv[0] == "--widget"
        assert argv[2] == "--out"
        widget_path = Path(argv[1])
        out_path = Path(argv[3])
        assert widget_path.name == "widget.tsx"
        assert out_path.name == "widget.html"
        assert widget_path.parent == out_path.parent
        assert widget_path.parent.parent == workspace
        assert widget_path.parent.name.startswith("render-")
        assert not widget_path.parent.exists()
        assert not any(workspace.glob("render-*"))

    assert all(runtime.exited for runtime in fake_belgie.runtimes)


async def test_concurrent_renders_use_isolated_paths(fake_belgie) -> None:
    source_a = "export default function A() { return null; }"
    source_b = "export default function B() { return null; }"

    async with BelgieSandboxSession(enable_rendering=True) as session:
        workspace = session.workspace
        assert workspace is not None
        results = await asyncio.gather(
            session.render_widget(source_a),
            session.render_widget(source_b),
        )
        assert results == ["<html>rendered</html>", "<html>rendered</html>"]
        assert len(fake_belgie.command_calls) == 2
        render_dirs: list[Path] = []
        for command_name, argv in fake_belgie.command_calls:
            assert command_name == "@belgie/vite"
            widget = Path(argv[1])
            out = Path(argv[3])
            assert widget.name == "widget.tsx"
            assert out.name == "widget.html"
            assert widget.parent == out.parent
            assert widget.parent.parent == workspace
            assert widget.parent.name.startswith("render-")
            render_dirs.append(widget.parent)
        assert render_dirs[0] != render_dirs[1]
        assert not any(workspace.glob("render-*"))


async def test_render_widget_without_side_channel_is_an_error(fake_belgie) -> None:
    runtime = fake_belgie.module.Runtime()
    session = BelgieSandboxSession(runtime=runtime)
    async with session:
        with pytest.raises(BelgieSandboxError, match="Widget rendering is unavailable"):
            await session.render_widget("export default function Widget() { return null; }")


@pytest.mark.parametrize(
    ("specifier", "name"),
    [
        ("npm:@belgie/vite", "@belgie/vite"),
        ("@belgie/vite@1.2.3", "@belgie/vite"),
        ("npm:react@19.2.8", "react"),
        ("react", "react"),
    ],
)
def test_package_name_from_specifier(specifier: str, name: str) -> None:
    assert package_name_from_specifier(specifier) == name


def test_package_name_from_specifier_rejects_jsr() -> None:
    with pytest.raises(ValueError, match="JSR"):
        package_name_from_specifier("jsr:@scope/pkg")


async def test_custom_runtime_is_entered_without_workspace(fake_belgie) -> None:
    runtime = fake_belgie.module.Runtime()
    session = BelgieSandboxSession(runtime=runtime)

    async with session:
        assert session.workspace is None
        assert await session.run_script("export default () => 1") == {"ok": True}
    assert runtime.exited
    assert fake_belgie.environments == []


async def test_rejects_double_enter(fake_belgie) -> None:
    session = BelgieSandboxSession()
    async with session:
        with pytest.raises(BelgieSandboxError, match="already open"):
            await session.__aenter__()


async def test_rejects_concurrent_enter(fake_belgie) -> None:
    fake_belgie.enter_started = asyncio.Event()
    fake_belgie.enter_gate = asyncio.Event()
    runtime = fake_belgie.module.Runtime()
    session = BelgieSandboxSession(runtime=runtime)
    first = asyncio.create_task(session.__aenter__())
    await fake_belgie.enter_started.wait()

    with pytest.raises(BelgieSandboxError, match="already open"):
        await session.__aenter__()
    fake_belgie.enter_gate.set()
    await first
    await session.close()
    assert runtime.exited


async def test_requires_asyncio(fake_belgie, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_loop() -> None:
        message = "no loop"
        raise RuntimeError(message)

    monkeypatch.setattr(asyncio, "get_running_loop", no_loop)
    with pytest.raises(BelgieSandboxError, match="requires an asyncio"):
        await BelgieSandboxSession().__aenter__()


async def test_missing_dependency_clears_entering_guard(fake_belgie, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_belgie() -> object:
        message = "Belgie Sandbox requires Belgie and Python 3.12-3.14."
        raise BelgieSandboxUnavailableError(message)

    monkeypatch.setattr(_session, "_load_belgie", missing_belgie)
    session = BelgieSandboxSession()

    with pytest.raises(BelgieSandboxUnavailableError, match="Python 3.12-3.14"):
        await session.__aenter__()
    with pytest.raises(BelgieSandboxUnavailableError, match="Python 3.12-3.14"):
        await session.__aenter__()


async def test_start_failure_cleans_up(fake_belgie) -> None:
    fake_belgie.start_error = RuntimeError("worker failed")
    session = BelgieSandboxSession()

    with pytest.raises(BelgieSandboxUnavailableError, match="worker failed"):
        await session.__aenter__()
    assert not session.is_open
    assert session.workspace is None
    assert fake_belgie.environments[0].exited


async def test_start_failure_retains_state_when_cleanup_fails(fake_belgie) -> None:
    fake_belgie.start_error = RuntimeError("worker failed")
    fake_belgie.environment_exit_error = RuntimeError("cleanup failed")
    session = BelgieSandboxSession()

    with pytest.raises(BelgieSandboxUnavailableError, match="worker failed.*Cleanup also failed.*cleanup failed"):
        await session.__aenter__()
    assert session.workspace is None
    with pytest.raises(BelgieSandboxError, match="pending cleanup"):
        await session.__aenter__()

    fake_belgie.environment_exit_error = None
    await session.close()
    assert fake_belgie.environments[0].exited


async def test_start_cancellation_is_preserved(fake_belgie) -> None:
    fake_belgie.start_error = asyncio.CancelledError()
    session = BelgieSandboxSession()

    with pytest.raises(asyncio.CancelledError):
        await session.__aenter__()
    assert session.workspace is None
    assert fake_belgie.environments[0].exited


async def test_close_retains_failed_runtime_for_retry(fake_belgie) -> None:
    session = BelgieSandboxSession()
    await session.__aenter__()
    fake_belgie.runtime_exit_error = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await session.close()
    assert session.is_open
    assert session.workspace is None
    assert not fake_belgie.runtimes[0].exited

    fake_belgie.runtime_exit_error = None
    await session.close()
    assert not session.is_open
    assert fake_belgie.runtimes[0].exited


async def test_script_error_is_normalized(fake_belgie) -> None:
    fake_belgie.script_error = BelgieError("boom")
    async with BelgieSandboxSession() as session:
        with pytest.raises(BelgieSandboxExecutionError, match="execution failed"):
            await session.run_script("throw new Error('boom')")


async def test_invalid_json_error_is_normalized(fake_belgie) -> None:
    fake_belgie.script_error = TypeError("BigInt is not JSON")
    async with BelgieSandboxSession() as session:
        with pytest.raises(BelgieSandboxExecutionError, match="invalid JSON"):
            await session.run_script("export default () => 1n")


async def test_timeout_cancels_script(fake_belgie) -> None:
    fake_belgie.hang = True
    async with BelgieSandboxSession() as session:
        with pytest.raises(BelgieSandboxTimeoutError, match="0.01 seconds"):
            await session.run_script("export default async () => await never", timeout=0.01)
    assert fake_belgie.cancelled


async def test_runtime_timeout_error_is_execution_failure(fake_belgie) -> None:
    runtime_error = TimeoutError("runtime failed before the deadline")
    fake_belgie.script_error = runtime_error
    async with BelgieSandboxSession() as session:
        with pytest.raises(BelgieSandboxExecutionError, match="runtime failed before the deadline") as exc_info:
            await session.run_script("export default () => fail()", timeout=10)
    assert exc_info.value.__cause__ is runtime_error
    assert not fake_belgie.cancelled


async def test_caller_cancellation_is_preserved(fake_belgie) -> None:
    fake_belgie.hang = True
    fake_belgie.script_started = asyncio.Event()
    async with BelgieSandboxSession() as session:
        task = asyncio.create_task(session.run_script("export default async () => await never"))
        await fake_belgie.script_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert fake_belgie.cancelled


async def test_rejects_calls_while_closed(fake_belgie) -> None:
    session = BelgieSandboxSession()
    with pytest.raises(BelgieSandboxError, match="not open"):
        await session.run_script("export default () => 1")
    await session.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"allow_package_imports": 1}, "allow_package_imports must be a bool"),
        ({"allow_network": 1}, "allow_network must be a bool"),
        ({"enable_rendering": 1}, "enable_rendering must be a bool"),
        ({"max_old_generation_size_mb": 0}, "must be a positive integer or None"),
    ],
)
async def test_rejects_invalid_session_configuration(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        cast("Any", BelgieSandboxSession)(**kwargs)


async def test_runtime_rejects_owned_settings(fake_belgie) -> None:
    runtime = fake_belgie.module.Runtime()
    with pytest.raises(ValueError, match="cannot be combined with `runtime`"):
        BelgieSandboxSession(runtime=runtime, enable_rendering=True)


@pytest.mark.parametrize(
    ("source", "deadline", "error_type", "message"),
    [
        (1, 1.0, TypeError, "source must be a string"),
        ("code", 0, ValueError, "timeout must be a positive finite number"),
        ("code", True, ValueError, "timeout must be a positive finite number"),
    ],
)
async def test_validates_run_arguments(
    fake_belgie,
    source: object,
    deadline: object,
    error_type: type[Exception],
    message: str,
) -> None:
    async with BelgieSandboxSession() as session:
        with pytest.raises(error_type, match=message):
            await cast("Any", session).run_script(source, timeout=deadline)


def test_public_workspace_contract() -> None:
    assert BelgieSandboxSession().workspace is None
    assert Path is not None
