import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// import seo from './vite-plugin-seo'   (off: see plugins below)

// Backend target for the dev proxy. Defaults to the docker-compose service
// name; set VITE_PROXY_TARGET=http://localhost:8000 to run the dev server on
// the host against a backend reachable at localhost (no CORS, same-origin).
const backend = process.env.VITE_PROXY_TARGET || 'http://backend:8000'
const renderer = process.env.VITE_RENDER_TARGET || 'http://renderer:3100'

// https://vitejs.dev/config/
export default defineConfig({
  // seo() runs on build only. It injects the crawler-visible homepage content
  // into #root and emits the static /alternatives pages, sitemap.xml and
  // llms.txt. See vite-plugin-seo.js.
  // Synapse AI: the build-time SEO pages were OpenShorts' marketing (its cloud prices, its comparisons); they come
  // back when Synapse AI writes its own (seo/, vite-plugin-seo.js).
  plugins: [react()],
  server: {
    // Docker Desktop on Windows (and some Mac setups) doesn't propagate
    // inotify events across a bind mount, so Vite never notices a file saved
    // from the host and keeps serving the stale transformed module forever —
    // no error, no HMR, just silently wrong until the container is restarted.
    // Polling costs a bit of CPU but is the only thing that works there.
    watch: { usePolling: true, interval: 300 },
    allowedHosts: [
      'openshorts.app',
      'www.openshorts.app'
    ],
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/videos': { target: backend, changeOrigin: true },
      '/thumbnails': { target: backend, changeOrigin: true },
      '/gallery': { target: backend, changeOrigin: true },
      '/video': { target: backend, changeOrigin: true },
      '/render': { target: renderer, changeOrigin: true },
    }
  }
})
