from __future__ import annotations

import atexit
import socket
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import TYPE_CHECKING, Final
from urllib.parse import urlunparse

from belgie import Command, Environment, Runtime
from belgie._pyproject import (
    PyprojectError,
    parse_belgie_tool_config,
    parse_tool_table,
    read_pyproject_toml,
    resolve_file_dependency_paths,
)
from belgie.errors import BelgieError
from belgie.mcp._widgets import read_built_widget, read_widget_html

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_VITE_HOST: Final[str] = "127.0.0.1"
DEFAULT_VITE_PORT: Final[int] = 5173
VITE_DEPENDENCY: Final[str] = "vite"
LOCKFILE_NAME: Final[str] = "deno.lock"
DEV_PROBE_TIMEOUT_SECONDS: Final[float] = 0.25
DEV_POLL_INTERVAL_SECONDS: Final[float] = 0.1
DEV_START_TIMEOUT_SECONDS: Final[float] = 60.0
DEV_STOP_TIMEOUT_SECONDS: Final[float] = 5.0
MISSING_DEPENDENCIES_ERROR: Final[str] = (
    "Cannot run Vite for {project}: [tool.belgie.dependencies] is empty or missing."
)
MISSING_VITE_ERROR: Final[str] = (
    "Cannot run Vite for {project}: [tool.belgie.dependencies] must contain a 'vite' entry."
)
DEV_SERVER_CONFLICT_ERROR: Final[str] = (
    "Cannot start Vite for {project} at {url}: this process already manages that address for {managed_project}."
)
DEV_SERVER_START_ERROR: Final[str] = "Unable to start the Vite development server at {url}: {detail}"
DEV_SERVER_TIMEOUT_ERROR: Final[str] = "Timed out waiting for the Vite development server at {url}."

type DevServerKey = tuple[str, int]


@dataclass(slots=True, kw_only=True, frozen=True)
class _ViteProject:
    root: Path
    dependencies: dict[str, str]
    module: bool
    lockfile: Path | None


@dataclass(slots=True, kw_only=True)
class _ViteDevServer:
    project: Path
    host: str
    port: int
    environment: Environment | None = None
    runtime: Runtime | None = None
    thread: threading.Thread | None = None
    error: Exception | None = None
    stopping: bool = False
    state_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(slots=True)
class _ViteLifecycleState:
    atexit_registered: bool = False


DEV_SERVERS_LOCK: Final[threading.Lock] = threading.Lock()
DEV_SERVERS: Final[dict[DevServerKey, _ViteDevServer]] = {}
BUILD_LOCKS_LOCK: Final[threading.Lock] = threading.Lock()
BUILD_LOCKS: Final[dict[Path, threading.Lock]] = {}
BUILT_PROJECTS: Final[set[Path]] = set()
VITE_LIFECYCLE_STATE: Final[_ViteLifecycleState] = _ViteLifecycleState()


def ensure_vite_dev_server(
    project: Path,
    *,
    host: str = DEFAULT_VITE_HOST,
    port: int = DEFAULT_VITE_PORT,
) -> None:
    project_path = project.resolve()
    key = (host, port)
    url = _vite_url(host, port)

    with DEV_SERVERS_LOCK:
        server = DEV_SERVERS.get(key)
        if server is not None and server.thread is not None and not server.thread.is_alive():
            DEV_SERVERS.pop(key)
            server = None
        if server is not None and server.project != project_path:
            msg = DEV_SERVER_CONFLICT_ERROR.format(
                project=project_path,
                url=url,
                managed_project=server.project,
            )
            raise RuntimeError(msg)
        if server is None:
            if _is_address_reachable(host, port):
                return
            server = _ViteDevServer(project=project_path, host=host, port=port)
            thread = threading.Thread(
                target=_run_vite_dev_server,
                args=(server,),
                name=f"belgie-vite-{host}-{port}",
                daemon=True,
            )
            server.thread = thread
            DEV_SERVERS[key] = server
            _register_atexit()
            thread.start()

    _wait_for_vite_dev_server(server, url=url)


def build_vite_once(project: Path) -> None:
    project_path = project.resolve()
    with _project_build_lock(project_path):
        _build_vite_if_needed(project_path)


def load_production_widget(project: Path, widget: Path) -> str:
    project_path = project.resolve()
    with _project_build_lock(project_path):
        _build_vite_if_needed(project_path)
        html = read_built_widget(project_path, widget)
        BUILT_PROJECTS.add(project_path)
        return html


def _project_build_lock(project_path: Path) -> threading.Lock:
    with BUILD_LOCKS_LOCK:
        return BUILD_LOCKS.setdefault(project_path, threading.Lock())


