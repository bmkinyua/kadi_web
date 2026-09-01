import { defineConfig } from 'vite';

export default defineConfig({
  // VITE_WS_URL overrides adapters/web/src/WebAdapter.ts's dev
  // default (ws://localhost:53010) -- set it in a .env file or the
  // deploy environment for anything other than local dev against
  // `python -m server.kadi_server` with no flags.
  server: { port: 5173 },
  build: { outDir: 'dist', sourcemap: true },
});
