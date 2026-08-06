# Pydantic AI Generative UI

This example combines FastAPI, Pydantic AI, and the Belgie sandbox. A prompt is sent to a Pydantic AI agent,
which authors a TSX widget in the sandbox and returns a self-contained HTML document for the SPA to render.

## Setup

Install the Python and frontend dependencies:

```bash
uv sync
uv run belgie lock
uv run belgie install
```

Set `OPENAI_API_KEY` before generating a widget.

## Development

Start FastAPI and Vite in separate terminals:

```bash
uv run fastapi dev --port 8000
```

```bash
uv run belgie run vite --host 127.0.0.1
```

Open <http://127.0.0.1:5173/> and describe the interface you want in the prompt box. The SPA sends the prompt to
FastAPI, and the generated widget appears in the preview without navigating away from the page.

## Production

Build the SPA and serve it from FastAPI:

```bash
uv run belgie run vite build
uv run fastapi run --port 8000
```

Open <http://127.0.0.1:8000/>.

The generated HTML is loaded into an iframe with scripts enabled but without same-origin access, keeping the
agent-authored preview isolated from the host SPA.
