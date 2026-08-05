# Changelog

This page summarizes user-visible documentation and upgrade notes. The
[GitHub releases](https://github.com/mplemay/belgie/releases) remain the source for published
release details.

## 0.1.1

- Added documentation for the Python runtime, environments, commands, MCP Apps, agent integrations,
  CLI, and TypeScript packages.
- Documented path-based `widget.tsx` registration and self-contained Vite widget output.
- Documented `@belgie/render` as a separate host-mediated renderer for agent-authored TSX.

## Upgrade guidance

Use the current pages as the source of truth for public APIs. In particular:

- Register MCP widgets with `BelgieExtension.tool(widget=Path(...))`.
- Use `@belgie/mcp` for path-based MCP Apps widgets and `@belgie/render` for inline agent rendering.
- Lock project JavaScript dependencies with `belgie lock` before frozen installs.

For historical changes, see the repository's [commit history](https://github.com/mplemay/belgie/commits/main).
