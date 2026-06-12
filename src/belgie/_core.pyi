from collections.abc import Awaitable
from os import PathLike
from types import TracebackType
from typing import Self

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

class BelgieError(Exception): ...
class BelgieRuntimeError(BelgieError): ...
class BelgieModuleError(BelgieError): ...
class BelgieJavaScriptError(BelgieError): ...

class PackageInstallResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def dependencies(self) -> int: ...
    @property
    def dev_dependencies(self) -> int: ...

class PackageUpdateChange:
    @property
    def name(self) -> str: ...
    @property
    def previous(self) -> str: ...
    @property
    def updated(self) -> str: ...

class PackageUpdateResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def changes(self) -> list[PackageUpdateChange]: ...

class RunTaskOptions:
    def __init__(
        self,
        task_cwd: str,
        script: str,
        *,
        argv: list[str] | None = None,
        env: dict[str, str] | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None: ...
    @property
    def task_cwd(self) -> str: ...
    @property
    def script(self) -> str: ...
    @property
    def argv(self) -> list[str]: ...

class TaskProcess:
    @property
    def origin(self) -> str: ...
    @property
    def is_running(self) -> bool: ...
    def stop(self) -> Awaitable[None]: ...

class TaskRunner:
    def __init__(self) -> None: ...
    def run(self, options: RunTaskOptions) -> Awaitable[None]: ...
    def start(self, options: RunTaskOptions) -> Awaitable[TaskProcess]: ...

class Script[**P, R]:
    def __init__(self, content: str) -> None: ...
    @classmethod
    def from_file(cls: type[Self], path: str | PathLike[str]) -> Self: ...

class SyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...

class AsyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]: ...

class RuntimeOptions:
    def __init__(
        self,
        *,
        max_old_generation_size_mb: int | None = None,
        max_young_generation_size_mb: int | None = None,
        code_range_size_mb: int | None = None,
    ) -> None: ...

class Runtime[**BoundP, BoundR]:
    def __init__(
        self,
        cwd: str | PathLike[str] | None = None,
        *,
        options: RuntimeOptions | None = None,
    ) -> None: ...
    def __call__[**P, R](self, script: Script[P, R]) -> Runtime[P, R]: ...
    def __enter__(self) -> SyncRunner[BoundP, BoundR]: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    async def __aenter__(self) -> AsyncRunner[BoundP, BoundR]: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

def install_packages(
    cwd: str | PathLike[str] | None = None,
    *,
    include_dev: bool = True,
    lockfile_only: bool = False,
) -> PackageInstallResult: ...
def lock_packages(
    cwd: str | PathLike[str] | None = None,
    *,
    include_dev: bool = True,
) -> PackageInstallResult: ...
def update_packages(
    cwd: str | PathLike[str] | None = None,
    packages: list[str] | None = None,
    *,
    include_dev: bool = True,
    latest: bool = False,
    lockfile_only: bool = False,
) -> PackageUpdateResult: ...
def ainstall_packages(
    cwd: str | PathLike[str] | None = None,
    *,
    include_dev: bool = True,
    lockfile_only: bool = False,
) -> Awaitable[PackageInstallResult]: ...
def alock_packages(
    cwd: str | PathLike[str] | None = None,
    *,
    include_dev: bool = True,
) -> Awaitable[PackageInstallResult]: ...
def aupdate_packages(
    cwd: str | PathLike[str] | None = None,
    packages: list[str] | None = None,
    *,
    include_dev: bool = True,
    latest: bool = False,
    lockfile_only: bool = False,
) -> Awaitable[PackageUpdateResult]: ...
