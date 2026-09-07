import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The API is proxied rather than called cross-origin. Talking to
// http://localhost:8000 directly puts every request through CORS, and a CORS
// rejection — a dev server that fell back to port 5174, a preview build on
// 4173 — surfaces in the browser as an unexplained "Network Error". Same
// origin, no preflight, no failure mode to explain.
//
// Set VITE_API_URL to point a deployed build at a backend on another host.
const backend = process.env.VITE_PROXY_TARGET || 'http://localhost:8000'

const proxy = {
  '/api': {
    target: backend,
    changeOrigin: true,
    // A debate is streamed over SSE for minutes at a time.
    timeout: 0,
    proxyTimeout: 0,
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: { proxy },
  preview: { proxy },
})
