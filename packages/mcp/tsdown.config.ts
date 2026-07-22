import { defineConfig } from "tsdown";

export default defineConfig({
  attw: {
    level: "error",
    profile: "esm-only",
  },
  clean: true,
  copy: [
    { from: "node_modules/vite/dist/client/client.mjs", to: "dist/vite-client" },
    { from: "node_modules/vite/dist/client/env.mjs", to: "dist/vite-client" },
  ],
  dts: true,
  deps: {
    alwaysBundle(id, importer) {
      if (id === "vite") {
        return importer?.endsWith("/src/builder.ts");
      }
      return id.startsWith("vite/") && importer?.includes("/node_modules/vite/");
    },
    neverBundle: [/^(?:lightningcss|rolldown)(?:\/|$)/u],
  },
  entry: {
    builder: "src/builder.ts",
    cli: "src/cli.ts",
    codegen: "src/codegen.ts",
    index: "src/index.tsx",
    internal: "src/internal.ts",
    vite: "src/vite.ts",
  },
  exports: {
    bin: {
      "belgie-mcp": "src/cli.ts",
    },
    exclude: ["cli"],
    legacy: true,
    packageJson: true,
  },
  fixedExtension: false,
  format: "esm",
  platform: "node",
  plugins: [
    {
      name: "belgie:inline-vite-version",
      transform(code, id) {
        if (!id.replaceAll("\\", "/").endsWith("/vite/dist/node/chunks/logger.js")) {
          return null;
        }
        const transformed = code
          .replace(/const \{ version \} = JSON\.parse\(readFileSync\([^;]+;/u, 'const version = "8.1.3";')
          .replace(
            /const VITE_PACKAGE_DIR = [^;]+;\nconst CLIENT_ENTRY = [^;]+;\nconst ENV_ENTRY = [^;]+;\nconst CLIENT_DIR = [^;]+;/u,
            [
              'const VITE_PACKAGE_DIR = resolve(fileURLToPath(import.meta.url), "..");',
              'const CLIENT_ENTRY = resolve(VITE_PACKAGE_DIR, "vite-client/client.mjs");',
              'const ENV_ENTRY = resolve(VITE_PACKAGE_DIR, "vite-client/env.mjs");',
              "const CLIENT_DIR = path.dirname(CLIENT_ENTRY);",
            ].join("\n"),
          );
        return {
          code: transformed,
          map: null,
        };
      },
    },
  ],
  publint: {
    level: "error",
  },
  sourcemap: true,
});
