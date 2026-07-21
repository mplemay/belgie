import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  return (
    <main className="page">
      <section className="card">
        <p className="eyebrow">Belgie example</p>
        <h1>TanStack Start, FastAPI, and MCP UI</h1>
        <p>
          TanStack Start builds this single-page frontend, FastAPI serves the production files, and Belgie builds the
          get-time MCP widget from the same Vite project.
        </p>
        <dl>
          <div>
            <dt>Page</dt>
            <dd>/</dd>
          </div>
          <div>
            <dt>MCP endpoint</dt>
            <dd>/mcp/</dd>
          </div>
          <div>
            <dt>Widget</dt>
            <dd>get-time</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
