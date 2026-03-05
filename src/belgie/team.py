"""Team re-exports for belgie consumers."""

_TEAM_IMPORT_ERROR = "belgie.team requires the 'team' extra. Install with: uv add belgie[team]"

try:
    from belgie_team import (  # type: ignore[import-not-found]
        Team,
        TeamClient,
        TeamMemberView,
        TeamPlugin,
        TeamView,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_TEAM_IMPORT_ERROR) from exc

__all__ = [
    "Team",
    "TeamClient",
    "TeamMemberView",
    "TeamPlugin",
    "TeamView",
]
