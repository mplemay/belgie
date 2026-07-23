import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { belgie } from "../src/vite.ts";

const INTERNAL_PACKAGE_TYPE_ENV = "BELGIE_INTERNAL_PACKAGE_TYPE";
const INTERNAL_WIDGET_PATH_ENV = "BELGIE_INTERNAL_WIDGET_PATH";
const temporaryDirectories: string[] = [];

function temporaryProject(): string {
  const root = mkdtempSync(join(tmpdir(), "belgie-mcp-vite-"));
  temporaryDirectories.push(root);
  return root;
}

function writeWidget(root: string, name: string, source: string): string {
  const directory = join(root, "src", "widgets", name);
  mkdirSync(directory, { recursive: true });
  const filePath = join(directory, "widget.tsx");
  writeFileSync(filePath, source);
  return filePath;
}

function configHook(plugin: ReturnType<typeof belgie>) {
  const hook = plugin.config;
  assert.ok(hook && typeof hook === "object" && "handler" in hook);
  return hook.handler;
}

function outputOptionsHook(plugin: ReturnType<typeof belgie>) {
  const hook = plugin.outputOptions;
  assert.ok(hook && typeof hook === "object" && "handler" in hook);
  return hook.handler;
}

function generateBundleHook(plugin: ReturnType<typeof belgie>) {
  const hook = plugin.generateBundle;
  assert.ok(hook && typeof hook === "object" && "handler" in hook);
  return hook.handler;
}

function chunk(overrides: Record<string, unknown> = {}) {
  return {
    code: "console.log('widget')",
    dynamicImports: [],
    facadeModuleId: null,
    fileName: "entry.js",
    imports: [],
    isEntry: true,
    type: "chunk",
    ...overrides,
  };
}

afterEach(() => {
  delete process.env[INTERNAL_PACKAGE_TYPE_ENV];
  delete process.env[INTERNAL_WIDGET_PATH_ENV];
  vi.restoreAllMocks();
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true });
  }
});

