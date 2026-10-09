import { Widget, sendMessage, updateModelContext, useDisplayMode, useToolResult } from "@belgie/mcp";
import { partsLibrary } from "@widgets/tools";
import type { PartsLibraryOutputPartView } from "@widgets/tools";
import { useState } from "react";

import "@/global.css";
import { useOpenAI } from "@/hooks/use-openai";

const PART_PATH = /^\/parts\/([^/?#]+)/u;

function attachPart(part: PartsLibraryOutputPartView) {
  return updateModelContext({
    content: [
      {
        type: "text",
        text: `Selected part ${part.id}: ${part.name}, ${part.length}. ${part.description}`,
        // ChatGPT labels the attachment and shows the thumbnail; other hosts ignore `_meta`.
        _meta: {
          "openai/title": part.name,
          ...(part.thumbnail === undefined ? {} : { "openai/thumbnail": { src: part.thumbnail } }),
        },
      },
    ],
  });
}

function draftQuestion(part: PartsLibraryOutputPartView) {
  return sendMessage({
    role: "user",
    content: [{ type: "text", text: `What can I pair with the ${part.name}?` }],
    // Opens an editable draft in a new ChatGPT conversation instead of sending it.
    _meta: { "openai/message": { target: "new", send: false } },
  });
}

function Library() {
  const openai = useOpenAI();
  const { data, error, isLoading } = useToolResult(partsLibrary);
  const [displayMode, setDisplayMode] = useDisplayMode();
  const [selectedId, setSelectedId] = useState<string>();

  // Deep links such as `?path=/parts/washer` select a part when the sidebar app opens.
  const deepLink = openai.deepLink.getCurrent()?.url;
  const linkedId = deepLink === undefined ? undefined : PART_PATH.exec(deepLink)?.[1];
  const activeId = selectedId ?? linkedId;
  const selected = data?.parts.find((part) => part.id === activeId);
  const attached = openai.modelContext?.getCurrent();

  if (isLoading) {
    return <p className="main muted">Loading parts...</p>;
  }
  if (error || !data) {
    return <p className="main muted">{error?.message ?? "No parts returned."}</p>;
  }

  return (
    <main className="main">
      <header className="header">
        <h2>Parts Library</h2>
        <button onClick={() => void setDisplayMode(displayMode === "fullscreen" ? "inline" : "fullscreen")}>
          {displayMode === "fullscreen" ? "Exit fullscreen" : "Fullscreen"}
        </button>
      </header>
      <p className="muted">
        Units: {data.units}. Deep link: {deepLink ?? "none"}.
      </p>

      <section className="grid">
        {data.parts.map((part) => (
          <button
            key={part.id}
            className="card"
            aria-pressed={part.id === activeId}
            onClick={() => {
              setSelectedId(part.id);
            }}
          >
            {part.thumbnail && (
              <img
                src={part.thumbnail}
                alt=""
              />
            )}
            <strong>{part.name}</strong>
            <span className="muted">{part.length}</span>
          </button>
        ))}
      </section>

      {selected && (
        <section className="detail">
          <h3>{selected.name}</h3>
          <p className="muted">{selected.description}</p>
          <div className="actions">
            <button
              className="primary"
              onClick={() => void attachPart(selected)}
            >
              Attach to chat
            </button>
            <button onClick={() => void draftQuestion(selected)}>Draft question in new chat</button>
          </div>
          {attached !== undefined && (
            <p className="muted">
              {attached === null ? "No part attached." : `Attached (update ${attached.updateId}).`}
            </p>
          )}
        </section>
      )}
    </main>
  );
}

export default function PartsLibrary() {
  return (
    <Widget
      metadata={{ name: "Parts Library", version: "1.0.0" }}
      fallback={<p className="main muted">Connecting...</p>}
    >
      <Library />
    </Widget>
  );
}
