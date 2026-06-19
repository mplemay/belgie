from collections.abc import Awaitable, Coroutine, Iterable, Mapping
from os import PathLike
from types import TracebackType
from typing import Any, Self, overload

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

class BelgieError(Exception): ...
class BelgieRuntimeError(BelgieError): ...
class BelgieModuleError(BelgieError): ...
class BelgieJavaScriptError(BelgieError): ...

class EnvironmentInstallResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def dependencies(self) -> int: ...

class EnvironmentUpdateChange:
    @property
    def name(self) -> str: ...
    @property
    def previous(self) -> str: ...
    @property
    def updated(self) -> str: ...

class EnvironmentUpdateResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def changes(self) -> list[EnvironmentUpdateChange]: ...

class Script[**P, R]:
    def __init__(self, content: str) -> None: ...
    @classmethod
    def from_file(cls: type[Self], path: str | PathLike[str]) -> Self: ...

class SyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...

class AsyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Coroutine[Any, Any, R]: ...

class Command:
    def __init__(
        self,
        name: str,
        *,
        cwd: str | PathLike[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None: ...

class SyncCommandRunner:
    def __call__(self, *args: str) -> None: ...

class AsyncCommandRunner:
    def __call__(self, *args: str) -> Coroutine[Any, Any, None]: ...

class SyncRuntime:
    @overload
    def __call__[**P, R](self, target: Script[P, R]) -> SyncRunner[P, R]: ...
    @overload
    def __call__(self, target: Command) -> SyncCommandRunner: ...

class AsyncRuntime:
    @overload
    def __call__[**P, R](self, target: Script[P, R]) -> AsyncRunner[P, R]: ...
    @overload
    def __call__(self, target: Command) -> AsyncCommandRunner: ...

class RuntimeOptions:
    def __init__(
        self,
        *,
        max_old_generation_size_mb: int | None = None,
        max_young_generation_size_mb: int | None = None,
        code_range_size_mb: int | None = None,
    ) -> None: ...

class Environment:
    def __init__(
        self,
        dependencies: Mapping[str, str] | None = None,
        *,
        lockfile: str | PathLike[str] | None = None,
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    def lock_blocking(self) -> EnvironmentInstallResult: ...
    def install_blocking(self) -> EnvironmentInstallResult: ...
    def update_blocking(
        self,
        packages: Iterable[str] | None = None,
        *,
        latest: bool = False,
        lockfile_only: bool = False,
    ) -> EnvironmentUpdateResult: ...
    def lock(self) -> Awaitable[EnvironmentInstallResult]: ...
    def install(self) -> Awaitable[EnvironmentInstallResult]: ...
    def update(
        self,
        packages: Iterable[str] | None = None,
        *,
        latest: bool = False,
        lockfile_only: bool = False,
    ) -> Awaitable[EnvironmentUpdateResult]: ...

class Runtime:
    def __init__(
        self,
        *,
        env: Environment | None = None,
        options: RuntimeOptions | None = None,
    ) -> None: ...
    @classmethod
    def from_folder(
        cls: type[Self],
        path: str | PathLike[str],
        *,
        options: RuntimeOptions | None = None,
    ) -> Self: ...
    def __enter__(self) -> SyncRuntime: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    async def __aenter__(self) -> AsyncRuntime: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
