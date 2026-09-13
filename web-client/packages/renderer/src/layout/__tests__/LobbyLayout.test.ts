import { describe, expect, it } from 'vitest';
import { computeLobbyLayout } from '../LobbyLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('computeLobbyLayout', () => {
  it('places status/identity/rank/header in top-to-bottom order at any viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeLobbyLayout(viewport, ZERO_INSETS, 10);
      expect(layout.status.y).toBeLessThan(layout.identity.y);
      expect(layout.identity.y).toBeLessThan(layout.rank.y);
      expect(layout.rank.y).toBeLessThan(layout.leaderboardHeader.y);
    }
  });

  it('grows font sizes and positions when the viewport grows (mid tablet vs narrow phone)', () => {
    const phoneLayout = computeLobbyLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 5);
    const tabletLayout = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 5);

    expect(tabletLayout.scale).toBeGreaterThan(phoneLayout.scale);
    expect(tabletLayout.status.fontPx).toBeGreaterThan(phoneLayout.status.fontPx);
    expect(tabletLayout.rowHeight).toBeGreaterThan(phoneLayout.rowHeight);
    // Positions scale too -- the header should sit further down on
    // the larger/taller surface, not at a fixed pixel offset.
    expect(tabletLayout.leaderboardHeader.y).toBeGreaterThan(phoneLayout.leaderboardHeader.y);
  });

  it('shrinks further for an even wider/taller desktop viewport than the mid tablet panel', () => {
    const tabletLayout = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 5);
    const desktopLayout = computeLobbyLayout(WIDE_DESKTOP, ZERO_INSETS, 5);
    expect(desktopLayout.scale).toBeGreaterThanOrEqual(tabletLayout.scale);
  });

  it('caps visible leaderboard rows to what fits, rather than laying out past the bottom edge', () => {
    // A short viewport where 50 entries obviously cannot all fit.
    const shortViewport = { width: 400, height: 420 };
    const layout = computeLobbyLayout(shortViewport, ZERO_INSETS, 50);
    expect(layout.rows.length).toBeLessThan(50);
    expect(layout.rows.length).toBe(layout.maxVisibleRows);
    for (const row of layout.rows) {
      expect(row.y + layout.rowHeight).toBeLessThanOrEqual(
        layout.contentRect.y + layout.contentRect.height + 1, // +1 for float rounding
      );
    }
  });

  it('renders fewer rows than requested when entryCount is below capacity, not padding with empty rows', () => {
    const layout = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 3);
    expect(layout.rows.length).toBe(3);
  });

  it('shifts every element inward when safe-area insets are applied (Part D)', () => {
    const noInsets = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 5);
    const withInsets = computeLobbyLayout(
      MID_TABLET_PANEL,
      { top: 40, right: 10, bottom: 20, left: 15 },
      5,
    );

    expect(withInsets.status.x).toBeGreaterThan(noInsets.status.x);
    expect(withInsets.status.y).toBeGreaterThan(noInsets.status.y);
    expect(withInsets.contentRect.width).toBeLessThan(noInsets.contentRect.width);
    expect(withInsets.contentRect.height).toBeLessThan(noInsets.contentRect.height);
  });

  it('reduces max visible rows when a large bottom inset eats into available height', () => {
    const noInsets = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 20);
    const withBottomInset = computeLobbyLayout(
      MID_TABLET_PANEL,
      { top: 0, right: 0, bottom: 200, left: 0 },
      20,
    );
    expect(withBottomInset.maxVisibleRows).toBeLessThan(noInsets.maxVisibleRows);
  });

  it('never produces a negative row count or NaN when insets exceed the viewport', () => {
    const layout = computeLobbyLayout(
      { width: 320, height: 400 },
      { top: 300, right: 0, bottom: 300, left: 0 },
      10,
    );
    expect(layout.maxVisibleRows).toBe(0);
    expect(layout.rows.length).toBe(0);
    expect(Number.isFinite(layout.contentRect.height)).toBe(true);
    expect(layout.contentRect.height).toBeGreaterThanOrEqual(0);
  });

  it('centers the content block on a very wide desktop viewport instead of leaving it pinned to the left edge', () => {
    // Regression test: a real browser screenshot on a wide window
    // (see project notes) showed all content jammed in the top-left
    // corner with a large empty gap on the right -- correct per the
    // scale formula (wide-but-normal-height barely scales past 1x),
    // but not a layout that actually looks intentional.
    const narrowLayout = computeLobbyLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 3);
    const wideLayout = computeLobbyLayout(WIDE_DESKTOP, ZERO_INSETS, 3);
    const narrowLeftGap = narrowLayout.status.x - narrowLayout.contentRect.x;
    const wideLeftGap = wideLayout.status.x - wideLayout.contentRect.x;
    // On the wide viewport, centering should have engaged and pushed
    // the content meaningfully further from the left edge than a flat
    // scaled-up left margin would (proof it's actually centering, not
    // just scaling the same fixed margin).
    expect(wideLeftGap).toBeGreaterThan(narrowLeftGap * 5);
    // ...but not so far that it's pushed past the horizontal middle.
    expect(wideLeftGap).toBeLessThan(wideLayout.contentRect.width / 2);
  });

  it('keeps the original left-margin behavior unchanged on a viewport too narrow for centering to apply (no regression)', () => {
    // 360px-wide phone-portrait (NARROW_PHONE_PORTRAIT) turns out to
    // ALREADY be wide enough to trigger centering at its own scale --
    // correctly so, a 360px screen shouldn't pin a ~300px-wide content
    // block 18px from the left either. Use a narrower viewport here
    // specifically to exercise the untouched natural-left-margin
    // fallback path.
    const veryNarrow = { width: 300, height: 500 };
    const layout = computeLobbyLayout(veryNarrow, ZERO_INSETS, 3);
    expect(layout.status.x).toBeCloseTo(24 * layout.scale, 5);
  });

  it('Part E: the Quick Play button always meets the minimum touch-target size, at any viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeLobbyLayout(viewport, ZERO_INSETS, 5);
      expect(layout.quickPlayButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX - 0.001);
      expect(layout.quickPlayButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX - 0.001);
    }
  });

  it('Part E: the Quick Play button sits inside the content rect and never collides with the leaderboard column', () => {
    const layout = computeLobbyLayout(MID_TABLET_PANEL, ZERO_INSETS, 10);
    expect(layout.quickPlayButton.x).toBeGreaterThanOrEqual(layout.contentRect.x);
    expect(layout.quickPlayButton.x + layout.quickPlayButton.width).toBeLessThanOrEqual(
      layout.contentRect.x + layout.contentRect.width + 0.001,
    );
    // To the right of every leaderboard row's own x (rows use the
    // same left margin as status/identity/rank/header).
    for (const row of layout.rows) {
      expect(layout.quickPlayButton.x).toBeGreaterThan(row.x);
    }
  });
});
