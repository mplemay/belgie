# MCP

Runs a small MCP server with a React app resource built by `BelgieExtension`.

Requires `belgie[mcp]` (included in this example's dependencies).

Install the widget build dependencies before starting the server:

```bash
uv run belgie lock
uv run belgie install
```

## Run

```bash
uv run main
```

The server listens on port `3001`. An MCP Apps-capable client can render the `get-time` widget and call the matching
`get-time` server tool.

## What's Happening

`BelgieExtension` binds the Python tool to a widget path:

```python
belgie = BelgieExtension(root=WIDGETS_ROOT)

@belgie.tool(name="get-time", path=Path("get-time/widget.tsx"))
def get_time() -> list[TextContent]:
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]
```

The widget default export calls `render({ widget: <App /> })`, which Belgie bundles with Vite through the local
`@belgie/widget` package into a complete inline HTML document served as an MCP app resource.
