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
// One JSON blob for every SettingsScene field, same "whole object at
// once" shape as core/settings_store.py's own settings.json -- see
// getSettings()/saveSettings() below and PlatformAdapter.ts's
// docstring on why the concrete shape isn't imported here.
const STORAGE_KEY_SETTINGS = 'kadi.web.settings';
// Own key, deliberately separate from STORAGE_KEY_SETTINGS -- see
// PlatformAdapter.ts's getProfile()/saveProfile() docstring for why
// progress (stats/badges/cosmetics) and preferences (Settings) must
// not share one storage object.
const STORAGE_KEY_PROFILE = 'kadi.web.profile';

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

/**
 * Reads the browser's actual CSS env(safe-area-inset-*) values (Part
 * D) -- notch/home-indicator/rounded-corner insets that iOS Safari
 * (and some Android browsers) expose once index.html's viewport meta
 * tag includes `viewport-fit=cover` (see that file). There's no JS
 * API for these; the standard technique is a hidden probe element
 * whose padding is set to the four env() values, then measured via
 * getComputedStyle() once it's actually laid out. Lazily created once
 * and reused -- these values only change on rotation/fullscreen
 * changes, which is infrequent enough that re-measuring the same
 * element on each getSafeAreaInsets() call (see below) is simpler
 * than wiring a dedicated change listener for four numbers.
 */
let safeAreaProbe: HTMLDivElement | null = null;

function getSafeAreaProbe(): HTMLDivElement | null {
  if (typeof document === 'undefined') return null; // non-browser test/SSR context
  if (safeAreaProbe && document.body.contains(safeAreaProbe)) return safeAreaProbe;
  const el = document.createElement('div');
  el.style.position = 'fixed';
  el.style.pointerEvents = 'none';
  el.style.visibility = 'hidden';
  el.style.left = '0';
  el.style.top = '0';
  el.style.width = '0';
  el.style.height = '0';
  el.style.paddingTop = 'env(safe-area-inset-top, 0px)';
  el.style.paddingRight = 'env(safe-area-inset-right, 0px)';
  el.style.paddingBottom = 'env(safe-area-inset-bottom, 0px)';
  el.style.paddingLeft = 'env(safe-area-inset-left, 0px)';
  document.body.appendChild(el);
  safeAreaProbe = el;
  return el;
}

function readSafeAreaInsets(): SafeAreaInsets {
  const probe = getSafeAreaProbe();
  if (!probe) return { top: 0, right: 0, bottom: 0, left: 0 };
  const style = getComputedStyle(probe);
  const px = (value: string): number => {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  return {
    top: px(style.paddingTop),
    right: px(style.paddingRight),
    bottom: px(style.paddingBottom),
    left: px(style.paddingLeft),
  };
}

function resolveWebSocketUrl(): string {
  // Vite exposes build-time env vars via import.meta.env -- see
  // apps/web-pwa/vite.config.ts. VITE_WS_URL always wins when set
  // (needed for a non-default port, or a game server on a DIFFERENT
  // machine than the one serving this page).
  const fromEnv = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_WS_URL;
  if (fromEnv) return fromEnv;

  // No override set -- default to the SAME HOST this page was itself
  // loaded from (location.hostname), not a hardcoded 'localhost'.
  //
  // This exists specifically because of a real phone-testing failure:
  // hardcoding 'localhost' here meant a phone loading the page at
  // http://192.168.1.102:5173 (reachable thanks to vite.config.ts's
  // `server: { host: true }`) would still try to open a WebSocket to
  // 'localhost' -- which on the PHONE resolves to the phone itself,
  // not the dev machine -- and sit in KadiConnection's reconnect loop
  // forever with no server there to answer. Requiring a manually
  // created .env.local to fix this is a real, easy-to-get-wrong extra
  // step (wrong folder, typo'd variable name, or -- the actual cause
  // observed -- editing it without restarting `npm run dev:web-pwa`,
  // since Vite only reads .env files at startup); deriving the host
  // from location.hostname instead makes the common case (page and
  // game server on the SAME machine, whatever that machine's address
  // happens to be) work with zero configuration, on a phone exactly
  // as much as on the dev machine itself. VITE_WS_URL remains
  // available, and still takes priority above, for anyone who
  // actually needs a different host/port than this default.
  const host = typeof location !== 'undefined' ? location.hostname : 'localhost';
  return `ws://${host}:53010`;
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

  async setDisplayName(name: string): Promise<void> {
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
    return readSafeAreaInsets();
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

  async getSettings(): Promise<Record<string, unknown> | null> {
    const raw = localStorage.getItem(STORAGE_KEY_SETTINGS);
    if (!raw) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      // A non-object value here would mean the key was overwritten by
      // something else entirely (manual devtools edit, a future
      // version writing an incompatible shape) -- treat it the same
      // as "nothing saved yet" rather than handing SettingsScene.ts a
      // value it can't safely spread over its defaults.
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
      return parsed as Record<string, unknown>;
    } catch {
      // Corrupt JSON (shouldn't happen from our own writes, but a
      // manual edit or a future format change could produce this) --
      // same fallback core/settings_store.py's own load_settings()
      // takes on a parse failure: use defaults rather than throw.
      return null;
    }
  }

  async saveSettings(settings: Record<string, unknown>): Promise<void> {
    localStorage.setItem(STORAGE_KEY_SETTINGS, JSON.stringify(settings));
  }

  async getProfile(): Promise<Record<string, unknown> | null> {
    const raw = localStorage.getItem(STORAGE_KEY_PROFILE);
    if (!raw) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      // Same "treat a non-object as nothing saved" rule as
      // getSettings() -- see that method's comment.
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
      return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  async saveProfile(profile: Record<string, unknown>): Promise<void> {
    localStorage.setItem(STORAGE_KEY_PROFILE, JSON.stringify(profile));
  }
}

// Re-exported for the same reason PlatformAdapter.ts re-exports
// MsomiStore.ts's types (see that file's comment): this package's
// package.json points "main"/"types" at this file specifically, and
// apps/web-pwa/src/main.ts (the one file allowed to import concrete
// adapter/store classes — see createMsomiStore.ts's own header) needs
// a single import path for both.
export { createMsomiStore } from './msomi/createMsomiStore.js';

