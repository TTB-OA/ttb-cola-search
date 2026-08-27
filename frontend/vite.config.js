import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The API base for local dev. During `vite dev` we proxy /api to the FastAPI
// server so the browser can call same-origin paths (no CORS, cookie-friendly).
// /docs and /openapi.json are proxied too so the header's API link works in dev.
const API_TARGET = process.env.VITE_API_PROXY || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
      '/docs': {
        target: API_TARGET,
        changeOrigin: true,
      },
      '/openapi.json': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
