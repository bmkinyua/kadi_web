import { describe, expect, it } from 'vitest';
import { getSafeContentRect } from '../safeArea.js';

describe('getSafeContentRect', () => {
  it('returns the full viewport when insets are all zero', () => {
    const rect = getSafeContentRect({ width: 800, height: 600 }, { top: 0, right: 0, bottom: 0, left: 0 });
    expect(rect).toEqual({ x: 0, y: 0, width: 800, height: 600 });
  });

  it('shrinks and offsets the rect by each inset independently', () => {
    const rect = getSafeContentRect(
      { width: 800, height: 600 },
      { top: 20, right: 10, bottom: 30, left: 15 },
    );
    expect(rect.x).toBe(15);
    expect(rect.y).toBe(20);
    expect(rect.width).toBe(800 - 15 - 10);
    expect(rect.height).toBe(600 - 20 - 30);
  });

  it('floors width/height at 0 rather than going negative for oversized insets', () => {
    const rect = getSafeContentRect(
      { width: 100, height: 100 },
      { top: 80, right: 80, bottom: 80, left: 80 },
    );
    expect(rect.width).toBe(0);
    expect(rect.height).toBe(0);
  });
});
