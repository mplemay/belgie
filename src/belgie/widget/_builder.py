from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, ExitStack
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import TYPE_CHECKING, Final, Self, cast

from belgie import Environment, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.errors import BelgieJavaScriptError
from belgie.widget._models import WidgetBundle, WidgetSource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from belgie._core import AsyncRunner, SyncRunner

REACT_VERSION: Final[str] = "19.2.6"
EXT_APPS_VERSION: Final[str] = "1.7.4"
BUILDER_TIMEOUT_MESSAGE: Final[str] = "Widget build exceeded the {timeout:g} second timeout."
BUILDER_NOT_ENTERED_MESSAGE: Final[str] = "Widget builder session must be entered before building widgets."
BUILDER_ALREADY_ENTERED_MESSAGE: Final[str] = "WidgetBuilder is already active."
INVALID_TIMEOUT_MESSAGE: Final[str] = "timeout must be greater than zero"
INVALID_RESULT_MESSAGE: Final[str] = "@belgie/mcp/builder returned an invalid result"
BUILDER_PACKAGE_JSON: Final[str] = '{"private":true,"type":"module","workspaces":[]}\n'
RESERVED_DEPENDENCY_MESSAGE: Final[str] = (
    "dependency alias {alias!r} is reserved by WidgetBuilder and must use {specifier!r}"
)


def _default_mcp_specifier() -> str:
    # src/belgie/widget/_builder.py -> repo root when running from an editable checkout
    local_mcp = Path(__file__).resolve().parents[3] / "packages" / "mcp"
    if (local_mcp / "package.json").is_file():
        return f"file:{local_mcp.as_posix()}"
    return f"npm:@belgie/mcp@{version('belgie')}"


BUILDER_DEPENDENCIES: Final[dict[str, str]] = {
    "@belgie/mcp": _default_mcp_specifier(),
    "@modelcontextprotocol/ext-apps": f"npm:@modelcontextprotocol/ext-apps@{EXT_APPS_VERSION}",
    "@modelcontextprotocol/sdk": "npm:@modelcontextprotocol/sdk@1.29.0",
    "@modelcontextprotocol/sdk/shared/protocol.js": ("npm:@modelcontextprotocol/sdk@1.29.0/shared/protocol.js"),
    "@modelcontextprotocol/sdk/types.js": "npm:@modelcontextprotocol/sdk@1.29.0/types.js",
    "@oxc-project/types": "npm:@oxc-project/types@0.139.0",
    "@rolldown/pluginutils": "npm:@rolldown/pluginutils@1.0.1",
    "detect-libc": "npm:detect-libc@2.1.2",
    "fdir": "npm:fdir@6.5.0",
    "lightningcss": "npm:lightningcss@1.32.0",
    "nanoid": "npm:nanoid@3.3.15",
    "picocolors": "npm:picocolors@1.1.1",
    "picomatch": "npm:picomatch@4.0.5",
    "postcss": "npm:postcss@8.5.17",
    "react": f"npm:react@{REACT_VERSION}",
    "react/jsx-dev-runtime": f"npm:react@{REACT_VERSION}/jsx-dev-runtime",
    "react/jsx-runtime": f"npm:react@{REACT_VERSION}/jsx-runtime",
    "react-dom": f"npm:react-dom@{REACT_VERSION}",
    "react-dom/client": f"npm:react-dom@{REACT_VERSION}/client",
    "rolldown": "npm:rolldown@1.1.5",
    "rolldown/experimental": "npm:rolldown@1.1.5/experimental",
    "rolldown/filter": "npm:rolldown@1.1.5/filter",
    "rolldown/parseAst": "npm:rolldown@1.1.5/parseAst",
    "rolldown/plugins": "npm:rolldown@1.1.5/plugins",
    "rolldown/utils": "npm:rolldown@1.1.5/utils",
    "source-map-js": "npm:source-map-js@1.2.1",
    "tinyglobby": "npm:tinyglobby@0.2.17",
    "zod": "npm:zod@4.4.3",
    "zod/v3": "npm:zod@4.4.3/v3",
    "zod/v4": "npm:zod@4.4.3/v4",
    "zod/v4-mini": "npm:zod@4.4.3/v4-mini",
    "zod/v4/core": "npm:zod@4.4.3/v4/core",
}
BUILDER_SCRIPT: Final[Script[[dict[str, object], float | None], dict[str, str]]] = Script(
    """
export default async function run(input, timeout) {
  const processEnv = Object.getOwnPropertyDescriptor(process, "env");
  Object.defineProperty(process, "env", {
    configurable: true,
    value: { APPVEYOR: "1", NODE_ENV: "production", TERM: "dumb" },
  });
  try {
    const { buildWidget } = await import("@belgie/mcp/builder");
    if (timeout === null) {
      return await buildWidget(input);
    }
    let timer;
    try {
      return await Promise.race([
        buildWidget(input),
        new Promise((_, reject) => {
          timer = setTimeout(
            () => reject(new Error(`Widget build exceeded the ${timeout} second timeout.`)),
            timeout * 1000,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  } finally {
    if (processEnv === undefined) {
      delete process.env;
    } else {
      Object.defineProperty(process, "env", processEnv);
    }
  }
}
""",
)

