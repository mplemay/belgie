import path from "node:path";

import { belgie } from "@belgie/mcp/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const viewsDir = path.resolve(import.meta.dirname, "src/shadcn/views");
const widgetsDir = path.resolve(viewsDir, "widgets");

export default defineConfig({
  plugins: [belgie({ srcDir: "src/shadcn/views/widgets" }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": viewsDir,
      "@widgets": widgetsDir,
    },
  },
});
