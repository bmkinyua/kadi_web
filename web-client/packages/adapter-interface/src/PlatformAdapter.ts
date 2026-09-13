/**
 * KADI - the contract every platform adapter (Discord/Telegram/WeChat/
 * web) implements. packages/renderer never imports a concrete adapter
 * class, only this type -- see KADI_web_port_implementation_plan.md §2.
 *
 * THIS FIRST PASS only builds adapters/web (see that package) and only
 * meaningfully implements getPlayerId/getDisplayName/getWebSocketUrl/
 * onReady -- the methods a lobby-connect-and-see-the-leaderboard slice
 * actually needs. inviteFriend/shareResult/getTheme/
 * getSafeAreaInsets/onSuspend are real, typed, and part of the
 * contract every future adapter must fill in, but WebAdapter's
 * implementations of them are intentionally minimal placeholders for
 * now (see that file) -- there's no invite-a-friend flow to wire them
 * into until packages/renderer has more than one scene.
 */

export interface SafeAreaInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface PlatformTheme {
  background: string;
  surface: string;
  text: string;
  accent: string;
}

export interface ShareResultPayload {
  resultText: string;
  cardImageUrl?: string;
  deepLink: string;
}

export interface PlatformIdentity {
  platform: string;
  externalId: string;
}

export interface PlatformAdapter {
  /** Local player id/name as this platform's SDK reports them --
   * NOT yet server-verified, see server/leaderboard_store.py's
   * identity-key docstring for what that limit means in practice. */
  getPlayerId(): Promise<string>;
  getDisplayName(): Promise<string>;
  getAvatarUrl(): Promise<string | null>;

  /** Returns null for a platform with no stable identity to offer
   * (e.g. a WebAdapter before it's generated/persisted one) -- see
   * that adapter for how it fills this in. Used to populate
   * HelloMsg.platform/external_id; omitted entirely (not sent as
   * empty strings) when null, per protocol.ts's HelloMsg docstring. */
  getPlatformIdentity(): Promise<PlatformIdentity | null>;

  inviteFriend(gameCode: string): Promise<void>;
  shareResult(payload: ShareResultPayload): Promise<void>;

  getTheme(): PlatformTheme;
  getSafeAreaInsets(): SafeAreaInsets;

  onReady(cb: () => void): void;
  onSuspend(cb: () => void): void;

  getWebSocketUrl(): string;

  /**
   * Client-local settings persistence (SettingsScene, Part C of the
   * KADI_web_port_implementation_plan.md Settings task). Deliberately
   * typed as a loose JSON-serializable bag rather than importing
   * packages/renderer's own `SettingsValues` shape (layout/
   * SettingsLayout.ts) -- this package sits BELOW renderer in the
   * dependency graph (renderer depends on @kadi/adapter-interface,
   * never the reverse; see this file's own header comment), so the
   * concrete settings shape/defaults must stay a renderer-side
   * concern. SettingsScene.ts is responsible for merging whatever
   * partial bag comes back here over its own defaults (a fresh
   * install, or a settings file predating a newly-added field, both
   * legitimately return a partial or empty object).
   *
   * Mirrors core/settings_store.py's save_settings()/load_settings()
   * one level up: same "one JSON blob, whole settings object at once"
   * shape, but WHERE it's written is platform-specific (the PC file
   * lives in a per-user app-data directory; WebAdapter's is
   * localStorage -- see that file). Every future adapter
   * (Discord/Telegram/WeChat) must implement both, even if only as a
   * no-op/in-memory stand-in, same as the rest of this interface's
   * intentionally-minimal-for-now methods (see this file's header).
   */
  getSettings(): Promise<Record<string, unknown> | null>;
  saveSettings(settings: Record<string, unknown>): Promise<void>;

  /**
   * Client-local PROGRESS persistence (ProfileScene, Part B of the
   * KADI_web_port_implementation_plan.md §9 Profile task) -- stats,
   * badges, cosmetics, undo tokens. Deliberately a SEPARATE pair of
   * methods from getSettings()/saveSettings() above, not a shared
   * blob: mirrors core/profile_store.py's own file being distinct
   * from core/settings_store.py's (see that module's docstring --
   * "Reset to Defaults" in Settings must never wipe someone's
   * badges/stats, which is only guaranteed if they're genuinely
   * separate storage, not two keys inside one object a future edit
   * could accidentally clear together). Same loose-bag-of-JSON
   * typing, for the same reason (this package sits below
   * packages/renderer in the dependency graph -- see getSettings()'s
   * docstring above); ProfileScene.ts owns the concrete `ProfileData`
   * shape (packages/renderer/src/profileData.ts) and merges whatever
   * partial/absent bag comes back here over its own defaults.
   */
  getProfile(): Promise<Record<string, unknown> | null>;
  saveProfile(profile: Record<string, unknown>): Promise<void>;
}

// Re-exported from this file since this package's package.json points
// its "main"/"types" at PlatformAdapter.ts specifically (see that
// file) rather than a separate index.ts — MsomiStore.ts's contract
// (Chuo/MSOMI local storage, Part B) is a sibling concern at the same
// package level, not a submodule of PlatformAdapter itself, but needs
// the same "renderer imports only this package, never a concrete
// class" treatment. See MsomiStore.ts's own header for why it's a
// separate interface rather than folded into PlatformAdapter above.
export * from './MsomiStore.js';
