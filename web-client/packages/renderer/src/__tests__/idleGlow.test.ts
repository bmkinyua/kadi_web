import { describe, expect, it } from 'vitest';
import {
  IDLE_GLOW_DURATION_MS,
  IDLE_GLOW_INTERVAL_MS,
  IdleGlowTimer,
  glowPulse,
  initialIdleGlowState,
  isGlowing,
  noticeActivity,
  updateIdleGlow,
} from '../idleGlow.js';

describe('updateIdleGlow (pure)', () => {
  it('does not glow before 30s of accrued inactivity', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false);
    expect(isGlowing(state)).toBe(false);
  });

  it('starts glowing once 30s of inactivity has accrued (inclusive boundary)', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false);
    expect(isGlowing(state)).toBe(true);
    expect(state.glowMs).toBe(IDLE_GLOW_DURATION_MS);
  });

  it('accrues inactivity across several smaller ticks, not just one big one', () => {
    let state = initialIdleGlowState();
    const tick = IDLE_GLOW_INTERVAL_MS / 10;
    for (let i = 0; i < 9; i++) {
      state = updateIdleGlow(state, tick, false);
      expect(isGlowing(state)).toBe(false);
    }
    state = updateIdleGlow(state, tick, false);
    expect(isGlowing(state)).toBe(true);
  });

  it('the glow lasts exactly 3s and then stops on its own', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false); // trigger
    state = updateIdleGlow(state, IDLE_GLOW_DURATION_MS - 1, false);
    expect(isGlowing(state)).toBe(true);
    state = updateIdleGlow(state, 1, false);
    expect(isGlowing(state)).toBe(false);
  });

  it('repeats every 30s of continued inactivity after a glow finishes', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false); // 1st trigger
    state = updateIdleGlow(state, IDLE_GLOW_DURATION_MS, false); // glow ends, idle clock fresh
    expect(isGlowing(state)).toBe(false);
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false);
    expect(isGlowing(state)).toBe(false);
    state = updateIdleGlow(state, 1, false);
    expect(isGlowing(state)).toBe(true); // 2nd trigger
  });

  it('noticeActivity resets the idle clock before it has triggered', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false);
    state = noticeActivity(state);
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false);
    expect(isGlowing(state)).toBe(false); // would have triggered without the reset
  });

  it('noticeActivity cancels an in-progress glow immediately', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false);
    expect(isGlowing(state)).toBe(true);
    state = noticeActivity(state);
    expect(isGlowing(state)).toBe(false);
    expect(state.idleMs).toBe(0);
  });

  it('is fully suppressed while the overlay is open, even after 30s+', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS * 2, true);
    expect(isGlowing(state)).toBe(false);
    expect(state.idleMs).toBe(0);
  });

  it('suppression while open also cancels an already-active glow', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false);
    expect(isGlowing(state)).toBe(true);
    state = updateIdleGlow(state, 1, true); // overlay opens mid-glow
    expect(isGlowing(state)).toBe(false);
  });

  it('resumes accruing idle time from zero once closed again after being open', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false);
    state = updateIdleGlow(state, 5000, true); // opened before it would have triggered
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS - 1, false); // closed again
    expect(isGlowing(state)).toBe(false); // needs a fresh full 30s, not the leftover 1ms
  });
});

describe('glowPulse', () => {
  it('returns null when not glowing', () => {
    expect(glowPulse(initialIdleGlowState())).toBeNull();
  });

  it('returns a radiusExtra/alpha pair while glowing', () => {
    let state = initialIdleGlowState();
    state = updateIdleGlow(state, IDLE_GLOW_INTERVAL_MS, false);
    const pulse = glowPulse(state);
    expect(pulse).not.toBeNull();
    expect(pulse!.radiusExtra).toBeGreaterThanOrEqual(4);
    expect(pulse!.radiusExtra).toBeLessThanOrEqual(10);
    expect(pulse!.alpha).toBeGreaterThanOrEqual(90);
    expect(pulse!.alpha).toBeLessThanOrEqual(190);
  });
});

describe('IdleGlowTimer (stateful wrapper)', () => {
  it('mirrors the pure function behavior end-to-end', () => {
    const timer = new IdleGlowTimer();
    expect(timer.isGlowing).toBe(false);

    timer.update(IDLE_GLOW_INTERVAL_MS - 1, false);
    expect(timer.isGlowing).toBe(false);

    timer.update(1, false);
    expect(timer.isGlowing).toBe(true);
    expect(timer.pulse).not.toBeNull();

    timer.noticeActivity();
    expect(timer.isGlowing).toBe(false);
    expect(timer.pulse).toBeNull();
  });

  it('suppresses while open and resumes cleanly once closed', () => {
    const timer = new IdleGlowTimer();
    timer.update(IDLE_GLOW_INTERVAL_MS, true); // open the whole time
    expect(timer.isGlowing).toBe(false);
    timer.update(IDLE_GLOW_INTERVAL_MS, false); // now closed, fresh 30s
    expect(timer.isGlowing).toBe(true);
  });
});