describe("Vite configuration and virtual modules", () => {
  it("discovers widgets for development and keeps custom build input", () => {
    const root = temporaryProject();
    const filePath = writeWidget(root, "weather", "export default function Weather() { return null }");
    writeWidget(root, "invalid", "export const Invalid = true");
    const plugin = belgie();
    const result = configHook(plugin)(
      { build: { rolldownOptions: { input: "custom.ts" } }, root },
      { command: "serve", mode: "test" },
    );
    assert.deepEqual(result?.resolve, { dedupe: ["react", "react-dom"] });
    assert.equal(result?.build?.rolldownOptions?.input, "custom.ts");
    assert.deepEqual(result?.optimizeDeps?.include, ["react", "react-dom/client", "react/jsx-runtime"]);
    assert.equal(plugin.resolveId?.("belgie:widget-build-orchestrator"), "\0belgie:widget-build-orchestrator");
    assert.equal(plugin.resolveId?.("/_belgie/widget/missing"), null);
    assert.equal(plugin.resolveId?.("ordinary"), null);
    assert.equal(plugin.resolveId?.("/_belgie/widget/weather?x=1"), "\0belgie:widget:weather");
    assert.equal(plugin.load?.("\0belgie:widget-build-orchestrator"), "export {};\n");
    assert.ok(String(plugin.load?.("\0belgie:widget:weather")).includes(filePath.replaceAll("\\", "/")));
    assert.equal(plugin.load?.("\0belgie:widget:missing"), null);
    assert.equal(plugin.load?.("ordinary"), null);
  });

  it("rejects invalid widgets for production builds", () => {
    const root = temporaryProject();
    writeWidget(root, "invalid", "export const Invalid = true");
    const plugin = belgie({ srcDir: join(root, "src", "widgets") });
    assert.throws(() => configHook(plugin)({ root }, { command: "build", mode: "test" }), /missing a default export/u);
  });

  it("configures JavaScript server output in module mode", () => {
    process.env[INTERNAL_PACKAGE_TYPE_ENV] = "module";
    const plugin = belgie();
    const output = outputOptionsHook(plugin).call({ environment: { config: { consumer: "server" } } } as never, {
      chunkFileNames: "chunks/[name]-[hash].mjs",
      entryFileNames: "server/[name].mjs",
    });
    assert.ok(output);
    assert.equal(output.entryFileNames, "server/[name].js");
    assert.equal(output.chunkFileNames, "chunks/[name]-[hash].js");
    assert.equal(
      outputOptionsHook(plugin).call({ environment: { config: { consumer: "client" } } } as never, {}),
      undefined,
    );
  });

  it("configures an isolated widget build", () => {
    const root = temporaryProject();
    const filePath = writeWidget(root, "a name", "export default function Widget() { return null }");
    process.env[INTERNAL_WIDGET_PATH_ENV] = filePath;
    const plugin = belgie();
    const result = configHook(plugin)({ root }, { command: "build", mode: "test" });
    assert.equal(result?.appType, "custom");
    assert.equal(result?.build?.rolldownOptions?.input, "/_belgie/widget/a%20name");
    assert.equal(result?.build?.assetsInlineLimit, Number.MAX_SAFE_INTEGER);
    assert.equal(result?.build?.rolldownOptions?.output?.codeSplitting, false);
    assert.equal(result?.environments?.client?.build?.outDir, "dist");
    assert.equal(result?.environments?.client?.build?.rolldownOptions?.input, "/_belgie/widget/a%20name");
  });

  it("rejects an unknown isolated widget path", () => {
    const root = temporaryProject();
    writeWidget(root, "known", "export default function Widget() { return null }");
    process.env[INTERNAL_WIDGET_PATH_ENV] = join(root, "missing.tsx");
    const plugin = belgie();
    assert.throws(() => configHook(plugin)({ root }, { command: "build", mode: "test" }), /requested unknown entry/u);
  });

  it("resolves source directories from resolved configuration", () => {
    const root = temporaryProject();
    const plugin = belgie({ srcDir: "custom/widgets" });
    plugin.configResolved?.({ root });
    assert.equal(plugin.api && (plugin.api as { srcDir: string }).srcDir, "custom/widgets");
    const cwdPlugin = belgie({ srcDir: join(root, "missing") });
    configHook(cwdPlugin)({ root: "" }, { command: "serve", mode: "test" });
  });
});

