import { belgie } from "@belgie/mcp/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    belgie(),
    tanstackStart({
      spa: {
        enabled: true,
        prerender: {
          outputPath: "/index",
        },
      },
    }),
    react(),
  ],
});
