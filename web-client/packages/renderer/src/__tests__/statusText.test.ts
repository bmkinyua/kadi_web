import { describe, expect, it } from 'vitest';
import { StatusTextGuard, canReplaceStatusText, DEFAULT_MIN_DISPLAY_MS } from '../statusText.js';

describe('canReplaceStatusText', () => {
  it('refuses a replacement the instant a message was shown (0ms elapsed)', () => {
    expect(canReplaceStatusText(1000, 1000, 500)).toBe(false);
  });

  it('refuses a replacement while still short of the minimum window', () => {
    expect(canReplaceStatusText(1000, 1499, 500)).toBe(false);
  });

  it('allows a replacement exactly at the minimum window (inclusive boundary)', () => {
    expect(canReplaceStatusText(1000, 1500, 500)).toBe(true);
  });

  it('allows a replacement comfortably past the minimum window', () => {
    expect(canReplaceStatusText(1000, 5000, 500)).toBe(true);
  });

  it('allows an initial message with no prior show (lastShownAtMs = -Infinity)', () => {
    expect(canReplaceStatusText(-Infinity, 0, 500)).toBe(true);
  });
});

describe('StatusTextGuard', () => {
  /** A tiny controllable clock so the guard's timing can be driven
   * deterministically instead of racing a real one. */
  function fakeClock(startMs = 0) {
    let now = startMs;
    return {
      now: () => now,
      advance: (ms: number) => {
        now += ms;
      },
    };
  }

  it('applies the very first message immediately regardless of minDisplayMs', () => {
    const clock = fakeClock(0);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now, 500);

    guard.show('Reconnecting…');

    expect(calls).toEqual(['Reconnecting…']);
  });

  it('the exact bug this fixes: a same-tick clear right after a shown message is dropped', () => {
    // Mirrors GameTableScene's onConnectionState() setting 'Reconnecting…'
    // immediately followed, in the same tick, by onServerMessage's
    // 'rejoined' handler blanking it back to ''.
    const clock = fakeClock(1000);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now, 500);

    guard.show('Reconnecting…');
    guard.show(''); // 0ms later -- must NOT clobber the message just shown

    expect(calls).toEqual(['Reconnecting…']);
  });

  it('allows a later call once minDisplayMs has genuinely elapsed', () => {
    const clock = fakeClock(0);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now, 500);

    guard.show('Reconnecting…');
    clock.advance(500);
    guard.show('');

    expect(calls).toEqual(['Reconnecting…', '']);
  });

  it('a rapid string of calls within the window all collapse to just the first', () => {
    const clock = fakeClock(0);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now, 500);

    guard.show('A');
    clock.advance(100);
    guard.show('B');
    clock.advance(100);
    guard.show('C');

    expect(calls).toEqual(['A']);

    clock.advance(300); // total 500ms since 'A' was shown
    guard.show('D');
    expect(calls).toEqual(['A', 'D']);
  });

  it('showImmediate always wins and resets the guard window from that moment', () => {
    const clock = fakeClock(0);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now, 500);

    guard.show('Reconnecting…');
    clock.advance(10);
    guard.showImmediate('Could not reconnect — timed out'); // bypasses the guard

    expect(calls).toEqual(['Reconnecting…', 'Could not reconnect — timed out']);

    // And a normal show() right after showImmediate() is itself gated
    // by the fresh window showImmediate() just started.
    clock.advance(10);
    guard.show('Something else');
    expect(calls).toEqual(['Reconnecting…', 'Could not reconnect — timed out']);
  });

  it('uses DEFAULT_MIN_DISPLAY_MS when no override is given', () => {
    const clock = fakeClock(0);
    const calls: string[] = [];
    const guard = new StatusTextGuard((t) => calls.push(t), clock.now);

    guard.show('A');
    clock.advance(DEFAULT_MIN_DISPLAY_MS - 1);
    guard.show('B');
    expect(calls).toEqual(['A']);

    clock.advance(1);
    guard.show('B');
    expect(calls).toEqual(['A', 'B']);
  });
});