describe("production bundle rendering", () => {
  function isolatedPlugin() {
    const root = temporaryProject();
    const filePath = writeWidget(root, "weather", "export default function Widget() { return null }");
    process.env[INTERNAL_WIDGET_PATH_ENV] = filePath;
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "build", mode: "test" });
    return plugin;
  }

  it("inlines JavaScript and CSS and emits one widget document", () => {
    const plugin = isolatedPlugin();
    const bundle = {
      "a.css": { fileName: "a.css", source: "a { color: red }", type: "asset" },
      "b.css": { fileName: "b.css", source: new TextEncoder().encode("b { color: blue }"), type: "asset" },
      "entry.js": chunk({
        imports: ["entry.js"],
        viteMetadata: { importedCss: new Set(["b.css", "a.css"]) },
      }),
    };
    const emitted: unknown[] = [];
    generateBundleHook(plugin).call(
      { emitFile: (file: unknown) => emitted.push(file) } as never,
      {} as never,
      bundle as never,
    );
    assert.deepEqual(Object.keys(bundle), []);
    assert.equal(emitted.length, 1);
    const output = emitted[0] as { fileName: string; source: string };
    assert.equal(output.fileName, "widgets/weather/index.html");
    assert.match(output.source, /console\.log\('widget'\)/u);
    assert.match(output.source, /a \{ color: red \}/u);
    assert.match(output.source, /b \{ color: blue \}/u);
  });

  it("falls back to sorted CSS assets without Vite metadata", () => {
    const plugin = isolatedPlugin();
    const emitted: { source: string }[] = [];
    generateBundleHook(plugin).call(
      { emitFile: (file: { source: string }) => emitted.push(file) } as never,
      {} as never,
      {
        "a.css": { fileName: "a.css", source: "a{}", type: "asset" },
        "entry.js": chunk(),
        "z.css": { fileName: "z.css", source: "z{}", type: "asset" },
      } as never,
    );
    assert.ok(emitted[0].source.indexOf("a{}") < emitted[0].source.indexOf("z{}"));
  });

  it.each([
    [{}, /expected one entry chunk/u],
    [{ a: chunk({ fileName: "a.js" }), b: chunk({ fileName: "b.js" }) }, /received 2/u],
    [{ entry: chunk(), extra: chunk({ fileName: "extra.js", isEntry: false }) }, /emitted extra chunks/u],
    [{ entry: chunk({ imports: ["shared.js"] }) }, /retained imports/u],
    [{ entry: chunk(), image: { fileName: "image.png", source: "image", type: "asset" } }, /emitted non-CSS assets/u],
    [{ entry: chunk({ viteMetadata: { importedCss: new Set(["missing.css"]) } }) }, /references missing CSS asset/u],
  ])("rejects unsafe widget bundles %#", (bundle, pattern) => {
    const plugin = isolatedPlugin();
    assert.throws(
      () => generateBundleHook(plugin).call({ emitFile() {} } as never, {} as never, bundle as never),
      pattern,
    );
  });

  it("rejects a lost isolated widget entry", () => {
    const root = temporaryProject();
    process.env[INTERNAL_WIDGET_PATH_ENV] = join(root, "widget.tsx");
    const plugin = belgie();
    assert.throws(
      () => generateBundleHook(plugin).call({ emitFile() {} } as never, {} as never, {}),
      /lost its widget entry/u,
    );
  });

  it("removes only its generated orchestration chunk", () => {
    const root = temporaryProject();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "build", mode: "test" });
    const bundle = {
      application: chunk({ facadeModuleId: "/app.ts" }),
      orchestration: chunk({ facadeModuleId: "\0belgie:widget-build-orchestrator" }),
    };
    generateBundleHook(plugin).call({} as never, {} as never, bundle as never);
    assert.deepEqual(Object.keys(bundle), ["application"]);

    const custom = belgie();
    configHook(custom)(
      { build: { rolldownOptions: { input: "custom.ts" } }, root },
      { command: "build", mode: "test" },
    );
    const customBundle = {
      orchestration: chunk({ facadeModuleId: "\0belgie:widget-build-orchestrator" }),
    };
    generateBundleHook(custom).call({} as never, {} as never, customBundle as never);
    assert.deepEqual(Object.keys(customBundle), ["orchestration"]);
  });
});

