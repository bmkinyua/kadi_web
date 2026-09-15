/**
 * KADI web-client — the Help Overlay's "stuck?" idle-glow nudge, as a
 * pure, Phaser-free state machine.
 *
 * Direct port of rendering/widgets.py's HelpOverlay.update_idle_glow()/
 * notice_activity()/is_glowing/draw_button_glow() (scenes.py wires
 * update_idle_glow(dt) every frame and notice_activity() on every real
 * input event — see e.g. ChuoScene.update()/handle_event() there for
 * the reference wiring this file's own consumers mirror).
 *
 * Same "pure function(s) + thin stateful wrapper" split as this
 * package's own statusText.ts (StatusTextGuard) — kept here for the
 * same reason: a timer with a 30s trigger / 3s duration / reset-on-
 * activity / suppressed-while-open contract is exactly the kind of
 * thing that should have a real unit test with fake deltas rather
 * than only a visual check in a live Scene.
 *
 * One deliberate difference from the PC class: there, "is the overlay
 * open" is read directly off `self.visible` (update_idle_glow is a
 * HelpOverlay method). Here, the timer has no reference to the
 * overlay's own open/closed state, so the caller passes it in as
 * `overlayOpen` on every update() call -- HelpOverlay.ts (the Phaser
 * wrapper) is the one place that both owns an IdleGlowTimer AND knows
 * whether it's currently open, so it supplies that flag itself; this
 * module only needs to be told, not to know.
 */

/** Seconds-of-inactivity before the "?" button starts its nudge glow
 * -- ported verbatim from HelpOverlay.IDLE_GLOW_INTERVAL (30.0s). */
export const IDLE_GLOW_INTERVAL_MS = 30_000;

/** How long the nudge glow lasts once triggered -- ported verbatim
 * from HelpOverlay.IDLE_GLOW_DURATION (3.0s). */
export const IDLE_GLOW_DURATION_MS = 3_000;

export interface IdleGlowState {
  /** Milliseconds of continued inactivity accrued since the last
   * notice_activity()/glow trigger -- mirrors `_idle_timer`. */
  idleMs: number;
  /** Milliseconds remaining in an active glow, 0 when not glowing --
   * mirrors `_glow_timer`. */
  glowMs: number;
}

export function initialIdleGlowState(): IdleGlowState {
  return { idleMs: 0, glowMs: 0 };
}

/** Call on any real input event on the owning screen -- resets the
 * idle clock and cancels an in-progress glow immediately, same as the
 * PC's notice_activity() (once the player's doing something, there's
 * no point finishing the nudge). */
export function noticeActivity(_state: IdleGlowState): IdleGlowState {
  return { idleMs: 0, glowMs: 0 };
}

/** Call once per frame regardless of whether the overlay is open --
 * fully suppressed while `overlayOpen` is true, mirroring the PC's
 * own early-return on `self.visible` (no point nudging someone to
 * open something they already have open). */
export function updateIdleGlow(state: IdleGlowState, deltaMs: number, overlayOpen: boolean): IdleGlowState {
  if (overlayOpen) return { idleMs: 0, glowMs: 0 };
  if (state.glowMs > 0) {
    return { idleMs: state.idleMs, glowMs: Math.max(0, state.glowMs - deltaMs) };
  }
  const idleMs = state.idleMs + deltaMs;
  if (idleMs >= IDLE_GLOW_INTERVAL_MS) {
    return { idleMs: 0, glowMs: IDLE_GLOW_DURATION_MS };
  }
  return { idleMs, glowMs: 0 };
}

export function isGlowing(state: IdleGlowState): boolean {
  return state.glowMs > 0;
}

/** The soft pulsing gold halo's current radius-extra/alpha, or null
 * when not glowing -- direct port of draw_button_glow()'s pulse math
 * (`t = 1 - glow_timer/DURATION`, `pulse = 0.5 + 0.5*sin(t*pi*4)`,
 * a couple of pulses across the 3s glow). Callers add `radiusExtra`
 * to half the button's width to get the halo's actual draw radius,
 * same as the PC's `button_rect.width // 2 + 4 + int(pulse * 6)`. */
export function glowPulse(state: IdleGlowState): { radiusExtra: number; alpha: number } | null {
  if (state.glowMs <= 0) return null;
  const t = 1 - state.glowMs / IDLE_GLOW_DURATION_MS;
  const pulse = 0.5 + 0.5 * Math.sin(t * Math.PI * 4);
  return { radiusExtra: 4 + pulse * 6, alpha: 90 + pulse * 100 };
}

/** Thin stateful wrapper for ergonomic use inside a Scene/HelpOverlay
 * -- same shape as statusText.ts's StatusTextGuard class alongside its
 * own pure canReplaceStatusText() function. */
export class IdleGlowTimer {
  private state: IdleGlowState = initialIdleGlowState();

  noticeActivity(): void {
    this.state = noticeActivity(this.state);
  }

  update(deltaMs: number, overlayOpen: boolean): void {
    this.state = updateIdleGlow(this.state, deltaMs, overlayOpen);
  }

  get isGlowing(): boolean {
    return isGlowing(this.state);
  }

  get pulse(): { radiusExtra: number; alpha: number } | null {
    return glowPulse(this.state);
  }
}
