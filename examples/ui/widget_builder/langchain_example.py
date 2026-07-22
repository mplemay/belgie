from pathlib import Path
from typing import Final

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage

from belgie.langchain import BelgieMiddleware
from belgie.widget import WidgetBuilder, WidgetBundle

EXAMPLE_DIR: Final[Path] = Path(__file__).parent


def project_prompt() -> str:
    widget = (EXAMPLE_DIR / "widget.tsx").read_text(encoding="utf-8")
    component = (EXAMPLE_DIR / "weather-card.tsx").read_text(encoding="utf-8")
    styles = (EXAMPLE_DIR / "styles.css").read_text(encoding="utf-8")
    return f"""Call build_widget once with this virtual project.

widget.tsx:
```tsx
{widget}
```

weather-card.tsx:
```tsx
{component}
```

styles.css:
```css
{styles}
```
"""


agent = create_agent(
    "openai:gpt-5",
    middleware=[BelgieMiddleware(widget_builder=WidgetBuilder())],
)
result = agent.invoke({"messages": [("user", project_prompt())]})
bundle = next(
    message.artifact
    for message in result["messages"]
    if isinstance(message, ToolMessage) and isinstance(message.artifact, WidgetBundle)
)
print(bundle.html)  # noqa: T201
