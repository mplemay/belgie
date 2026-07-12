from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp_types import TextContent

from belgie.mcp import BelgieExtension

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DIST_DIR: Path = PROJECT_ROOT / "dist"
BASE_URL: str = "http://127.0.0.1:3001"

belgie = BelgieExtension(base_url=BASE_URL, project=PROJECT_ROOT)


@belgie.tool(
    widget="get-time",
    name="get-time",
    title="Get Time",
    description="Get the current server time in ISO 8601 format.",
)
def get_time() -> list[TextContent]:
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]


mcp = MCPServer(name="Get Time Server", extensions=[belgie])

app = FastAPI()
app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))
app.frontend("/", directory=DIST_DIR, check_dir=False)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=3001)


if __name__ == "__main__":
    main()
