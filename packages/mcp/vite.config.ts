import { defineConfig } from "vite";

export default defineConfig({
  build: {
    copyPublicDir: false,
    minify: false,
    outDir: "dist",
    rolldownOptions: {
      input: {
        cli: "src/cli.ts",
        codegen: "src/codegen.ts",
        index: "src/index.tsx",
        vite: "src/vite.ts",
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
    ssr: true,
    sourcemap: true,
    target: "es2023",
  },
  ssr: {
    external: true,
    target: "node",
  },
});
