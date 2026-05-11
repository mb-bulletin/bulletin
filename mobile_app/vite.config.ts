import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Vite config. The PWA plugin handles service worker generation and the
// web app manifest; configured to cache today/schedule responses so the
// app works offline (parishioners checking Mass times in a church basement
// with no signal is the exact failure mode we want to avoid).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "Parish Bulletin",
        short_name: "Bulletin",
        description: "Mass times, announcements, and the week's bulletin",
        theme_color: "#7c2d12",
        background_color: "#fafaf9",
        display: "standalone",
        start_url: "/",
        icons: [
          {
            src: "/icon-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "/icon-512.png",
            sizes: "512x512",
            type: "image/png",
          },
        ],
      },
      workbox: {
        runtimeCaching: [
          {
            // Cache today/schedule responses for offline use; stale-while-revalidate
            // means the user gets last known data instantly even on flaky networks.
            urlPattern: /\/v1\/parishes\/.+\/(today|schedule|bulletins\/current)$/,
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "bulletin-api",
              expiration: { maxAgeSeconds: 60 * 60 * 24 * 7 },
            },
          },
        ],
      },
    }),
  ],
});
