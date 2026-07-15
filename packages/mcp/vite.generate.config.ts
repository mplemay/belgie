import { defineConfig } from "vite";

export default defineConfig({
  build: {
    copyPublicDir: false,
    emptyOutDir: false,
    minify: false,
    outDir: "dist",
    rolldownOptions: {
      input: {
        generate: "src/generate.ts",
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
    ssr: true,
    sourcemap: false,
    target: "es2023",
  },
  ssr: {
    noExternal: true,
    target: "node",
  },
});
