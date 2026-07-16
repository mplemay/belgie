import { Widget, useWidget } from "@belgie/mcp";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useTool } from "@widgets/tools";

import "../../global.css";

function AppView() {
  const app = useWidget();
  const {
    mutate: getTime,
    data: timeData,
    error: timeError,
    isPending: timePending,
  } = useTool("get-time");
  const [message, setMessage] = useState("");
  const [logMessage, setLogMessage] = useState("");
  const [link, setLink] = useState("https://modelcontextprotocol.io");

  const serverTime = timeData?.result.find((content) => content.type === "text")?.text;

  return (
    <main className="flex flex-col gap-4 p-4">
      <h2 className="font-heading text-lg font-medium">Get Time Example</h2>

      <Card>
        <CardHeader>
          <CardTitle>Server Time</CardTitle>
          <CardDescription>Call the get-time tool on the MCP server.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="font-mono text-sm text-muted-foreground">
            {serverTime ?? "No time fetched yet."}
          </p>
          {timeError && <p className="text-sm text-destructive">{timeError.message}</p>}
          <Button
            disabled={timePending}
            onClick={() => getTime()}
          >
            {timePending ? "Getting Server Time..." : "Get Server Time"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Send Message</CardTitle>
          <CardDescription>Post a user message through the widget app.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="message">Message</FieldLabel>
              <Textarea
                id="message"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Type a message..."
              />
            </Field>
            <Button
              onClick={() => {
                if (message.trim()) {
                  app.sendMessage({ role: "user", content: [{ type: "text", text: message }] });
                }
              }}
            >
              Send Message
            </Button>
          </FieldGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Send Log</CardTitle>
          <CardDescription>Emit an info log to the host client.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="log">Log message</FieldLabel>
              <Input
                id="log"
                value={logMessage}
                onChange={(event) => setLogMessage(event.target.value)}
                placeholder="Log message..."
              />
            </Field>
            <Button
              onClick={() => {
                if (logMessage.trim()) {
                  app.sendLog({ level: "info", data: logMessage });
                }
              }}
            >
              Send Log
            </Button>
          </FieldGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Open Link</CardTitle>
          <CardDescription>Ask the host to open a URL.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="link">URL</FieldLabel>
              <Input
                id="link"
                value={link}
                onChange={(event) => setLink(event.target.value)}
                placeholder="https://..."
              />
            </Field>
            <Button
              onClick={() => {
                if (link.trim()) {
                  app.openLink({ url: link });
                }
              }}
            >
              Open Link
            </Button>
          </FieldGroup>
        </CardContent>
      </Card>
    </main>
  );
}

export default function GetTime() {
  return (
    <Widget
      metadata={{ name: "Get Time", version: "1.0.0" }}
      fallback={<div className="p-4 text-muted-foreground">Connecting...</div>}
      error={(err) => (
        <div className="p-4 text-destructive">
          <strong>ERROR:</strong> {err.message}
        </div>
      )}
    >
      <AppView />
    </Widget>
  );
}
