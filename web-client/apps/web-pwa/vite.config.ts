import { defineConfig } from 'vite';

export default defineConfig({
  // VITE_WS_URL overrides adapters/web/src/WebAdapter.ts's default
  // WebSocket target, which otherwise auto-derives from whatever host
  // served this page (see that file's resolveWebSocketUrl()) --
  // needed only when the game server runs on a different host or
  // non-default port than the page itself. See PHONE_TESTING.md.
  server: {
    port: 5173,
    // host: true binds Vite's dev server to 0.0.0.0 instead of just
    // localhost -- required for a phone (or any other device) on the
    // same WiFi to reach it at all. Without this, the dev server only
    // accepts connections from the machine it's running on, and a
    // phone visiting http://<PC-LAN-IP>:5173 gets a connection
    // refused/timeout before the app ever loads (this is a Vite dev-
    // server binding setting, separate from -- and a precondition
    // for even attempting -- the WebSocket game-connection reachability
    // covered by VITE_WS_URL below and PHONE_TESTING.md's fuller
    // walkthrough).
    host: true,
  },
  build: { outDir: 'dist', sourcemap: true },
});
