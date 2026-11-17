import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    preserveSymlinks: true,
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: parseInt(process.env.PORT || "8080", 10),
    host: true,
    allowedHosts: true,
    fs: {
      strict: false,
    },
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_TARGET || "http://127.0.0.1:3000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/decoder": {
        target: process.env.VITE_DECODER_TARGET || "http://127.0.0.1:3001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/decoder/, ""),
      },
      "/iam": {
        target: process.env.VITE_IAM_TARGET || "http://127.0.0.1:3002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/iam/, ""),
      },
      "/billing-service": {
        target: process.env.VITE_BILLING_TARGET || "http://127.0.0.1:3003",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/billing-service/, ""),
      },
      "/protocol-ingestion": {
        target: process.env.VITE_INGESTION_TARGET || "http://127.0.0.1:1002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/protocol-ingestion/, ""),
      },
    },
  },
});
