import assert from "node:assert/strict";

import { MemoryOAuthProvider, oauthState, startOAuthCallbackServer } from "../src/oauth.ts";

const openMock = vi.hoisted(() => vi.fn());
vi.mock(import("open"), () => ({ default: openMock }));

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  openMock.mockReset();
});

test("memory OAuth provider stores metadata and credentials", () => {
  const provider = new MemoryOAuthProvider({
    openBrowser: false,
    redirectUrl: "http://127.0.0.1/callback",
    state: "state",
  });
  assert.equal(provider.redirectUrl, "http://127.0.0.1/callback");
  assert.equal(provider.state(), "state");
  assert.deepEqual(provider.clientMetadata.redirect_uris, ["http://127.0.0.1/callback"]);
  assert.equal(provider.clientInformation(), undefined);
  assert.equal(provider.tokens(), undefined);
  assert.throws(() => provider.codeVerifier(), /was not saved/u);

  const clientInformation = { client_id: "client" };
  const tokens = { access_token: "token", token_type: "bearer" };
  provider.saveClientInformation(clientInformation);
  provider.saveTokens(tokens);
  provider.saveCodeVerifier("verifier");
  assert.equal(provider.clientInformation(), clientInformation);
  assert.equal(provider.tokens(), tokens);
  assert.equal(provider.codeVerifier(), "verifier");
});

test("oAuth provider prints authorization URLs when browser opening is disabled", async () => {
  const provider = new MemoryOAuthProvider({
    openBrowser: false,
    redirectUrl: "http://127.0.0.1/callback",
    state: "state",
  });
  const write = vi.spyOn(process.stderr, "write").mockReturnValue(true);
  await provider.redirectToAuthorization(new URL("https://example.com/authorize?q=1"));
  assert.equal(write.mock.calls[0]?.[0], "Authorize MCP code generation at:\nhttps://example.com/authorize?q=1\n");
  assert.equal(openMock.mock.calls.length, 0);
});

test("oAuth provider opens authorization URLs when requested", async () => {
  const provider = new MemoryOAuthProvider({
    openBrowser: true,
    redirectUrl: "http://127.0.0.1/callback",
    state: "state",
  });
  await provider.redirectToAuthorization(new URL("https://example.com/authorize"));
  assert.deepEqual(openMock.mock.calls, [["https://example.com/authorize"]]);
});

test("waitForCode keeps waiting after invalid OAuth state", async () => {
  const callback = await startOAuthCallbackServer("expected-state");
  try {
    const waiting = callback.waitForCode();
    const invalid = await fetch(`${callback.redirectUrl}?state=wrong-state&code=unused`);
    assert.equal(invalid.status, 400);
    const valid = await fetch(`${callback.redirectUrl}?state=expected-state&code=auth-code`);
    assert.equal(valid.status, 200);
    assert.equal(await waiting, "auth-code");
  } finally {
    await callback.close();
  }
});

test("waitForCode rejects on missing OAuth authorization code", async () => {
  const callback = await startOAuthCallbackServer("expected-state");
  try {
    const waiting = assert.rejects(callback.waitForCode(), /Missing OAuth authorization code/u);
    const response = await fetch(`${callback.redirectUrl}?state=expected-state`);
    assert.equal(response.status, 400);
    await waiting;
  } finally {
    await callback.close();
  }
});

test("waitForCode resolves when state and code are valid", async () => {
  const callback = await startOAuthCallbackServer("expected-state");
  try {
    const waiting = callback.waitForCode();
    const response = await fetch(`${callback.redirectUrl}?state=expected-state&code=auth-code`);
    assert.equal(response.status, 200);
    assert.equal(await waiting, "auth-code");
  } finally {
    await callback.close();
  }
});

test("callback server returns 404 for unrelated routes", async () => {
  const callback = await startOAuthCallbackServer("state");
  try {
    const response = await fetch(new URL("/other", callback.redirectUrl));
    assert.equal(response.status, 404);
    assert.equal(await response.text(), "Not found");
  } finally {
    await callback.close();
  }
});

test.each([
  ["access_denied", undefined, "access_denied"],
  ["server_error", "Provider unavailable", "server_error: Provider unavailable"],
])("rejects OAuth callback errors", async (error, description, message) => {
  const callback = await startOAuthCallbackServer("state");
  try {
    const waiting = assert.rejects(callback.waitForCode(), new RegExp(message, "u"));
    const url = new URL(callback.redirectUrl);
    url.searchParams.set("state", "state");
    url.searchParams.set("error", error);
    if (description !== undefined) {
      url.searchParams.set("error_description", description);
    }
    const response = await fetch(url);
    assert.equal(response.status, 400);
    assert.equal(await response.text(), "OAuth authorization failed");
    await waiting;
  } finally {
    await callback.close();
  }
});

test("waitForCode times out and close is idempotent", async () => {
  const callback = await startOAuthCallbackServer("state");
  vi.useFakeTimers();
  const waiting = assert.rejects(callback.waitForCode(), /Timed out waiting/u);
  await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
  await waiting;
  vi.useRealTimers();
  await callback.close();
  await callback.close();
});

test("oauthState returns random URL-safe state", () => {
  const first = oauthState();
  const second = oauthState();
  assert.match(first, /^[A-Za-z0-9_-]{43}$/u);
  assert.notEqual(first, second);
});
