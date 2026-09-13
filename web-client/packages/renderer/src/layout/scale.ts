/**
 * KADI web-client — continuous scale-factor system.
 *
 * Successor to the Python client's `get_chrome_scale(sw, sh)`
 * (constants.py) for this renderer. Deliberately kept **pure and
 * framework-agnostic** — no Phaser types, no DOM — so every formula
 * here is unit-testable without a canvas/WebGL context (see
 * __tests__/scale.test.ts). The Phaser-facing wiring (Scale Manager
 * config, resize event subscription) lives in index.ts and each
 * scene; this file is only the math.
 *
 * WHY THIS DIFFERS FROM get_chrome_scale, NOT JUST A PORT:
 *
 * 1. get_chrome_scale(sw, sh) is fed one of 8 resolutions the player
 *    explicitly picked from a fixed list (RESOLUTIONS in scenes.py) —
 *    it only ever needs to look good at exactly those 8 points, and
 *    UI_SCALE_PROFILES in constants.py hand-tunes each one. There is
 *    no picker here (browser/mobile viewports resize continuously and
 *    the player never chooses a number), so this can't be a lookup
 *    table — it has to be a smooth function of whatever the *current*
 *    canvas size actually is, recomputed on every genuine resize.
 * 2. get_chrome_scale's own code comments admit roughly half the
 *    Python UI was "never audited" for what happens when text/layout
 *    scales — only the gameplay table and Settings/Rules panel
 *    actually consume it. This system is built to be the mandatory
 *    pattern from LobbyScene onward (see KADI_web_port_implementation
 *    _plan.md's new "Continuous Layout & Scale System" section) so
 *    that gap does not reopen here.
 *
 * WHY THE FORMULA LOOKS LIKE THIS:
 *
 * scale = clamp(min(width / BASE_WIDTH, height / BASE_HEIGHT), MIN, MAX)
 *
 * Using min() of the two axis ratios (rather than e.g. width alone)
 * means a very tall-narrow phone and a very wide-short desktop panel
 * both get a scale that fits BOTH axes at once — nothing overflows
 * the shorter dimension. This is the same reasoning Phaser's own
 * Phaser.Scale.FIT mode uses for letterboxing; we do it ourselves
 * (as a *number*, not a canvas transform) because we still want the
 * canvas to fill the viewport (Scale.RESIZE — see index.ts) while
 * only font/UI-chrome sizing follows the FIT-style ratio.
 */

/** Design-baseline canvas size every font/button size below is
 * expressed relative to — matches the renderer's original fixed
 * canvas (see index.ts's previous `width: 480, height: 640`). */
export const BASE_WIDTH = 480;
export const BASE_HEIGHT = 640;

/** Scale-factor floor/ceiling. Mirrors the spirit of the Python
 * fallback's `max(0.8, min(4.0, sw / 1280))` (constants.py
 * get_ui_scale) — wide enough to cover phone-portrait through 4K/8K
 * desktop without either shrinking text to illegible sizes on a tiny
 * panel or blowing UI up absurdly large on an ultra-wide monitor. */
export const MIN_SCALE = 0.7;
export const MAX_SCALE = 3.0;

/**
 * Supported viewport range (Part B). Discord Activities and Telegram
 * Mini Apps do NOT publish a fixed numeric min/max panel size —
 * both are explicitly designed to be resized/dragged by the host at
 * runtime and their own guidance is "make UI elements scale
 * appropriately" / "consider different screen sizes and orientations"
 * rather than "target exactly NxM" (see the sources recorded in
 * KADI_web_port_implementation_plan.md's new section). So these
 * bounds are a deliberately-chosen practical range informed by that
 * research, not a platform-mandated constant:
 *
 * - MIN_WIDTH 320 / MIN_HEIGHT 400: covers the narrowest common phone
 *   portrait viewport (320 CSS px, e.g. older/smaller Android and the
 *   iPhone SE family) and Telegram's collapsed/"compact" BottomSheet
 *   state, which can present less than full device height.
 * - MAX_WIDTH 3840 / MAX_HEIGHT 2160: a 4K desktop browser window.
 *   Values beyond this still render (the scale factor itself clamps
 *   at MAX_SCALE above) — Scale Manager's max just stops the actual
 *   canvas from growing past a sane render-target size.
 */
