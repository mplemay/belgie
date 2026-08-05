from pathlib import Path
from typing import Final

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieCapability

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FRONTEND_DIR: Final[Path] = PROJECT_ROOT / "dist" / "client"
MAX_PROMPT_LENGTH: Final[int] = 4_000
GENERATION_INSTRUCTIONS: Final[str] = """
You are a generative UI designer for a small FastAPI demo.

Use the run_code tool for every request. Author one self-contained TSX module that imports render from
"npm:@belgie/render" and returns render({ widget: <Widget />, plugins: [] }). The widget must be a useful,
polished interpretation of the user's design brief, use only React primitives and inline styles or CSS, and work
without network requests. Return the complete HTML string produced by render as the tool result. Do not return
Markdown, source code, or an explanation outside the rendered widget.
""".strip()

agent = Agent(
    "openai:gpt-5",
    instructions=GENERATION_INSTRUCTIONS,
    capabilities=[BelgieCapability()],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


class GenerateResponse(BaseModel):
    html: str


async def generate_ui(request: GenerateRequest) -> GenerateResponse:
    result = await agent.run(request.prompt)
    html = result.output
    if not isinstance(html, str) or not html.lstrip().lower().startswith("<!doctype html>"):
        raise ValueError("the agent did not return a rendered HTML document")
    return GenerateResponse(html=html)


app = FastAPI(title="Belgie Pydantic AI Generative UI")
app.frontend("/", directory=FRONTEND_DIR, check_dir=False)


@app.post("/api/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest) -> GenerateResponse:
    try:
        return await generate_ui(request)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"UI generation failed: {error}") from error


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
