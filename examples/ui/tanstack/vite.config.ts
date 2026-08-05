import { belgie } from "@belgie/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    belgie({ bundle: "shared" }),
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
