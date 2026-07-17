import {
  Widget,
  openLink,
  sendLog,
  sendMessage,
  type ToolCallError,
} from "@belgie/mcp";
import { useState } from "react";

import "@/global.css";
import { getTime, type GetTimeOutput } from "@widgets/tools";

function AppView() {
  const [timeData, setTimeData] = useState<GetTimeOutput>();
  const [timeError, setTimeError] = useState<ToolCallError>();
  const [timeLoading, setTimeLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [logMessage, setLogMessage] = useState("");
  const [link, setLink] = useState("https://modelcontextprotocol.io");

  async function refreshTime(): Promise<void> {
    setTimeLoading(true);
    const { result, error } = await getTime();
    setTimeData(result);
    setTimeError(error);
    setTimeLoading(false);
  }

  return (
    <main className="main">
      <h2>Get Time Example</h2>

      <div className="action">
        <h3>Server Time</h3>
        <p>
          <span className="server-time">{timeData?.time ?? "No time fetched yet."}</span>
        </p>
        {timeError && <p className="notice">{timeError.message}</p>}
        <button
          disabled={timeLoading}
          onClick={() => void refreshTime()}
        >
          {timeLoading ? "Getting Server Time..." : "Refresh Server Time"}
        </button>
      </div>

      <div className="action">
        <h3>Send Message</h3>
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Type a message..." />
        <button
          onClick={() => {
            if (message.trim()) {
              sendMessage({ role: "user", content: [{ type: "text", text: message }] });
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
              sendLog({ level: "info", data: logMessage });
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
              openLink({ url: link });
            }
          }}
        >
          Open Link
        </button>
      </div>
    </main>
  );
}

export default function GetTime() {
  return (
    <Widget
      metadata={{ name: "Get Time", version: "1.0.0" }}
      fallback={<div className="notice">Connecting...</div>}
      error={(err) => (
        <div className="notice">
          <strong>ERROR:</strong> {err.message}
        </div>
      )}
    >
      <AppView />
    </Widget>
  );
}
