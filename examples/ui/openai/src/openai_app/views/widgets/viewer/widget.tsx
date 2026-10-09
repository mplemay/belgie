import { Widget, useToolResult } from "@belgie/mcp";
import { stlViewer } from "@widgets/tools";
import { useCallback, useEffect, useState } from "react";

import "@/global.css";
import { useOpenAI } from "@/hooks/use-openai";

interface LoadedFile {
  text: string;
  etag: string | undefined;
  writable: boolean;
}

function Viewer() {
  const openai = useOpenAI();
  const resources = openai.resources;
  const { data, isFetching, execute } = useToolResult(stlViewer);
  const file = data?.file ?? undefined;
  const resourceUri = file?.resourceUri;
  const [loaded, setLoaded] = useState<LoadedFile>();
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    if (!resourceUri || !resources) {
      return;
    }
    // ChatGPT answers reads of the opaque file URI itself; the MCP server never sees them.
    const { contents } = await resources.read({ uri: resourceUri, representation: "text" });
    const content = contents[0];
    const text = content !== undefined && "text" in content ? content.text : "";
    setLoaded({ text, etag: content?.openaiMetadata?.etag, writable: content?.openaiMetadata?.writable ?? false });
    setDraft(text);
  }, [resourceUri, resources]);

  useEffect(() => {
    if (!resourceUri || !resources) {
      return;
    }
    void load();
    const dispose = resources.addUpdateHandler(async ({ params }) => {
      if (params.uri === resourceUri) {
        setStatus("File changed on disk; reloaded.");
        await load();
      }
    });
    void resources.subscribe({ uri: resourceUri });
    return () => {
      dispose();
      void resources.unsubscribe({ uri: resourceUri });
    };
  }, [load, resourceUri, resources]);

  async function save() {
    if (!resourceUri || !resources || !loaded) {
      return;
    }
    const result = await resources.write(resourceUri, {
      text: draft,
      ...(loaded.etag === undefined ? {} : { ifMatch: loaded.etag }),
    });
    if (result.outcome === "too-large") {
      setStatus(`The file exceeds the ${result.maxBytes}-byte write limit.`);
    } else if (result.outcome === "conflict") {
      setStatus("The file changed since it was opened. Reload before saving.");
    } else {
      setLoaded({ ...loaded, text: draft, etag: result.etag });
      setStatus("Saved.");
    }
  }

  if (!file) {
    return <p className="main muted">Open an .stl file in ChatGPT desktop to view it here.</p>;
  }
  if (!resources) {
    return <p className="main muted">This host does not provide file resources for {file.name}.</p>;
  }

  return (
    <main className="main">
      <header className="header">
        <h2>{file.name}</h2>
        <div className="actions">
          {/* Calls from this app carry the file's absolute path, which the server echoes back. */}
          <button
            disabled={isFetching}
            onClick={() => void execute()}
          >
            Locate file
          </button>
          <button
            disabled={!data?.path || !openai.files}
            onClick={() => {
              if (data?.path) {
                void openai.files?.open(data.path);
              }
            }}
          >
            Open in default app
          </button>
        </div>
      </header>
      {data?.path && <p className="muted">{data.path}</p>}
      <textarea
        value={draft}
        readOnly={!loaded?.writable}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
      />
      <div className="actions">
        <button
          className="primary"
          disabled={!loaded?.writable || draft === loaded.text}
          onClick={() => void save()}
        >
          Save
        </button>
        <button onClick={() => void load()}>Reload</button>
      </div>
      {status && <p className="muted">{status}</p>}
    </main>
  );
}

export default function StlViewer() {
  return (
    <Widget
      metadata={{ name: "STL Viewer", version: "1.0.0" }}
      fallback={<p className="main muted">Connecting...</p>}
    >
      <Viewer />
    </Widget>
  );
}
