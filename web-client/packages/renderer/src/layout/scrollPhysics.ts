/**
 * KADI web-client — shared scroll-limit "bounce" physics.
 *
 * Ported from scenes.py's module-level `_scroll_wheel_delta()` /
 * `_settle_scroll()` (SCROLL_OVERSHOOT / SCROLL_SETTLE_DURATION), which
 * that file's own comment already documents as shared across
 * SettingsScene, RulesScene, and ChuoScene's scrollable lists — this is
 * the same thing for this renderer: not RulesScene-specific, so it
 * lives at this shared layout-module level rather than inside
 * RulesLayout.ts, ready for a future SettingsScene to reuse exactly as
 * the PC side does.
 *
 * BEHAVIOR PRESERVED (see next_task_prompt2.md's Part B "suggested
 * shape" note — preserve the *behavior*, not a 1:1 tween-library
 * port): a wheel tick is allowed to push the scroll value a small
 * bounded amount past [0, maxScroll] rather than hard-clamping, and
 * once out of range it eases back to the nearest bound with an
 * overshoot-then-settle curve (`ease_out_back`) instead of snapping.
 * Framework-agnostic and pure, like scale.ts/safeArea.ts — see
 * __tests__/scrollPhysics.test.ts for direct verification with no
 * Phaser/canvas involved.
 *
 * WHY A SEPARATE settleScroll() SHAPE FROM THE PYTHON ORIGINAL:
 * `_settle_scroll()` takes an existing `Tween` object (or None) and
 * mutates/replaces it every frame — that `Tween` class (animation/
 * animator.py) carries its own internal elapsed-time state alongside
 * its start/end values. There's no equivalent shared Tween class on
 * this side (this module intentionally stays framework/library-free),
 * so the same three pieces of state (start value, end value, elapsed
 * time) are threaded through explicitly as a plain `ScrollBounce`
 * object instead — same information, no hidden mutation, and it
 * serializes trivially for a test to assert on mid-bounce.
 */

/** How far (in the same units as the scroll value itself) a value is
 * allowed to overshoot past [0, maxScroll] before scrollWheelDelta()
 * clamps it — mirrors scenes.py's SCROLL_OVERSHOOT exactly. */
export const SCROLL_OVERSHOOT = 42;

/** How long the eased return from an overshot value to its nearest
 * bound takes, in milliseconds — mirrors scenes.py's
 * SCROLL_SETTLE_DURATION (0.32s), converted to ms since this module's
 * callers (Phaser's per-frame `delta`) already work in ms. */
export const SCROLL_SETTLE_DURATION_MS: number = 320;

/** Overshoot constant for ease_out_back's cubic term — the same
 * "backs up past the target before arriving" magic number
 * animation/animator.py's ease_out_back() hard-codes as its default. */
const EASE_OUT_BACK_OVERSHOOT = 1.70158;

/** `t` in [0, 1] -> eased progress, briefly overshooting past 1.0 and
 * settling back — direct port of animation/animator.py's
 * ease_out_back(). */
export function easeOutBack(t: number, overshoot: number = EASE_OUT_BACK_OVERSHOOT): number {
  const c1 = overshoot;
  const c3 = c1 + 1;
  const shifted = t - 1;
  return 1 + c3 * shifted ** 3 + c1 * shifted ** 2;
}

/**
 * New scroll value for a single wheel tick, allowed to overshoot the
 * valid [0, maxScroll] range by up to `overshoot` before being
 * clamped. `deltaY` is the raw wheel delta the caller received
 * (positive = scroll down/content moves up, matching a standard DOM
 * WheelEvent's own sign convention) — direct port of
 * `_scroll_wheel_delta()`'s formula, but note the PC original negates
 * pygame's `event.y`, which uses the OPPOSITE sign convention from a
 * web WheelEvent's `deltaY`; this version is written for the web
 * convention directly rather than carrying that negation over
 * verbatim, so callers can pass a real `WheelEvent`/Phaser pointer
 * delta straight through.
 */
export function scrollWheelDelta(
  current: number,
  deltaY: number,
  maxScroll: number,
  overshoot: number = SCROLL_OVERSHOOT,
): number {
  const target = current + deltaY;
  return Math.max(-overshoot, Math.min(maxScroll + overshoot, target));
}

/** The (start, target, elapsed-so-far) state of an in-progress
 * settle-back animation — the explicit stand-in for the PC's mutable
 * `Tween` object (see this file's header note on why). `null`
 * anywhere this type is expected means "no bounce in progress." */
export interface ScrollBounce {
  readonly from: number;
  readonly to: number;
  elapsedMs: number;
}

/**
 * Call once per frame with the current scroll value and the previous
 * frame's bounce state (or null). While `current` sits outside
 * [0, maxScroll], eases it back toward the nearest bound over
 * SCROLL_SETTLE_DURATION_MS using ease_out_back; once within range (or
 * once the bounce completes), returns `bounce: null`. Direct port of
 * `_settle_scroll()`'s branching, restated against the explicit
 * ScrollBounce shape instead of a mutable Tween.
 */
export function settleScroll(
  current: number,
  bounce: ScrollBounce | null,
  dtMs: number,
  maxScroll: number,
): { value: number; bounce: ScrollBounce | null } {
  // Whether to CONTINUE an already-running bounce is decided by
  // `bounce !== null`, not by re-checking current's range every
  // frame: ease_out_back's whole point is to overshoot PAST the
  // target before settling (see this file's own "back" test), so a
  // bounce easing back toward 0 legitimately passes back THROUGH
  // [0, maxScroll] for a frame or two on its way to landing exactly
  // on the bound. Gating continuation on current's range (as an
  // earlier version of this function did, mirroring a literal read of
  // _settle_scroll()'s own `if current < 0 or current > max_scroll`)
  // mistook that transient in-range crossing for "animation over" and
  // froze the scroll a hair off the bound instead of finishing the
  // ease -- caught by this file's own "settles exactly at the bound"
  // test. Only a FRESH bounce (bounce === null) needs current's range
  // to decide whether to start one at all.
  const startingFresh = bounce === null;
  const outOfRange = current < 0 || current > maxScroll;
  if (startingFresh && !outOfRange) {
    return { value: current, bounce: null };
  }
  const bound = bounce ? bounce.to : current < 0 ? 0 : maxScroll;
  // A bounce already in flight keeps its ORIGINAL start value even
  // if `current` drifted further out of range since it began (the
  // PC's Tween behaves the same way -- it was constructed once from
  // whatever `current` was the moment the out-of-range state was
  // first detected, and eases from that fixed start regardless of
  // what happens to the raw value afterward).
  const active: ScrollBounce = bounce ?? { from: current, to: bound, elapsedMs: 0 };
  const elapsedMs = Math.min(active.elapsedMs + dtMs, SCROLL_SETTLE_DURATION_MS);
  const t = SCROLL_SETTLE_DURATION_MS === 0 ? 1 : elapsedMs / SCROLL_SETTLE_DURATION_MS;
  const eased = easeOutBack(t);
  const value = active.from + (active.to - active.from) * eased;
  const done = elapsedMs >= SCROLL_SETTLE_DURATION_MS;
  return { value, bounce: done ? null : { ...active, elapsedMs } };
}

/** Clamp a scroll value into the valid [0, maxScroll] range with no
 * overshoot allowance -- used once a drag/settle interaction ends and
 * the value needs to land exactly in-bounds (mirrors scenes.py's
 * `_set_scroll()`). */
export function clampScroll(value: number, maxScroll: number): number {
  return Math.max(0, Math.min(maxScroll, value));
}
