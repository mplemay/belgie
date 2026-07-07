from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import uvicorn
from mcp.server import MCPServer
from mcp_types import TextContent

from belgie.mcp import BelgieExtension

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

belgie = BelgieExtension(root=PROJECT_ROOT)


@belgie.tool(
    name="get-time",
    path=Path("src/mcp_app/views/widgets/get-time/widget.tsx"),
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> list[TextContent]:
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]


mcp = MCPServer(name="Get Time Server", extensions=[belgie])


def main() -> None:
    uvicorn.run(mcp.streamable_http_app(), port=3001)


if __name__ == "__main__":
    main()
