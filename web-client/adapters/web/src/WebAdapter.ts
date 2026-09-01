/**
 * KADI - PlatformAdapter implementation for the standalone web-pwa
 * target: your own site, with no host platform (Discord/Telegram/
 * WeChat) wrapping it.
 *
 * IDENTITY HONESTY NOTE: unlike Discord/Telegram, a plain browser tab
 * has no platform-issued login to read an id from. What this adapter
 * does instead is generate a random id ONCE and persist it in
 * localStorage, so the SAME BROWSER on the SAME DEVICE is recognized
 * across visits. That is meaningfully weaker than a Discord/Telegram
 * identity: it identifies a device/browser profile, not a person --
 * clearing site data or using a different browser creates a "new"
 * player. Treat `web:<uuid>` leaderboard entries with that caveat in
 * mind; see server/leaderboard_store.py's identity-key docstring for
 * the parallel caveat about server-side verification (this one has an
 * even weaker guarantee than that, since there's no platform backing
 * it at all -- it's self-asserted by the browser, nothing more).
 */
import type {
  PlatformAdapter,
  PlatformIdentity,
  PlatformTheme,
  SafeAreaInsets,
  ShareResultPayload,
} from '@kadi/adapter-interface';

const STORAGE_KEY_ID = 'kadi.web.deviceId';
const STORAGE_KEY_NAME = 'kadi.web.displayName';

function getOrCreateDeviceId(): string {
  const existing = localStorage.getItem(STORAGE_KEY_ID);
  if (existing) return existing;
  const fresh =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  localStorage.setItem(STORAGE_KEY_ID, fresh);
  return fresh;
}

function resolveWebSocketUrl(): string {
  // Vite exposes build-time env vars via import.meta.env -- see
  // apps/web-pwa/vite.config.ts. Falls back to the server's default
  // WS port (server/connection.py's DEFAULT_WS_PORT / KadiServer's
  // port+1000 auto-default -- both currently 53010) for local dev
  // against `python -m server.kadi_server` with no flags.
  const fromEnv = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_WS_URL;
  return fromEnv ?? 'ws://localhost:53010';
}

export class WebAdapter implements PlatformAdapter {
  async getPlayerId(): Promise<string> {
    return getOrCreateDeviceId();
  }

  async getDisplayName(): Promise<string> {
    const stored = localStorage.getItem(STORAGE_KEY_NAME);
    if (stored) return stored;
    const generated = `Player${getOrCreateDeviceId().slice(0, 4)}`;
    localStorage.setItem(STORAGE_KEY_NAME, generated);
    return generated;
  }

  setDisplayName(name: string): void {
    localStorage.setItem(STORAGE_KEY_NAME, name);
  }

  async getAvatarUrl(): Promise<string | null> {
    return null; // no platform to fetch an avatar from
  }

  async getPlatformIdentity(): Promise<PlatformIdentity | null> {
    return { platform: 'web', externalId: getOrCreateDeviceId() };
  }

  async inviteFriend(gameCode: string): Promise<void> {
    const url = `${location.origin}${location.pathname}?join=${encodeURIComponent(gameCode)}`;
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(url);
    }
    // No toast/UI feedback wired up yet -- packages/renderer has one
    // scene so far (see apps/web-pwa/src/main.ts); this just needs to
    // exist and work, the renderer decides how to surface "copied".
  }

  async shareResult(payload: ShareResultPayload): Promise<void> {
    if (navigator.share) {
      try {
        await navigator.share({ text: payload.resultText, url: payload.deepLink });
        return;
      } catch {
        // User cancelled the native share sheet -- fall through to clipboard.
      }
    }
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(`${payload.resultText} ${payload.deepLink}`);
    }
  }

  getTheme(): PlatformTheme {
    // No host platform to read a theme from -- this is the one place
    // KADI's own visual identity applies directly rather than
    // adapting to a host's colors.
    return { background: '#0b3d5c', surface: '#123a52', text: '#ffffff', accent: '#d9a441' };
  }

  getSafeAreaInsets(): SafeAreaInsets {
    return { top: 0, right: 0, bottom: 0, left: 0 };
  }

  onReady(cb: () => void): void {
    // No SDK handshake to wait for -- fires on the next tick (not
    // synchronously) so callers can register this after constructing
    // the adapter without a race, matching how a real SDK handshake
    // (Discord/Telegram) would behave.
    setTimeout(cb, 0);
  }

  onSuspend(cb: () => void): void {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) cb();
    });
  }

  getWebSocketUrl(): string {
    return resolveWebSocketUrl();
  }
}