def _build_vite_if_needed(project_path: Path) -> None:
    if project_path in BUILT_PROJECTS:
        return
    vite_project = _load_vite_project(project_path)
    _run_vite_command(vite_project, "build")
    read_widget_html.cache_clear()


def _load_vite_project(project: Path) -> _ViteProject:
    document = read_pyproject_toml(project / "pyproject.toml")
    dependencies = parse_tool_table(document, "belgie", "dependencies")
    if not dependencies:
        msg = MISSING_DEPENDENCIES_ERROR.format(project=project)
        raise RuntimeError(msg)
    if VITE_DEPENDENCY not in dependencies:
        msg = MISSING_VITE_ERROR.format(project=project)
        raise RuntimeError(msg)
    config = parse_belgie_tool_config(document)
    lockfile_path = project / LOCKFILE_NAME
    return _ViteProject(
        root=project,
        dependencies=resolve_file_dependency_paths(dependencies, project),
        module=config.module,
        lockfile=lockfile_path if lockfile_path.is_file() else None,
    )


def _run_vite_command(project: _ViteProject, *args: str) -> None:
    with Environment(project.dependencies, path=project.root, lockfile=project.lockfile) as environment:
        environment.install()
        with Runtime(env=environment) as runtime:
            runtime(Command(VITE_DEPENDENCY, cwd=str(project.root), module=project.module))(*args)


def _run_vite_dev_server(server: _ViteDevServer) -> None:
    try:
        project = _load_vite_project(server.project)
        environment_context = Environment(
            project.dependencies,
            path=project.root,
            lockfile=project.lockfile,
        )
        environment = environment_context.__enter__()
        with server.state_lock:
            server.environment = environment_context
        environment.install()

        runtime_context = Runtime(env=environment)
        runtime = runtime_context.__enter__()
        with server.state_lock:
            server.runtime = runtime_context
        runtime(
            Command(
                VITE_DEPENDENCY,
                cwd=str(project.root),
                module=project.module,
            ),
        )(
            "--host",
            server.host,
            "--port",
            str(server.port),
            "--strictPort",
        )
    except (BelgieError, PyprojectError, RuntimeError, ValueError) as error:
        with server.state_lock:
            if not server.stopping:
                server.error = error
    finally:
        _stop_vite_dev_server(server)


def _wait_for_vite_dev_server(server: _ViteDevServer, *, url: str) -> None:
    deadline = monotonic() + DEV_START_TIMEOUT_SECONDS
    while monotonic() < deadline:
        if _is_address_reachable(server.host, server.port):
            return
        with server.state_lock:
            error = server.error
            thread = server.thread
        if error is not None:
            detail = str(error) or type(error).__name__
            msg = DEV_SERVER_START_ERROR.format(url=url, detail=detail)
            raise RuntimeError(msg) from error
        if thread is not None and not thread.is_alive():
            msg = DEV_SERVER_START_ERROR.format(
                url=url,
                detail="Vite exited before the server became ready.",
            )
            raise RuntimeError(msg)
        sleep(DEV_POLL_INTERVAL_SECONDS)
    msg = DEV_SERVER_TIMEOUT_ERROR.format(url=url)
    raise RuntimeError(msg)


def _is_address_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=DEV_PROBE_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def _vite_url(host: str, port: int) -> str:
    return urlunparse(("http", f"{host}:{port}", "", "", "", ""))


def _stop_vite_dev_server(server: _ViteDevServer) -> None:
    with server.state_lock:
        server.stopping = True
        runtime = server.runtime
        environment = server.environment
        server.runtime = None
        server.environment = None
    if runtime is not None:
        with suppress(Exception):
            runtime.__exit__(None, None, None)
    if environment is not None:
        with suppress(Exception):
            environment.__exit__(None, None, None)


def _shutdown_vite_dev_servers() -> None:
    with DEV_SERVERS_LOCK:
        servers = list(DEV_SERVERS.values())
        DEV_SERVERS.clear()
    for server in servers:
        _stop_vite_dev_server(server)
    for server in servers:
        thread = server.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=DEV_STOP_TIMEOUT_SECONDS)


def _register_atexit() -> None:
    if VITE_LIFECYCLE_STATE.atexit_registered:
        return
    atexit.register(_shutdown_vite_dev_servers)
    VITE_LIFECYCLE_STATE.atexit_registered = True


def _reset_vite_state_for_tests() -> None:
    _shutdown_vite_dev_servers()
    with BUILD_LOCKS_LOCK:
        BUILD_LOCKS.clear()
        BUILT_PROJECTS.clear()
    if VITE_LIFECYCLE_STATE.atexit_registered:
        atexit.unregister(_shutdown_vite_dev_servers)
        VITE_LIFECYCLE_STATE.atexit_registered = False
