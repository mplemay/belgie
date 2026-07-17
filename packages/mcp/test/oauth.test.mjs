import assert from "node:assert/strict";
import test from "node:test";

import { startOAuthCallbackServer } from "../dist/oauth.js";

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
