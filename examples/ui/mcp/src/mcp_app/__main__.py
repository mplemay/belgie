from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypedDict

import uvicorn
from mcp.server import MCPServer

from belgie.mcp import BelgieExtension

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
WIDGET: Final[Path] = PROJECT_ROOT / "src" / "mcp_app" / "views" / "widgets" / "get-time" / "widget.tsx"

belgie = BelgieExtension(project=PROJECT_ROOT)


class TimeResult(TypedDict):
    time: str


@belgie.tool(
    widget=WIDGET,
    name="get-time",
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> TimeResult:
    return {"time": datetime.now(tz=UTC).isoformat()}


mcp = MCPServer(name="Get Time Server", extensions=[belgie])


def main() -> None:
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=3001)


if __name__ == "__main__":
    main()
