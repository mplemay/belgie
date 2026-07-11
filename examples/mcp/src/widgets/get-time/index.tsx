import { render } from "@belgie/mcp";
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useState } from "react";

import "./global.css";

function App() {
  const [toolResult, setToolResult] = useState<CallToolResult | null>(null);
  const [message, setMessage] = useState("");
  const [logMessage, setLogMessage] = useState("");
  const [link, setLink] = useState("https://modelcontextprotocol.io");

  const { app, error } = useApp({
    appInfo: { name: "Get Time", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (createdApp) => {
      createdApp.onerror = console.error;
    },
  });

  if (error) {
    return (
      <div className="notice">
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) {
    return <div className="notice">Connecting...</div>;
  }

  const serverTime = (() => {
    const text = toolResult?.content?.find((content): content is { type: "text"; text: string } => {
      return content.type === "text";
    });
    return text?.text ?? null;
  })();

  return (
    <main className="main">
      <h2>Get Time Example</h2>

      <div className="action">
        <h3>Server Time</h3>
        <p>
          <span className="server-time">{serverTime ?? "No time fetched yet."}</span>
        </p>
        <button
          onClick={async () => {
            const result = await app.callServerTool({ name: "get-time" });
            setToolResult(result);
          }}
        >
          Get Server Time
        </button>
      </div>

      <div className="action">
        <h3>Send Message</h3>
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Type a message..." />
        <button
          onClick={() => {
            if (message.trim()) {
              app.sendMessage({ role: "user", content: [{ type: "text", text: message }] });
            }
          }}
        >
          Send Message
        </button>
      </div>

      <div className="action">
        <h3>Send Log</h3>
        <input value={logMessage} onChange={(event) => setLogMessage(event.target.value)} placeholder="Log message..." />
        <button
          onClick={() => {
            if (logMessage.trim()) {
              app.sendLog({ level: "info", data: logMessage });
            }
          }}
        >
          Send Log
        </button>
      </div>

      <div className="action">
        <h3>Open Link</h3>
        <input value={link} onChange={(event) => setLink(event.target.value)} placeholder="https://..." />
        <button
          onClick={() => {
            if (link.trim()) {
              app.openLink({ url: link });
            }
          }}
        >
          Open Link
        </button>
      </div>
    </main>
  );
}

export default function widget() {
  return render({ metadata: { title: "Get Time" }, widget: <App /> });
}
