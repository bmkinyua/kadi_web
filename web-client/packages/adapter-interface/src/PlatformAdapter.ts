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
}
