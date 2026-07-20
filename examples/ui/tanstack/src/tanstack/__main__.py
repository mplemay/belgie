from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from typing import Final, TypedDict

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp_types import ToolAnnotations

from belgie.mcp import BelgieExtension

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FRONTEND_DIR: Final[Path] = PROJECT_ROOT / "dist" / "client"
WIDGET: Final[Path] = PROJECT_ROOT / "src" / "widgets" / "get-time" / "widget.tsx"
BELGIE_DEV: Final[bool] = environ.get("BELGIE_DEV", "1") == "1"

belgie = BelgieExtension(project=PROJECT_ROOT, dev=BELGIE_DEV)


class TimeResult(TypedDict):
    time: str


@belgie.tool(
    widget=WIDGET,
    name="get-time",
    title="Get Time",
    description="Use this when the user wants the current server time in ISO 8601 format.",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    prefers_border=True,
)
def get_time() -> TimeResult:
    return {"time": datetime.now(tz=UTC).isoformat()}


mcp = MCPServer(name="TanStack Time Server", extensions=[belgie])
mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp_app)
app.frontend("/", directory=FRONTEND_DIR, check_dir=False)
