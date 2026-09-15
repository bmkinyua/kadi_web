import { describe, expect, it } from 'vitest';
import { computeMainMenuLayout } from '../MainMenuLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('computeMainMenuLayout', () => {
  it('places title above subtitle above the button stack, in order', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeMainMenuLayout(viewport, ZERO_INSETS);
      expect(layout.title.y).toBeLessThan(layout.subtitle.y);
      expect(layout.subtitle.y).toBeLessThan(layout.buttons[0].y);
    }
  });

  it('returns exactly the six planned buttons, in a stable order', () => {
    const layout = computeMainMenuLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(layout.buttons.map((b) => b.id)).toEqual([
      'playVsAi',
      'multiplayer',
      'profile',
      'settings',
      'howToPlay',
      'chuo',
    ]);
  });

  it('marks all six buttons enabled -- chuo is now wired to ChuoScene', () => {
    const layout = computeMainMenuLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const byId = Object.fromEntries(layout.buttons.map((b) => [b.id, b.enabled]));
    expect(byId.playVsAi).toBe(true);
    expect(byId.multiplayer).toBe(true);
    expect(byId.profile).toBe(true);
    expect(byId.settings).toBe(true);
    expect(byId.howToPlay).toBe(true);
    expect(byId.chuo).toBe(true);
  });

  it('stacks buttons top to bottom with no overlap, at any viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeMainMenuLayout(viewport, ZERO_INSETS);
      for (let i = 1; i < layout.buttons.length; i++) {
        const prev = layout.buttons[i - 1];
        const curr = layout.buttons[i];
        expect(curr.y).toBeGreaterThanOrEqual(prev.y + prev.height);
      }
    }
  });

  it('enforces the minimum touch target on every button at a tiny viewport', () => {
    const layout = computeMainMenuLayout({ width: 320, height: 400 }, ZERO_INSETS);
    for (const button of layout.buttons) {
      expect(button.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(button.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('grows font sizes and button sizes when the viewport grows', () => {
    const phoneLayout = computeMainMenuLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS);
    const tabletLayout = computeMainMenuLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(tabletLayout.scale).toBeGreaterThan(phoneLayout.scale);
    expect(tabletLayout.title.fontPx).toBeGreaterThan(phoneLayout.title.fontPx);
    expect(tabletLayout.buttons[0].width).toBeGreaterThan(phoneLayout.buttons[0].width);
  });

  it('centers the title/subtitle/buttons horizontally within the content rect', () => {
    const layout = computeMainMenuLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const centerX = layout.contentRect.x + layout.contentRect.width / 2;
    expect(layout.title.x).toBeCloseTo(centerX, 5);
    for (const button of layout.buttons) {
      expect(button.x + button.width / 2).toBeCloseTo(centerX, 5);
    }
  });

  it('shifts every element inward when safe-area insets are applied', () => {
    const noInsets = computeMainMenuLayout(MID_TABLET_PANEL, ZERO_INSETS);
    const withInsets = computeMainMenuLayout(MID_TABLET_PANEL, {
      top: 40,
      right: 20,
      bottom: 20,
      left: 20,
    });
    expect(withInsets.title.y).toBeGreaterThan(noInsets.title.y);
    expect(withInsets.buttons[0].y).toBeGreaterThan(noInsets.buttons[0].y);
  });
});
