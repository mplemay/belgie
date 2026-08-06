from pathlib import Path
from typing import Final

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FRONTEND_DIR: Final[Path] = PROJECT_ROOT / "dist" / "client"
MAX_PROMPT_LENGTH: Final[int] = 4_000
SANDBOX_TIMEOUT_SECONDS: Final[float] = 30.0
MAX_OUTPUT_BYTES: Final[int] = 512 * 1024
INVALID_HTML_RESPONSE_MESSAGE: Final[str] = "the agent did not return a rendered HTML document"
GENERATION_INSTRUCTIONS: Final[str] = """
You are a generative UI designer for a small FastAPI demo.

Use the render_widget tool for every request. Pass one complete TSX module that default-exports a React
component — do not import or call render(). The widget must be a useful, polished interpretation of the user's
design brief, use only React primitives and inline styles or CSS, and work without network requests. After
render_widget returns HTML, reply with that complete HTML document and nothing else. Do not return Markdown,
source code, or an explanation outside the rendered widget.
""".strip()

agent = Agent(
    "openai:gpt-5",
    instructions=GENERATION_INSTRUCTIONS,
    capabilities=[
        BelgieSandbox(
            enable_rendering=True,
            timeout=SANDBOX_TIMEOUT_SECONDS,
            max_output_bytes=MAX_OUTPUT_BYTES,
        ),
    ],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


class GenerateResponse(BaseModel):
    html: str


async def generate_ui(request: GenerateRequest) -> GenerateResponse:
    result = await agent.run(request.prompt)
    html = result.output
    if not isinstance(html, str) or not html.lstrip().lower().startswith("<!doctype html>"):
        raise ValueError(INVALID_HTML_RESPONSE_MESSAGE)
    return GenerateResponse(html=html)


app = FastAPI(title="Belgie Pydantic AI Generative UI")
app.frontend("/", directory=FRONTEND_DIR, check_dir=False)


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> GenerateResponse:
    try:
        return await generate_ui(request)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"UI generation failed: {error}") from error


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
