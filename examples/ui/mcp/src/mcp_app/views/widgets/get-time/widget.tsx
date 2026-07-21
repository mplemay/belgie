import { Widget, openLink, sendLog, sendMessage, useToolResult } from "@belgie/mcp";
import { getTime } from "@widgets/tools";

import "@/global.css";
import { useState } from "react";

function buttonLabel(isLoading: boolean, isFetching: boolean): string {
  if (isLoading) {
    return "Waiting for Server Time...";
  }
  if (isFetching) {
    return "Refreshing Server Time...";
  }
  return "Refresh Server Time";
}

function AppView() {
  const {
    data: timeData,
    error: timeError,
    rawResult,
    status,
    isLoading,
    isFetching,
    execute,
  } = useToolResult(getTime);
  const [message, setMessage] = useState("");
  const [logMessage, setLogMessage] = useState("");
  const [link, setLink] = useState("https://modelcontextprotocol.io");

  return (
    <main className="main">
      <h2>Get Time Example</h2>

      <div className="action">
        <h3>Server Time</h3>
        <p>
          <span className="server-time">
            {timeData?.time ?? (isLoading ? "Waiting for the opening tool result..." : "No time returned.")}
          </span>
        </p>
        {timeError && <p className="notice">{timeError.message}</p>}
        <p>
          Status: {status}; raw response content blocks: {rawResult?.content.length ?? 0}
        </p>
        <button
          disabled={isFetching}
          onClick={() => void execute()}
        >
          {buttonLabel(isLoading, isFetching)}
        </button>
      </div>

      <div className="action">
        <h3>Send Message</h3>
        <textarea
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
          }}
          placeholder="Type a message..."
        />
        <button
          onClick={() => {
            if (message.trim()) {
              void sendMessage({ content: [{ type: "text", text: message }], role: "user" });
            }
          }}
        >
          Send Message
        </button>
      </div>

      <div className="action">
        <h3>Send Log</h3>
        <input
          value={logMessage}
          onChange={(event) => {
            setLogMessage(event.target.value);
          }}
          placeholder="Log message..."
        />
        <button
          onClick={() => {
            if (logMessage.trim()) {
              void sendLog({ data: logMessage, level: "info" });
            }
          }}
        >
          Send Log
        </button>
      </div>

      <div className="action">
        <h3>Open Link</h3>
        <input
          value={link}
          onChange={(event) => {
            setLink(event.target.value);
          }}
          placeholder="https://..."
        />
        <button
          onClick={() => {
            if (link.trim()) {
              void openLink({ url: link });
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