type ExitArgs = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]


def _builder_dependencies(dependencies: Mapping[str, str]) -> dict[str, str]:
    resolved = dict(BUILDER_DEPENDENCIES)
    for alias, specifier in dependencies.items():
        if alias in BUILDER_DEPENDENCIES and specifier != BUILDER_DEPENDENCIES[alias]:
            raise ValueError(
                RESERVED_DEPENDENCY_MESSAGE.format(alias=alias, specifier=BUILDER_DEPENDENCIES[alias]),
            )
        resolved[alias] = specifier
    return resolved


def _runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        enable_raw_imports=True,
        permissions=RuntimePermissions(
            allow_ffi=[str(root / "node_modules")],
            allow_read=[str(root)],
            allow_sys=["homedir", "uid", "gid", "cpus", "osRelease", "systemMemoryInfo"],
        ),
    )


def _builder_project(root: Path, stack: ExitStack | AsyncExitStack) -> Path:
    project = Path(
        stack.enter_context(TemporaryDirectory(prefix=".belgie-widget-project-", dir=root)),
    )
    (project / "package.json").write_text(BUILDER_PACKAGE_JSON, encoding="utf-8")
    return project


def _payload(source: WidgetSource, root: Path, dependencies: Mapping[str, str]) -> dict[str, object]:
    return {
        "root": str(root),
        "widget": source.widget,
        "files": dict(source.files),
        "dependencies": sorted(alias for alias in dependencies if alias not in BUILDER_DEPENDENCIES),
    }


def _bundle(result: object) -> WidgetBundle:
    if not isinstance(result, dict) or not isinstance(html := result.get("html"), str):
        raise TypeError(INVALID_RESULT_MESSAGE)
    return WidgetBundle(html=html)


def _is_builder_timeout(error: BelgieJavaScriptError, timeout: float | None) -> bool:
    message = str(error)
    return timeout is not None and "Widget build exceeded the " in message and " second timeout." in message


