import { describe, expect, it } from 'vitest';
import {
  BASE_HEIGHT,
  BASE_WIDTH,
  MAX_SCALE,
  MIN_SCALE,
  MIN_TOUCH_TARGET_PX,
  clampViewport,
  computeLayoutScale,
  enforceMinTouchTarget,
  fontPx,
} from '../scale.js';

// Representative viewport dimensions, per the task's verification
// requirement: narrow phone portrait, a mid-size tablet/panel, and
// wide desktop -- plus the exact design baseline as a sanity anchor.
const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 }; // e.g. a common Android phone
const MID_TABLET_PANEL = { width: 1024, height: 768 }; // iPad-ish / a Discord side panel
const WIDE_DESKTOP = { width: 2560, height: 1440 }; // a wide desktop browser window

describe('computeLayoutScale', () => {
  it('returns exactly 1.0 at the design baseline', () => {
    expect(computeLayoutScale({ width: BASE_WIDTH, height: BASE_HEIGHT })).toBeCloseTo(1.0, 5);
  });

  it('produces a smaller-than-baseline scale for a narrow phone portrait', () => {
    const scale = computeLayoutScale(NARROW_PHONE_PORTRAIT);
    expect(scale).toBeLessThan(1.0);
    expect(scale).toBeGreaterThanOrEqual(MIN_SCALE);
  });

  it('produces a larger-than-baseline scale for a mid-size tablet panel', () => {
    const scale = computeLayoutScale(MID_TABLET_PANEL);
    expect(scale).toBeGreaterThan(1.0);
  });

  it('produces an even larger scale for a wide desktop, clamped at MAX_SCALE', () => {
    const scale = computeLayoutScale(WIDE_DESKTOP);
    expect(scale).toBeLessThanOrEqual(MAX_SCALE);
    expect(scale).toBeGreaterThan(computeLayoutScale(MID_TABLET_PANEL));
  });

  it('increases monotonically as both dimensions grow proportionally', () => {
    const small = computeLayoutScale({ width: 480, height: 640 });
    const medium = computeLayoutScale({ width: 960, height: 1280 });
    const large = computeLayoutScale({ width: 1920, height: 2560 });
    expect(small).toBeLessThan(medium);
    // "large" here is 4x baseline, whose raw ratio (4.0) exceeds
    // MAX_SCALE, so it clamps -- still >= medium's unclamped 2.0,
    // just not a further multiple of it.
    expect(medium).toBeLessThanOrEqual(large);
    expect(large).toBe(MAX_SCALE);
  });

  it('uses the SMALLER of the two axis ratios, so a very tall-narrow viewport does not overflow width', () => {
    const tallNarrow = { width: 320, height: 2000 };
    const scale = computeLayoutScale(tallNarrow);
    // Width ratio (320/480 ~= 0.667) should dominate over the much
    // larger height ratio (2000/640 ~= 3.125) -- i.e. scale tracks the
    // constraining axis, not the generous one.
    expect(scale).toBeLessThan(1.0);
  });

  it('clamps degenerate near-zero dimensions to MIN_SCALE rather than producing 0 or negative', () => {
    const scale = computeLayoutScale({ width: 1, height: 1 });
    expect(scale).toBe(MIN_SCALE);
  });

  it('never exceeds MAX_SCALE even for an absurdly large viewport', () => {
    const scale = computeLayoutScale({ width: 20000, height: 20000 });
    expect(scale).toBe(MAX_SCALE);
  });
});

describe('fontPx', () => {
  it('scales a named font tier proportionally to the scale factor', () => {
    const base = fontPx('ui_normal', 1.0);
    const scaledUp = fontPx('ui_normal', 2.0);
    const scaledDown = fontPx('ui_normal', 0.5);
    expect(scaledUp).toBeGreaterThan(base);
    expect(scaledDown).toBeLessThan(base);
  });

  it('never returns a size below the 6px hard floor even at MIN_SCALE', () => {
    expect(fontPx('ui_tiny', MIN_SCALE)).toBeGreaterThanOrEqual(6);
  });

  it('produces a strict size ordering across the ladder at a fixed scale', () => {
    const scale = 1.0;
    expect(fontPx('ui_tiny', scale)).toBeLessThan(fontPx('ui_small', scale));
    expect(fontPx('ui_small', scale)).toBeLessThan(fontPx('ui_normal', scale));
    expect(fontPx('ui_normal', scale)).toBeLessThan(fontPx('ui_medium', scale));
    expect(fontPx('ui_medium', scale)).toBeLessThan(fontPx('ui_large', scale));
  });
});

describe('enforceMinTouchTarget (Part C)', () => {
  it('grows an element smaller than the minimum up to MIN_TOUCH_TARGET_PX', () => {
    const result = enforceMinTouchTarget({ width: 20, height: 30 });
    expect(result.width).toBe(MIN_TOUCH_TARGET_PX);
    expect(result.height).toBe(MIN_TOUCH_TARGET_PX);
  });

  it('leaves an already-large-enough element untouched', () => {
    const result = enforceMinTouchTarget({ width: 120, height: 60 });
    expect(result).toEqual({ width: 120, height: 60 });
  });

  it('only grows the dimension that is actually too small', () => {
    const result = enforceMinTouchTarget({ width: 200, height: 10 });
    expect(result.width).toBe(200);
    expect(result.height).toBe(MIN_TOUCH_TARGET_PX);
  });
});

describe('clampViewport (Part B)', () => {
  it('passes through a viewport already within the supported range', () => {
    expect(clampViewport({ width: 1280, height: 800 })).toEqual({ width: 1280, height: 800 });
  });

  it('clamps a viewport narrower/shorter than the supported minimum', () => {
    const result = clampViewport({ width: 100, height: 50 });
    expect(result.width).toBeGreaterThanOrEqual(320);
    expect(result.height).toBeGreaterThanOrEqual(400);
  });

  it('clamps a viewport larger than the supported maximum', () => {
    const result = clampViewport({ width: 10000, height: 8000 });
    expect(result.width).toBeLessThanOrEqual(3840);
    expect(result.height).toBeLessThanOrEqual(2160);
  });
});