describe("development middleware", () => {
  function mockServer(
    root: string,
    options: { base?: string; refresh?: boolean; transform?: (html: string) => Promise<string> } = {},
  ) {
    const watcherHandlers = new Map<string, () => void>();
    const warnings: string[] = [];
    const information: string[] = [];
    const errors: string[] = [];
    let middleware: (request: any, response: any, next: (error?: unknown) => void) => Promise<void>;
    const server = {
      config: {
        base: options.base ?? "/base",
        logger: {
          error: (message: string) => errors.push(message),
          info: (message: string) => information.push(message),
          warn: (message: string) => warnings.push(message),
        },
        plugins: options.refresh ? [{ name: "vite:react-refresh" }] : [],
        root,
      },
      middlewares: {
        use: (handler: typeof middleware) => {
          middleware = handler;
        },
      },
      transformIndexHtml: vi.fn(async (_path: string, html: string) =>
        options.transform ? options.transform(html) : html,
      ),
      watcher: {
        add: vi.fn(),
        on: (event: string, handler: () => void) => watcherHandlers.set(event, handler),
      },
    };
    return { errors, information, middleware: () => middleware!, server, warnings, watcherHandlers };
  }

  function response() {
    return {
      body: "",
      end(value = "") {
        this.body = value;
      },
      headers: new Map<string, string>(),
      setHeader(name: string, value: string) {
        this.headers.set(name, value);
      },
      statusCode: 0,
    };
  }

  it("serves widgets, delegates other paths, and returns unknown-widget 404s", async () => {
    const root = temporaryProject();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    const mock = mockServer(root, { refresh: true });
    const plugin = belgie();
    plugin.configureServer?.(mock.server);
    const middleware = mock.middleware();

    let delegated = false;
    await middleware({ url: "/ordinary" }, response(), () => {
      delegated = true;
    });
    assert.equal(delegated, true);
    delegated = false;
    await middleware({}, response(), () => {
      delegated = true;
    });
    assert.equal(delegated, true);

    const missing = response();
    await middleware({ url: "/widgets/missing/index.html" }, missing, () => {});
    assert.equal(missing.statusCode, 404);
    assert.equal(missing.body, "Unknown widget: missing");

    const valid = response();
    await middleware({ url: "/widgets/weather/index.html?dev=1" }, valid, () => {});
    assert.equal(valid.statusCode, 200);
    assert.equal(valid.headers.get("Content-Type"), "text/html; charset=utf-8");
    assert.match(valid.body, /\/base\/@react-refresh/u);
    assert.match(valid.body, /\/_belgie\/widget\/weather/u);
  });

  it("reports invalid widgets and later resolution", () => {
    const root = temporaryProject();
    const filePath = writeWidget(root, "weather", "export const Weather = true");
    const mock = mockServer(root);
    const plugin = belgie();
    plugin.configureServer?.(mock.server);
    assert.equal(mock.warnings.length, 1);
    mock.watcherHandlers.get("change")?.();
    assert.equal(mock.warnings.length, 1);
    writeFileSync(filePath, "export default function Weather() { return null }");
    mock.watcherHandlers.get("change")?.();
    assert.equal(mock.information.length, 1);
    assert.equal(mock.watcherHandlers.has("add"), true);
    assert.equal(mock.watcherHandlers.has("unlink"), true);
  });

  it("does not duplicate refresh preambles and forwards transform errors", async () => {
    const root = temporaryProject();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    const existing = mockServer(root, {
      refresh: true,
      transform: async (html) => html.replace("<head>", '<head><meta name="@react-refresh">'),
    });
    belgie().configureServer?.(existing.server);
    const served = response();
    await existing.middleware()({ url: "/widgets/weather/index.html" }, served, () => {});
    assert.equal(served.body.match(/@react-refresh/gu)?.length, 1);

    const failed = mockServer(root, {
      transform: async () => {
        throw new Error("transform failed");
      },
    });
    belgie().configureServer?.(failed.server);
    let forwarded: unknown;
    await failed.middleware()({ url: "/widgets/weather/index.html" }, response(), (error) => {
      forwarded = error;
    });
    assert.match((forwarded as Error).message, /transform failed/u);

    const configured = belgie();
    configHook(configured)({ root }, { command: "serve", mode: "test" });
    const slashBase = mockServer(root, { base: "/", refresh: true });
    configured.configureServer?.(slashBase.server);
    const slashResponse = response();
    await slashBase.middleware()({ url: "/widgets/weather/index.html" }, slashResponse, () => {});
    assert.equal(slashResponse.statusCode, 200);
    assert.match(slashResponse.body, /\/@react-refresh/u);
  });

  it("warns only invalid widget entry transforms", () => {
    const root = temporaryProject();
    const filePath = writeWidget(root, "weather", "export default function Widget() { return null }");
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "serve", mode: "test" });
    const warnings: string[] = [];
    const context = { warn: (message: string) => warnings.push(message) };
    assert.equal(plugin.transform?.call(context as never, "export const Weather = true", filePath), null);
    assert.equal(plugin.transform?.call(context as never, "export default function Weather() {}", filePath), null);
    assert.equal(plugin.transform?.call(context as never, "export const Other = true", join(root, "other.ts")), null);
    assert.equal(warnings.length, 1);
  });
});

