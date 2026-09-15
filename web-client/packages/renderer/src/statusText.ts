/**
 * KADI web-client — minimum-display-duration guard for transient
 * status-line text.
 *
 * BUG THIS FIXES: GameTableScene's `statusText` and InternetLobbyScene's
 * `browseStatusText` both set a message (`'Reconnecting…'`) the instant
 * the transport drops, then clear or overwrite it the instant it
 * recovers (`onServerMessage`'s 'rejoined' handler / `onConnectionState`'s
 * 'open' branch). On a FAST drop/recover cycle both calls can land
 * within the same tick — sometimes even before a single frame paints
 * the first one — so the player never actually sees "Reconnecting…"
 * even though the recovery genuinely happened underneath it. See
 * next_task_prompt2.md's Part A for the two call sites this was
 * observed at.
 *
 * FIX SHAPE: once a message is shown, a later call (blank or not)
 * can't replace it until at least `minDisplayMs` have passed. This
 * gates TEXT VISIBILITY ONLY — the actual reconnect work (sending
 * `hello`/`rejoin_game`, applying `state_sync`, resuming list polling)
 * is untouched and keeps happening on its own schedule; only the
 * `.setText()` call describing it is delayed.
 *
 * `canReplaceStatusText` is the pure timing check, unit-tested
 * directly with no Phaser/DOM involved. `StatusTextGuard` is a thin
 * stateful wrapper each scene builds around its own real `.setText()`
 * and its own clock (Phaser's `this.time.now`) — kept separate from
 * the pure function so the guard's bookkeeping (when was something
 * last actually shown) doesn't need a live Scene to verify either;
 * see __tests__/statusText.test.ts for both being tested directly
 * against a fake clock.
 */

/** Given "when did I last show a message" and "what time is it now",
 * can this new (possibly blank) message win? */
export function canReplaceStatusText(lastShownAtMs: number, nowMs: number, minDisplayMs: number): boolean {
  return nowMs - lastShownAtMs >= minDisplayMs;
}

/** Comfortably inside the brief's suggested 400–600ms window — long
 * enough that a fast reconnect cycle can't blank a message before a
 * frame paints it, short enough that it never reads as sluggish for a
 * genuinely new, unrelated status line. */
export const DEFAULT_MIN_DISPLAY_MS = 500;

export class StatusTextGuard {
  private lastShownAtMs = -Infinity;

  /**
   * @param set    The real setter to call through to once a change is
   *               allowed — e.g. `(text) => this.statusText.setText(text)`.
   * @param now    A clock, called fresh on every check — e.g.
   *               `() => this.time.now` (Phaser's scene clock, not
   *               `Date.now()`, so this respects the same time source
   *               everything else in the scene already runs on).
   * @param minDisplayMs How long a shown message (blank or not) must
   *               stay up before a later call can replace it.
   */
  constructor(
    private readonly set: (text: string) => void,
    private readonly now: () => number,
    private readonly minDisplayMs: number = DEFAULT_MIN_DISPLAY_MS,
  ) {}

  /** Normal path — every status update should go through this.
   * Silently dropped (not queued, not retried) if the guard window
   * hasn't elapsed yet; the next genuinely-new state change will call
   * this again on its own, so nothing needs to be replayed. */
  show(text: string): void {
    const nowMs = this.now();
    if (!canReplaceStatusText(this.lastShownAtMs, nowMs, this.minDisplayMs)) return;
    this.set(text);
    this.lastShownAtMs = nowMs;
  }

  /** Bypasses the guard unconditionally — reserved for the one
   * terminal case that already behaves correctly today and must keep
   * doing so exactly as-is (GameTableScene's "Could not reconnect —
   * <reason>", which then holds for its own explicit 2s before the
   * scene navigates away): it always wins immediately, and resets the
   * clock so nothing else queued behind it is blocked either. */
  showImmediate(text: string): void {
    const nowMs = this.now();
    this.set(text);
    this.lastShownAtMs = nowMs;
  }
}
