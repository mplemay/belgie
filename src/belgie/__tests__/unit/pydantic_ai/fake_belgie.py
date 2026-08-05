from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self


class FakeBelgie:
    def __init__(self) -> None:
        self.result: object = {"ok": True}
        self.render_result: object = "<html>rendered</html>"
        self.script_error: Exception | None = None
        self.render_error: Exception | None = None
        self.start_error: BaseException | None = None
        self.environment_exit_error: BaseException | None = None
        self.runtime_exit_error: BaseException | None = None
        self.enter_started: asyncio.Event | None = None
        self.enter_gate: asyncio.Event | None = None
        self.script_started: asyncio.Event | None = None
        self.hang = False
        self.cancelled = False
        self.environments: list[_Environment] = []
        self.runtimes: list[_Runtime] = []
        self.scripts: list[str] = []
        self.render_calls: list[tuple[str, str]] = []
        self.module = SimpleNamespace(
            Environment=_EnvironmentFactory(self),
            EnvironmentOptions=_EnvironmentOptions,
            Runtime=_RuntimeFactory(self),
            RuntimeOptions=_RuntimeOptions,
            RuntimePermissions=_RuntimePermissions,
            Script=_Script,
        )


class _EnvironmentOptions:
    def __init__(self, *, allow_remote: bool = True, no_npm: bool = False) -> None:
        self.allow_remote = allow_remote
        self.no_npm = no_npm


class _RuntimePermissions:
    def __init__(
        self,
        *,
        allow_read: Sequence[str] | None = None,
        allow_net: Sequence[str] | None = None,
        allow_ffi: Sequence[str] | None = None,
        allow_sys: Sequence[str] | None = None,
        allow_write: Sequence[str] | None = None,
    ) -> None:
        self.kwargs: dict[str, object] = {
            "allow_read": list(allow_read) if allow_read is not None else None,
        }
        for name, value in (
            ("allow_net", allow_net),
            ("allow_ffi", allow_ffi),
            ("allow_sys", allow_sys),
            ("allow_write", allow_write),
        ):
            if value is not None:
                self.kwargs[name] = list(value)


class _RuntimeOptions:
    def __init__(
        self,
        *,
        max_old_generation_size_mb: int | None = None,
        permissions: _RuntimePermissions | None = None,
    ) -> None:
        self.max_old_generation_size_mb = max_old_generation_size_mb
        self.permissions = permissions


class _Environment:
    def __init__(
        self,
        control: FakeBelgie,
        dependencies: dict[str, str] | None,
        *,
        path: str | Path | None,
        options: _EnvironmentOptions | None,
    ) -> None:
        self.control = control
        self.dependencies = dependencies
        self.workspace = Path(path) if path is not None else Path.cwd()
        self.options = options
        self.install_calls = 0
        self.exited = False
        self.exit_calls = 0
        control.environments.append(self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        self.exit_calls += 1
        if self.control.environment_exit_error is not None:
            raise self.control.environment_exit_error
        self.exited = True

    async def install(self) -> object:
        self.install_calls += 1
        return object()


class _Script:
    def __init__(self, content: str, *, from_path: Path | None = None) -> None:
        self.content = content
        self.from_path = from_path

    @classmethod
    def from_file(cls, path: str | Path) -> _Script:
        return cls("", from_path=Path(path))


class _ActiveRuntime:
    def __init__(self, control: FakeBelgie, *, is_render: bool) -> None:
        self.control = control
        self.is_render = is_render

    def __call__(self, script: _Script) -> Callable[..., Any]:
        async def run(*args: object) -> object:
            if self.is_render:
                source = args[0] if args else ""
                url = args[1] if len(args) > 1 else ""
                self.control.render_calls.append((str(source), str(url)))
                if self.control.render_error is not None:
                    raise self.control.render_error
                return self.control.render_result
            self.control.scripts.append(script.content)
            if self.control.script_started is not None:
                self.control.script_started.set()
            if self.control.hang:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.control.cancelled = True
                    raise
            if self.control.script_error is not None:
                raise self.control.script_error
            return self.control.result

        return run


class _Runtime:
    def __init__(
        self,
        control: FakeBelgie,
        *,
        env: _Environment | None,
        options: _RuntimeOptions | None,
    ) -> None:
        self.control = control
        self.env = env
        self.options = options
        self.exited = False
        self.exit_calls = 0
        control.runtimes.append(self)

    @property
    def is_render(self) -> bool:
        permissions = self.options.permissions if self.options is not None else None
        return permissions is not None and "allow_ffi" in permissions.kwargs

    async def __aenter__(self) -> _ActiveRuntime:
        if self.control.enter_started is not None:
            self.control.enter_started.set()
        if self.control.enter_gate is not None:
            await self.control.enter_gate.wait()
        if self.control.start_error is not None:
            raise self.control.start_error
        return _ActiveRuntime(self.control, is_render=self.is_render)

    async def __aexit__(self, *args: object) -> None:
        del args
        self.exit_calls += 1
        if self.control.runtime_exit_error is not None:
            raise self.control.runtime_exit_error
        self.exited = True


class _EnvironmentFactory:
    def __init__(self, control: FakeBelgie) -> None:
        self.control = control

    def __call__(
        self,
        dependencies: dict[str, str] | None = None,
        *,
        path: str | Path | None = None,
        options: _EnvironmentOptions | None = None,
    ) -> _Environment:
        return _Environment(self.control, dependencies, path=path, options=options)


class _RuntimeFactory:
    def __init__(self, control: FakeBelgie) -> None:
        self.control = control

    def __call__(
        self,
        *,
        env: _Environment | None = None,
        options: _RuntimeOptions | None = None,
    ) -> _Runtime:
        return _Runtime(self.control, env=env, options=options)
