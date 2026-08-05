import { useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";

type GenerateResponse = {
  html: string;
};

type ErrorResponse = {
  detail?: string;
};

function isGenerateResponse(value: unknown): value is GenerateResponse {
  return typeof value === "object" && value !== null && "html" in value && typeof value.html === "string";
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return typeof value === "object" && value !== null && (value.detail === undefined || typeof value.detail === "string");
}

function App() {
  const [prompt, setPrompt] = useState("");
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isGenerating) return;

    setError("");
    setIsGenerating(true);
    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmedPrompt }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        const message = isErrorResponse(payload) && payload.detail ? payload.detail : "The UI could not be generated.";
        throw new Error(message);
      }
      if (!isGenerateResponse(payload)) throw new Error("The server returned an invalid UI document.");
      setHtml(payload.html);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "The UI could not be generated.");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="prompt-panel">
        <p className="eyebrow">Belgie + Pydantic AI</p>
        <h1>Describe a UI. See it appear.</h1>
        <p className="lede">The agent writes the widget in the Belgie sandbox, then returns a live preview.</p>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <label htmlFor="prompt">What should we build?</label>
          <textarea
            id="prompt"
            name="prompt"
            rows={5}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="A calm reading list with three books, progress bars, and a weekly goal"
            disabled={isGenerating}
          />
          <button type="submit" disabled={isGenerating || !prompt.trim()}>
            {isGenerating ? "Generating..." : "Generate UI"}
          </button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      <section className="preview-panel" aria-busy={isGenerating} aria-live="polite">
        {html ? (
          <iframe title="Generated UI preview" sandbox="allow-scripts" srcDoc={html} />
        ) : (
          <div className="empty-state">
            <span className="spark">✦</span>
            <p>Your generated interface will appear here.</p>
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