@dataclass(slots=True, kw_only=True)
class _SyncWidgetSession:
    dependencies: Mapping[str, str]
    environment: Environment | None
    timeout: float | None
    _stack: ExitStack | None = field(default=None, init=False, repr=False)
    _environment_owner: Environment | None = field(default=None, init=False, repr=False)
    _root: Path | None = field(default=None, init=False, repr=False)
    _runner: SyncRunner[[dict[str, object], float | None], dict[str, str]] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __enter__(self) -> Self:
        if self._stack is not None:
            return self
        stack = ExitStack()
        try:
            if self.environment is None:
                root = Path(
                    stack.enter_context(TemporaryDirectory(prefix="belgie-widget-")),
                ).resolve()
                environment = Environment(_builder_dependencies(self.dependencies), path=root)
            else:
                environment = self.environment
            self._environment_owner = environment
            active_environment = stack.enter_context(environment)
            active_environment.install()
            environment_root = active_environment.workspace
            root = _builder_project(environment_root, stack)
            runtime = stack.enter_context(
                Runtime(env=active_environment, options=_runtime_options(environment_root)),
            )
            self._runner = runtime(BUILDER_SCRIPT)
            self._root = root
            self._stack = stack
        except BaseException:
            stack.close()
            raise
        return self

    def __exit__(self, *args: object) -> bool | None:
        stack = self._stack
        self._stack = None
        self._environment_owner = None
        self._root = None
        self._runner = None
        if stack is None:
            return None
        return stack.__exit__(*cast("ExitArgs", args))

    def build(self, source: WidgetSource) -> WidgetBundle:
        if self._runner is None or self._root is None:
            raise RuntimeError(BUILDER_NOT_ENTERED_MESSAGE)
        try:
            return _bundle(self._runner(_payload(source, self._root, self.dependencies), self.timeout))
        except BelgieJavaScriptError as error:
            if _is_builder_timeout(error, self.timeout):
                raise TimeoutError(BUILDER_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error
            raise


@dataclass(slots=True, kw_only=True)
class _AsyncWidgetSession:
    dependencies: Mapping[str, str]
    environment: Environment | None
    timeout: float | None
    _stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _environment_owner: Environment | None = field(default=None, init=False, repr=False)
    _root: Path | None = field(default=None, init=False, repr=False)
    _runner: AsyncRunner[[dict[str, object], float | None], dict[str, str]] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    async def __aenter__(self) -> Self:
        if self._stack is not None:
            return self
        stack = AsyncExitStack()
        try:
            if self.environment is None:
                temporary = TemporaryDirectory(prefix="belgie-widget-")
                root = await asyncio.to_thread(Path(temporary.name).resolve)
                stack.callback(temporary.cleanup)
                environment = Environment(_builder_dependencies(self.dependencies), path=root)
            else:
                environment = self.environment
            self._environment_owner = environment
            active_environment = await stack.enter_async_context(environment)
            await active_environment.install()
            environment_root = active_environment.workspace
            root = _builder_project(environment_root, stack)
            runtime = await stack.enter_async_context(
                Runtime(env=active_environment, options=_runtime_options(environment_root)),
            )
            self._runner = runtime(BUILDER_SCRIPT)
            self._root = root
            self._stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._stack
        self._stack = None
        self._environment_owner = None
        self._root = None
        self._runner = None
        if stack is None:
            return None
        return await stack.__aexit__(*cast("ExitArgs", args))

    async def build(self, source: WidgetSource) -> WidgetBundle:
        if self._runner is None or self._root is None:
            raise RuntimeError(BUILDER_NOT_ENTERED_MESSAGE)
        task = self._runner(_payload(source, self._root, self.dependencies), self.timeout)
        if self.timeout is None:
            return _bundle(await task)
        try:
            return _bundle(await asyncio.wait_for(task, timeout=self.timeout))
        except BelgieJavaScriptError as error:
            if _is_builder_timeout(error, self.timeout):
                raise TimeoutError(BUILDER_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error
            raise
        except TimeoutError as error:
            raise TimeoutError(BUILDER_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error


class WidgetBuilder:
    def __init__(
        self,
        *,
        dependencies: Mapping[str, str] | None = None,
        environment: Environment | None = None,
        timeout: float | None = None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(INVALID_TIMEOUT_MESSAGE)
        self.dependencies = _builder_dependencies(dependencies or {})
        self.environment = environment
        self.timeout = timeout
        self._sync_session: _SyncWidgetSession | None = None
        self._async_session: _AsyncWidgetSession | None = None

    def __enter__(self) -> _SyncWidgetSession:
        if self._sync_session is not None or self._async_session is not None:
            raise RuntimeError(BUILDER_ALREADY_ENTERED_MESSAGE)
        session = self.new_sync_session()
        self._sync_session = session
        try:
            return session.__enter__()
        except BaseException:
            self._sync_session = None
            raise

    def __exit__(self, *args: object) -> bool | None:
        session = self._sync_session
        self._sync_session = None
        if session is None:
            return None
        return session.__exit__(*args)

    async def __aenter__(self) -> _AsyncWidgetSession:
        if self._sync_session is not None or self._async_session is not None:
            raise RuntimeError(BUILDER_ALREADY_ENTERED_MESSAGE)
        session = self.new_async_session()
        self._async_session = session
        try:
            return await session.__aenter__()
        except BaseException:
            self._async_session = None
            raise

    async def __aexit__(self, *args: object) -> bool | None:
        session = self._async_session
        self._async_session = None
        if session is None:
            return None
        return await session.__aexit__(*args)

    def new_sync_session(self) -> _SyncWidgetSession:
        return _SyncWidgetSession(
            dependencies=self.dependencies,
            environment=self.environment,
            timeout=self.timeout,
        )

    def new_async_session(self) -> _AsyncWidgetSession:
        return _AsyncWidgetSession(
            dependencies=self.dependencies,
            environment=self.environment,
            timeout=self.timeout,
        )
