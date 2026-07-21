import { Widget, useToolResult } from "@belgie/mcp";

import { getTime } from "../tools";

import "./widget.css";

function buttonLabel(isLoading: boolean, isFetching: boolean): string {
  if (isLoading) {
    return "Waiting…";
  }
  if (isFetching) {
    return "Refreshing…";
  }
  return "Refresh time";
}

function TimeView() {
  const { data, error, isLoading, isFetching, execute } = useToolResult(getTime);

  return (
    <main className="time-card">
      <p className="label">Current server time</p>
      <time>{data?.time ?? (isLoading ? "Waiting for the opening tool result…" : "No time returned.")}</time>
      {error && <p className="error">{error.message}</p>}
      <button
        disabled={isFetching}
        onClick={() => void execute()}
      >
        {buttonLabel(isLoading, isFetching)}
      </button>
    </main>
  );
}

export default function GetTimeWidget() {
  return (
    <Widget
      metadata={{ name: "Get Time", version: "1.0.0" }}
      fallback={<p className="status">Connecting…</p>}
      error={(error) => <p className="status error">{error.message}</p>}
    >
      <TimeView />
    </Widget>
  );
}
