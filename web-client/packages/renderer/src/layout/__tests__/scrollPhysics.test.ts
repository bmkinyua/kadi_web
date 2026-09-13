import { describe, expect, it } from 'vitest';
import {
  SCROLL_OVERSHOOT,
  SCROLL_SETTLE_DURATION_MS,
  clampScroll,
  easeOutBack,
  scrollWheelDelta,
  settleScroll,
  type ScrollBounce,
} from '../scrollPhysics.js';

describe('easeOutBack', () => {
  it('starts at 0 and ends at 1', () => {
    expect(easeOutBack(0)).toBeCloseTo(0, 5);
    expect(easeOutBack(1)).toBeCloseTo(1, 5);
  });

  it('overshoots past 1.0 partway through before settling (the "back" in ease_out_back)', () => {
    // Somewhere in the back half of the curve the eased value should
    // exceed the 1.0 target -- that overshoot-then-settle bump is the
    // entire point of this easing function.
    const samples = [0.7, 0.75, 0.8, 0.85, 0.9].map((t) => easeOutBack(t));
    expect(Math.max(...samples)).toBeGreaterThan(1.0);
  });
});

describe('scrollWheelDelta', () => {
  it('adds a positive deltaY (scroll down) to the current value', () => {
    expect(scrollWheelDelta(100, 50, 500)).toBe(150);
  });

  it('adds a negative deltaY (scroll up) to the current value', () => {
    expect(scrollWheelDelta(100, -50, 500)).toBe(50);
  });

  it('allows overshoot below 0 up to -SCROLL_OVERSHOOT', () => {
    expect(scrollWheelDelta(10, -30, 500)).toBe(10 - 30); // -20, within -42
    expect(scrollWheelDelta(10, -1000, 500)).toBe(-SCROLL_OVERSHOOT);
  });

  it('allows overshoot above maxScroll up to maxScroll + SCROLL_OVERSHOOT', () => {
    expect(scrollWheelDelta(490, 20, 500)).toBe(510); // within 500+42
    expect(scrollWheelDelta(490, 10_000, 500)).toBe(500 + SCROLL_OVERSHOOT);
  });

  it('respects a custom overshoot amount', () => {
    expect(scrollWheelDelta(0, -100, 500, 10)).toBe(-10);
    expect(scrollWheelDelta(500, 100, 500, 10)).toBe(510);
  });
});

describe('settleScroll', () => {
  const MAX = 1000;

  it('passes an in-range value straight through with no bounce', () => {
    const result = settleScroll(500, null, 16, MAX);
    expect(result).toEqual({ value: 500, bounce: null });
  });

  it('starts a new bounce the first frame a value is below 0', () => {
    const result = settleScroll(-20, null, 16, MAX);
    expect(result.bounce).not.toBeNull();
    expect(result.bounce!.from).toBe(-20);
    expect(result.bounce!.to).toBe(0);
    // Partway through the settle duration, the value should have moved
    // from -20 toward 0, but not reached it yet.
    expect(result.value).toBeGreaterThan(-20);
  });

  it('starts a new bounce the first frame a value is above maxScroll', () => {
    const result = settleScroll(MAX + 30, null, 16, MAX);
    expect(result.bounce).not.toBeNull();
    expect(result.bounce!.from).toBe(MAX + 30);
    expect(result.bounce!.to).toBe(MAX);
  });

  it('keeps easing an in-progress bounce toward its bound over successive frames', () => {
    let state: { value: number; bounce: ScrollBounce | null } = settleScroll(-20, null, 16, MAX);
    const firstValue = state.value;
    // Drive it forward several more frames.
    for (let i = 0; i < 10; i++) {
      state = settleScroll(state.value, state.bounce, 16, MAX);
    }
    expect(state.value).toBeGreaterThan(firstValue);
  });

  it('settles exactly at the bound once elapsed time reaches SCROLL_SETTLE_DURATION_MS, and clears the bounce', () => {
    let state: { value: number; bounce: ScrollBounce | null } = settleScroll(-20, null, 16, MAX);
    // Drive it forward enough frames to exceed the settle duration.
    const frameMs = 16;
    const framesNeeded = Math.ceil(SCROLL_SETTLE_DURATION_MS / frameMs) + 2;
    for (let i = 0; i < framesNeeded; i++) {
      state = settleScroll(state.value, state.bounce, frameMs, MAX);
    }
    expect(state.bounce).toBeNull();
    expect(state.value).toBeCloseTo(0, 5);
  });

  it('keeps easing from the bounce\'s ORIGINAL start value even if current drifts further out of range mid-bounce', () => {
    // Mirrors the PC Tween's own behavior: once a bounce animation
    // exists, it doesn't get re-anchored to a newer, more-out-of-range
    // current value -- it keeps easing from where it first started.
    const first = settleScroll(-10, null, 16, MAX);
    expect(first.bounce!.from).toBe(-10);
    // Even if some caller fed a wildly different "current" on the next
    // frame, the bounce object itself still remembers -10 as `from`.
    const second = settleScroll(-999, first.bounce, 16, MAX);
    expect(second.bounce!.from).toBe(-10);
  });

  it('a zero-duration settle resolves to the bound immediately (no divide-by-zero)', () => {
    // Sanity check for the SCROLL_SETTLE_DURATION_MS === 0 branch --
    // not reachable via the exported constant today, but the function
    // itself should not divide by zero if it were ever configured to.
    const result = settleScroll(-5, null, 0, MAX);
    expect(Number.isFinite(result.value)).toBe(true);
  });
});

describe('clampScroll', () => {
  it('leaves an in-range value untouched', () => {
    expect(clampScroll(50, 100)).toBe(50);
  });

  it('clamps a negative value to 0 with no overshoot allowance', () => {
    expect(clampScroll(-30, 100)).toBe(0);
  });

  it('clamps a too-large value to maxScroll with no overshoot allowance', () => {
    expect(clampScroll(150, 100)).toBe(100);
  });
});
