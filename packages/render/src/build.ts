import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { build, type Plugin, type PluginOption, type Rollup } from "vite";

import { renderBundle, type BuildArtifact } from "./html.js";
import { CLIENT_ENTRY_ID, createInlineSourcePlugin } from "./source.js";

export type RenderContext = {
  source: string;
  url: string;
  version: 1;
};

const PACKAGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;

export function invariantPlugin(): Plugin {
  return {
    name: "belgie-render-invariants",
    enforce: "post",
    configResolved(config) {
      if (config.configFile !== undefined) {
        throw new Error("@belgie/render: Vite configuration files are disabled");
      }
      if (config.build.write) {
        throw new Error("@belgie/render: plugins cannot enable filesystem output");
      }
      const output = config.build.rolldownOptions.output;
      if (Array.isArray(output) || output?.codeSplitting !== false) {
        throw new Error("@belgie/render: plugins cannot enable code splitting");
      }
    },
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        const html = renderBundle(bundle as unknown as Record<string, BuildArtifact>);
        for (const fileName of Object.keys(bundle)) {
          delete bundle[fileName];
        }
        this.emitFile({ fileName: "widget.html", source: html, type: "asset" });
      },
    },
  };
}

export function readHtml(output: Rollup.RollupOutput | Rollup.RollupOutput[]): string {
  const outputs = Array.isArray(output) ? output : [output];
  const artifacts = outputs.flatMap((result) => result.output);
  if (artifacts.length !== 1) {
    throw new Error(`@belgie/render: expected one HTML artifact, received ${artifacts.length}`);
  }
  const artifact = artifacts[0]!;
  if (artifact.type !== "asset" || artifact.fileName !== "widget.html") {
    throw new Error(`@belgie/render: expected widget.html, received ${artifact.fileName}`);
  }
  return typeof artifact.source === "string" ? artifact.source : new TextDecoder().decode(artifact.source);
}

export async function buildInlineWidget(
  context: RenderContext,
  plugins: PluginOption[],
): Promise<string> {
  const output = await build({
    appType: "custom",
    configFile: false,
    envDir: false,
    logLevel: "silent",
    plugins: [createInlineSourcePlugin(context), react(), ...plugins, invariantPlugin()],
    publicDir: false,
    resolve: { dedupe: ["react", "react-dom"] },
    root: PACKAGE_ROOT,
    build: {
      assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
      copyPublicDir: false,
      cssCodeSplit: false,
      emptyOutDir: false,
      license: false,
      manifest: false,
      modulePreload: false,
      reportCompressedSize: false,
      sourcemap: false,
      ssrManifest: false,
      watch: null,
      write: false,
      rolldownOptions: {
        input: CLIENT_ENTRY_ID,
        output: { codeSplitting: false },
      },
    },
  });
  return readHtml(output as Rollup.RollupOutput | Rollup.RollupOutput[]);
}
