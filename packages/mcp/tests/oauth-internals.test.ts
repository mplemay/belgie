import assert from "node:assert/strict";

import { afterEach, test, vi } from "vitest";

type Listener = (...arguments_: any[]) => void;

class FakeServer {
  readonly listeners = new Map<string, Listener>();
  listening = false;
  requestHandler: Listener | undefined;
  addressValue: unknown = { port: 4321 };
  closeError: Error | undefined;
  listenError: Error | undefined;

  once(name: string, listener: Listener) {
    this.listeners.set(name, listener);
    return this;
  }

  off(name: string, listener: Listener) {
    if (this.listeners.get(name) === listener) this.listeners.delete(name);
    return this;
  }

  listen() {
    if (this.listenError !== undefined) {
      this.listeners.get("error")?.(this.listenError);
    } else {
      this.listening = true;
      this.listeners.get("listening")?.();
    }
    return this;
  }

  address() {
    return this.addressValue;
  }

  close(callback: (error?: Error) => void) {
    this.listening = false;
    callback(this.closeError);
    return this;
  }
}

async function oauthWithServer(server: FakeServer) {
  vi.resetModules();
  vi.doMock("node:http", () => ({
    createServer: (handler: Listener) => {
      server.requestHandler = handler;
      return server;
    },
  }));
  return import("../src/oauth.ts");
}

afterEach(() => {
  vi.doUnmock("node:http");
  vi.resetModules();
});

test("propagates callback server listen failures", async () => {
  const server = new FakeServer();
  server.listenError = new Error("listen failed");
  const { startOAuthCallbackServer } = await oauthWithServer(server);
  await assert.rejects(startOAuthCallbackServer("state"), /listen failed/u);
  assert.equal(server.listeners.has("listening"), false);
});

test("rejects callback servers without an address", async () => {
  const server = new FakeServer();
  server.addressValue = null;
  const { startOAuthCallbackServer } = await oauthWithServer(server);
  await assert.rejects(startOAuthCallbackServer("state"), /did not expose a loopback port/u);
  assert.equal(server.listening, false);
});

test("propagates callback server close failures", async () => {
  const server = new FakeServer();
  server.closeError = new Error("close failed");
  const { startOAuthCallbackServer } = await oauthWithServer(server);
  const callback = await startOAuthCallbackServer("state");
  await assert.rejects(callback.close(), /close failed/u);
});

test("handles requests without a URL", async () => {
  const server = new FakeServer();
  const { startOAuthCallbackServer } = await oauthWithServer(server);
  await startOAuthCallbackServer("state");
  const response = {
    status: 0,
    body: "",
    writeHead(status: number) {
      this.status = status;
      return this;
    },
    end(body = "") {
      this.body = body;
    },
  };
  server.requestHandler?.({}, response);
  assert.equal(response.status, 404);
  assert.equal(response.body, "Not found");
});
