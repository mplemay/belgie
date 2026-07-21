import { randomBytes } from "node:crypto";
import { createServer } from "node:http";
import type { Server } from "node:http";

import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import type {
  OAuthClientInformationMixed,
  OAuthClientMetadata,
  OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";

const CALLBACK_TIMEOUT_MS = 5 * 60 * 1000;

interface CallbackServer {
  redirectUrl: string;
  waitForCode: () => Promise<string>;
  close: () => Promise<void>;
}

export class MemoryOAuthProvider implements OAuthClientProvider {
  readonly #redirectUrl: string;
  readonly #metadata: OAuthClientMetadata;
  readonly #state: string;
  readonly #openBrowser: boolean;
  #clientInformation: OAuthClientInformationMixed | undefined;
  #tokens: OAuthTokens | undefined;
  #codeVerifier: string | undefined;

  constructor(options: { redirectUrl: string; state: string; openBrowser: boolean }) {
    this.#redirectUrl = options.redirectUrl;
    this.#state = options.state;
    this.#openBrowser = options.openBrowser;
    this.#metadata = {
      client_name: "Belgie MCP Tool Codegen",
      grant_types: ["authorization_code", "refresh_token"],
      redirect_uris: [options.redirectUrl],
      response_types: ["code"],
      token_endpoint_auth_method: "none",
    };
  }

  get redirectUrl(): string {
    return this.#redirectUrl;
  }

  get clientMetadata(): OAuthClientMetadata {
    return this.#metadata;
  }

  state(): string {
    return this.#state;
  }

  clientInformation(): OAuthClientInformationMixed | undefined {
    return this.#clientInformation;
  }

  saveClientInformation(clientInformation: OAuthClientInformationMixed): void {
    this.#clientInformation = clientInformation;
  }

  tokens(): OAuthTokens | undefined {
    return this.#tokens;
  }

  saveTokens(tokens: OAuthTokens): void {
    this.#tokens = tokens;
  }

  async redirectToAuthorization(authorizationUrl: URL): Promise<void> {
    if (!this.#openBrowser) {
      process.stderr.write(`Authorize MCP code generation at:\n${authorizationUrl.toString()}\n`);
      return;
    }
    const { default: open } = await import("open");
    await open(authorizationUrl.toString());
  }

  saveCodeVerifier(codeVerifier: string): void {
    this.#codeVerifier = codeVerifier;
  }

  codeVerifier(): string {
    if (this.#codeVerifier === undefined) {
      throw new Error("OAuth code verifier was not saved");
    }
    return this.#codeVerifier;
  }
}

async function closeServer(server: Server): Promise<void> {
  if (!server.listening) {
    return;
  }
  return new Promise((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    });
  });
}

export async function startOAuthCallbackServer(state: string): Promise<CallbackServer> {
  let resolveCode: ((code: string) => void) | undefined;
  let rejectCode: ((error: Error) => void) | undefined;
  const codePromise = new Promise<string>((resolve, reject) => {
    resolveCode = resolve;
    rejectCode = reject;
  });

  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (url.pathname !== "/callback") {
      response.writeHead(404).end("Not found");
      return;
    }
    if (url.searchParams.get("state") !== state) {
      response.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
      response.end("Invalid OAuth state");
      return;
    }
    if (url.searchParams.has("error")) {
      const description = url.searchParams.get("error_description");
      const error = url.searchParams.get("error")!;
      response.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
      response.end("OAuth authorization failed");
      rejectCode?.(new Error(description ? `${error}: ${description}` : error));
      return;
    }
    const code = url.searchParams.get("code");
    if (code === null || code.length === 0) {
      response.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
      response.end("Missing OAuth authorization code");
      rejectCode?.(new Error("Missing OAuth authorization code"));
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(
      "<!doctype html><title>Belgie MCP authorization complete</title><p>Authorization complete. You can close this window.</p>",
    );
    resolveCode?.(code);
  });

  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(0, "127.0.0.1");
  });

  const address = server.address();
  if (address === null || typeof address === "string") {
    await closeServer(server);
    throw new Error("OAuth callback server did not expose a loopback port");
  }

  return {
    close: async () => closeServer(server),
    redirectUrl: `http://127.0.0.1:${address.port}/callback`,
    waitForCode: async () => {
      let timeout: ReturnType<typeof setTimeout> | undefined;
      const timeoutPromise = new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => {
          reject(new Error("Timed out waiting for the OAuth callback"));
        }, CALLBACK_TIMEOUT_MS);
      });
      try {
        return await Promise.race([codePromise, timeoutPromise]);
      } finally {
        if (timeout !== undefined) {
          clearTimeout(timeout);
        }
      }
    },
  };
}

export function oauthState(): string {
  return randomBytes(32).toString("base64url");
}
