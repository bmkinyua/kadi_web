import { describe, expect, it } from 'vitest';
import { computeModeSelectLayout } from '../ModeSelectLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('computeModeSelectLayout', () => {
  it('returns exactly vsAi, internet, then back -- no LAN placeholder, ever', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeModeSelectLayout(viewport, ZERO_INSETS);
      expect(layout.buttons.map((b) => b.id)).toEqual(['vsAi', 'internet', 'back']);
      expect(layout.buttons.some((b) => /lan/i.test(b.label))).toBe(false);
    }
  });

  it('places the title above the button stack, and stacks buttons with no overlap', () => {
    const layout = computeModeSelectLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(layout.title.y).toBeLessThan(layout.buttons[0].y);
    for (let i = 1; i < layout.buttons.length; i++) {
      const prev = layout.buttons[i - 1];
      const curr = layout.buttons[i];
      expect(curr.y).toBeGreaterThanOrEqual(prev.y + prev.height);
    }
  });

  it('puts "back" clearly separated below the two mode buttons', () => {
    const layout = computeModeSelectLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const [vsAi, internet, back] = layout.buttons;
    const gapBetweenModes = internet.y - (vsAi.y + vsAi.height);
    const gapBeforeBack = back.y - (internet.y + internet.height);
    expect(gapBeforeBack).toBeGreaterThan(gapBetweenModes);
  });

  it('enforces the minimum touch target on every button at a tiny viewport', () => {
    const layout = computeModeSelectLayout({ width: 320, height: 400 }, ZERO_INSETS);
    for (const button of layout.buttons) {
      expect(button.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(button.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('grows scale/size when the viewport grows', () => {
    const phoneLayout = computeModeSelectLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS);
    const tabletLayout = computeModeSelectLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(tabletLayout.scale).toBeGreaterThan(phoneLayout.scale);
    expect(tabletLayout.buttons[0].width).toBeGreaterThan(phoneLayout.buttons[0].width);
  });

  it('centers every button horizontally within the content rect', () => {
    const layout = computeModeSelectLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const centerX = layout.contentRect.x + layout.contentRect.width / 2;
    for (const button of layout.buttons) {
      expect(button.x + button.width / 2).toBeCloseTo(centerX, 5);
    }
  });

  it('shifts every element inward when safe-area insets are applied', () => {
    const noInsets = computeModeSelectLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const withInsets = computeModeSelectLayout(MID_TABLET_PANEL, {
      top: 40,
      right: 20,
      bottom: 20,
      left: 20,
    });
    expect(withInsets.title.y).toBeGreaterThan(noInsets.title.y);
    expect(withInsets.buttons[0].y).toBeGreaterThan(noInsets.buttons[0].y);
  });
});