export const MIN_VIEWPORT_WIDTH = 320;
export const MIN_VIEWPORT_HEIGHT = 400;
export const MAX_VIEWPORT_WIDTH = 3840;
export const MAX_VIEWPORT_HEIGHT = 2160;

/**
 * Minimum interactive-element size (Part C), in CSS pixels == Phaser
 * scene units at this renderer's 1:1 device-pixel-ratio-aware setup.
 * 44 is Apple's Human Interface Guidelines floor for a tappable area
 * (also WCAG 2.5.5 AAA's 44x44 CSS px) — Google's Material Design
 * guidance is stricter at 48x48dp. 44 is used as the hard floor here
 * (matches the brief's own estimate and the stricter of the two
 * platforms' *minimums*), but callers are free to size elements larger
 * — this is a floor, not a target. Verified against current guidance;
 * see KADI_web_port_implementation_plan.md's new section for sources.
 */
export const MIN_TOUCH_TARGET_PX = 44;

export interface Viewport {
  width: number;
  height: number;
}

/** Clamp a number into [min, max]. */
function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/**
 * The one function every scene should call to get "the" current
 * scale factor, recomputed from the actual current canvas
 * dimensions — the direct successor to get_chrome_scale(sw, sh).
 * Never fed a resolution chosen from a list; always fed whatever
 * Phaser's Scale Manager currently reports as this.scale.width/height.
 */
export function computeLayoutScale(viewport: Viewport): number {
  const widthRatio = viewport.width / BASE_WIDTH;
  const heightRatio = viewport.height / BASE_HEIGHT;
  const raw = Math.min(widthRatio, heightRatio);
  return clamp(raw, MIN_SCALE, MAX_SCALE);
}

/**
 * Font-size ladder, mirroring asset_loader.py's named tiers
 * (ui_tiny/ui_small/ui_normal/ui_medium/ui_large) so the same naming
 * carries over conceptually. Base sizes are independent of the
 * Python side's point sizes (different rendering stack, same idea:
 * a small fixed set of named steps rather than arbitrary one-off
 * pixel values scattered across scenes).
 */
export const FONT_LADDER = {
  ui_tiny: 11,
  ui_small: 14,
  ui_normal: 16,
  ui_medium: 20,
  ui_large: 28,
} as const;

export type FontLadderName = keyof typeof FONT_LADDER;

/** Scaled pixel size for a named font tier at the given scale factor.
 * Returns a plain number (px) — callers building a Phaser text style
 * do `${fontPx(...)}px`. Rounded because Phaser fonts render slightly
 * more predictably at whole pixel sizes, and to keep results
 * deterministic for tests. */
export function fontPx(name: FontLadderName, scale: number): number {
  return Math.max(6, Math.round(FONT_LADDER[name] * scale));
}

export interface Size {
  width: number;
  height: number;
}

/**
 * Enforces the minimum interactive-element size (Part C) on a
 * proposed element box. Only ever grows a box, never shrinks one —
 * a caller that wants a bigger-than-minimum button keeps its size.
 */
export function enforceMinTouchTarget(size: Size): Size {
  return {
    width: Math.max(size.width, MIN_TOUCH_TARGET_PX),
    height: Math.max(size.height, MIN_TOUCH_TARGET_PX),
  };
}

/** Clamps an arbitrary reported viewport into the supported range
 * (Part B) before any layout math runs on it, so a host platform
 * momentarily reporting something degenerate (0x0 during a resize
 * transition, or something absurd) can't produce nonsensical layout. */
export function clampViewport(viewport: Viewport): Viewport {
  return {
    width: clamp(viewport.width, MIN_VIEWPORT_WIDTH, MAX_VIEWPORT_WIDTH),
    height: clamp(viewport.height, MIN_VIEWPORT_HEIGHT, MAX_VIEWPORT_HEIGHT),
  };
}