describe("isolated production builds", () => {
  it("requires a Vite config file", async () => {
    const root = temporaryProject();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "build", mode: "test" });
    plugin.configResolved?.({ configFile: false, root });
    await assert.rejects(() => plugin.closeBundle?.(), /require a Vite config file/u);
  });

  it("builds every widget as self-contained HTML and restores the environment", async () => {
    const root = temporaryProject();
    writeWidget(
      root,
      "weather",
      'import "./style.css"; export default function Widget() { return <div>Weather</div> }',
    );
    writeWidget(root, "clock", "export default function Widget() { return <div>Clock</div> }");
    writeFileSync(join(root, "src", "widgets", "weather", "style.css"), "div { color: red }");
    const configFile = join(root, "vite.config.ts");
    const packageRoot = resolve(import.meta.dirname, "..");
    const pluginUrl = pathToFileURL(join(packageRoot, "dist", "vite.js")).href;
    const packageEntry = join(packageRoot, "dist", "index.js");
    const reactRoot = join(packageRoot, "node_modules", "react");
    const reactDomRoot = join(packageRoot, "node_modules", "react-dom");
    writeFileSync(
      configFile,
      `import { belgie } from ${JSON.stringify(pluginUrl)}; export default { resolve: { alias: { "@belgie/mcp": ${JSON.stringify(packageEntry)}, "react/jsx-dev-runtime": ${JSON.stringify(join(reactRoot, "jsx-dev-runtime.js"))}, "react/jsx-runtime": ${JSON.stringify(join(reactRoot, "jsx-runtime.js"))}, "react-dom/client": ${JSON.stringify(join(reactDomRoot, "client.js"))}, "react": ${JSON.stringify(join(reactRoot, "index.js"))} } }, plugins: [belgie()] };\n`,
    );
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "build", mode: "production" });
    plugin.configResolved?.({
      configFile,
      logLevel: "silent",
      mode: "production",
      root,
    });
    await plugin.closeBundle?.();
    rmSync(configFile);
    await plugin.closeBundle?.();
    assert.equal(process.env[INTERNAL_WIDGET_PATH_ENV], undefined);
    const weather = readFileSync(resolve(root, "dist/widgets/weather/index.html"), "utf8");
    const clock = readFileSync(resolve(root, "dist/widgets/clock/index.html"), "utf8");
    assert.match(weather, /Weather/u);
    assert.match(weather, /color:red/u);
    assert.doesNotMatch(weather, /<script[^>]+src=/u);
    assert.match(clock, /Clock/u);
  });

  it("restores an existing environment value when a nested build fails", async () => {
    const root = temporaryProject();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    const configFile = join(root, "vite.config.ts");
    writeFileSync(configFile, 'throw new Error("nested config failed");\n');
    const plugin = belgie();
    configHook(plugin)({ root }, { command: "build", mode: "production" });
    plugin.configResolved?.({ configFile, mode: "production", root });
    process.env[INTERNAL_WIDGET_PATH_ENV] = "original";
    await assert.rejects(() => plugin.closeBundle?.(), /nested config failed/u);
    assert.equal(process.env[INTERNAL_WIDGET_PATH_ENV], "original");
  });

  it("skips non-build, unresolved, empty, and isolated close hooks", async () => {
    const root = temporaryProject();
    const serve = belgie();
    configHook(serve)({ root }, { command: "serve", mode: "test" });
    await serve.closeBundle?.();

    const unresolved = belgie();
    writeWidget(root, "weather", "export default function Widget() { return null }");
    configHook(unresolved)({ root }, { command: "build", mode: "test" });
    await unresolved.closeBundle?.();

    const emptyRoot = temporaryProject();
    const empty = belgie();
    configHook(empty)({ root: emptyRoot }, { command: "build", mode: "test" });
    empty.configResolved?.({ configFile: "config.ts", root: emptyRoot });
    await empty.closeBundle?.();

    const filePath = join(root, "src/widgets/weather/widget.tsx");
    process.env[INTERNAL_WIDGET_PATH_ENV] = filePath;
    const isolated = belgie();
    configHook(isolated)({ root }, { command: "build", mode: "test" });
    isolated.configResolved?.({ configFile: "config.ts", root });
    await isolated.closeBundle?.();
  });
});
