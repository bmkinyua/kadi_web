import { describe, expect, it } from 'vitest';
import {
  computeInternetLobbyBrowseLayout,
  computeInternetLobbyRosterLayout,
} from '../InternetLobbyLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('computeInternetLobbyBrowseLayout', () => {
  it('places title/host form/search/list header/back button in top-to-bottom order', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeInternetLobbyBrowseLayout(viewport, ZERO_INSETS, 5);
      expect(layout.title.y).toBeLessThan(layout.hostLabel.y);
      expect(layout.hostLabel.y).toBeLessThan(layout.gameNameField.y);
      expect(layout.gameNameField.y).toBeLessThan(layout.hostButton.y);
      expect(layout.hostButton.y).toBeLessThan(layout.searchField.y);
      expect(layout.searchField.y).toBeLessThan(layout.listHeader.y);
      expect(layout.listHeader.y).toBeLessThan(layout.backButton.y);
    }
  });

  it('grows scale/fonts on a larger viewport, same as the other renderer scenes', () => {
    const phoneLayout = computeInternetLobbyBrowseLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 3);
    const tabletLayout = computeInternetLobbyBrowseLayout(MID_TABLET_PANEL, ZERO_INSETS, 3);
    expect(tabletLayout.scale).toBeGreaterThan(phoneLayout.scale);
    expect(tabletLayout.title.fontPx).toBeGreaterThan(phoneLayout.title.fontPx);
    expect(tabletLayout.hostButton.width).toBeGreaterThan(phoneLayout.hostButton.width);
  });

  it('caps visible game rows to what fits below the search field, rather than overflowing past Back', () => {
    const shortViewport = { width: 400, height: 420 };
    const layout = computeInternetLobbyBrowseLayout(shortViewport, ZERO_INSETS, 50);
    expect(layout.rows.length).toBeLessThan(50);
    expect(layout.rows.length).toBe(layout.maxVisibleRows);
    for (const row of layout.rows) {
      expect(row.y + row.height).toBeLessThanOrEqual(layout.backButton.y + 1);
    }
  });

  it('renders exactly as many rows as there are games when under capacity, no empty padding rows', () => {
    const layout = computeInternetLobbyBrowseLayout(MID_TABLET_PANEL, ZERO_INSETS, 2);
    expect(layout.rows.length).toBe(2);
  });

  it('never produces a negative row count or NaN when insets swallow the whole viewport', () => {
    const layout = computeInternetLobbyBrowseLayout(
      { width: 320, height: 400 },
      { top: 300, right: 0, bottom: 300, left: 0 },
      10,
    );
    expect(layout.maxVisibleRows).toBe(0);
    expect(layout.rows.length).toBe(0);
    expect(Number.isFinite(layout.contentRect.height)).toBe(true);
    expect(layout.contentRect.height).toBeGreaterThanOrEqual(0);
  });

  it('keeps every Join button (and the host/back buttons) at or above the minimum touch target', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeInternetLobbyBrowseLayout(viewport, ZERO_INSETS, 6);
      expect(layout.hostButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.hostButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.backButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.backButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      for (const row of layout.rows) {
        expect(row.joinButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
        expect(row.joinButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
        // The Join button must stay nested inside its own row, not
        // spill past the row's right/bottom edge.
        expect(row.joinButton.x).toBeGreaterThanOrEqual(row.x);
        expect(row.joinButton.x + row.joinButton.width).toBeLessThanOrEqual(row.x + row.width + 1);
        expect(row.joinButton.y).toBeGreaterThanOrEqual(row.y - 1);
      }
    }
  });

  it('shifts every element inward when safe-area insets are applied', () => {
    const noInsets = computeInternetLobbyBrowseLayout(MID_TABLET_PANEL, ZERO_INSETS, 4);
    const withInsets = computeInternetLobbyBrowseLayout(
      MID_TABLET_PANEL,
      { top: 40, right: 10, bottom: 20, left: 15 },
      4,
    );
    expect(withInsets.gameNameField.x).toBeGreaterThan(noInsets.gameNameField.x);
    expect(withInsets.title.y).toBeGreaterThan(noInsets.title.y);
    expect(withInsets.contentRect.width).toBeLessThan(noInsets.contentRect.width);
  });

  it('centers the single-column content block on a very wide desktop viewport', () => {
    const narrowLayout = computeInternetLobbyBrowseLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 3);
    const wideLayout = computeInternetLobbyBrowseLayout(WIDE_DESKTOP, ZERO_INSETS, 3);
    const narrowLeftGap = narrowLayout.gameNameField.x - narrowLayout.contentRect.x;
    const wideLeftGap = wideLayout.gameNameField.x - wideLayout.contentRect.x;
    expect(wideLeftGap).toBeGreaterThan(narrowLeftGap * 5);
    expect(wideLeftGap).toBeLessThan(wideLayout.contentRect.width / 2);
  });
});

describe('computeInternetLobbyRosterLayout', () => {
  it('places title/subtitle/roster header/rows above the Start and Back buttons', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeInternetLobbyRosterLayout(viewport, ZERO_INSETS, 3);
      expect(layout.title.y).toBeLessThan(layout.subtitle.y);
      expect(layout.subtitle.y).toBeLessThan(layout.rosterHeader.y);
      expect(layout.rosterHeader.y).toBeLessThan(layout.startButton.y);
      expect(layout.startButton.y).toBeLessThan(layout.backButton.y);
    }
  });

  it('caps roster rows to what fits above the Start button on a short viewport', () => {
    const shortViewport = { width: 400, height: 420 };
    const layout = computeInternetLobbyRosterLayout(shortViewport, ZERO_INSETS, 50);
    expect(layout.rows.length).toBeLessThan(50);
    expect(layout.rows.length).toBe(layout.maxVisibleRows);
    for (const row of layout.rows) {
      expect(row.y).toBeLessThan(layout.startButton.y);
    }
  });

  it('renders exactly as many roster rows as players when under capacity', () => {
    const layout = computeInternetLobbyRosterLayout(MID_TABLET_PANEL, ZERO_INSETS, 2);
    expect(layout.rows.length).toBe(2);
  });

  it('keeps the Start and Back buttons at or above the minimum touch target', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeInternetLobbyRosterLayout(viewport, ZERO_INSETS, 4);
      expect(layout.startButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.startButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.backButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(layout.backButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('never produces a negative row count or NaN when insets swallow the whole viewport', () => {
    const layout = computeInternetLobbyRosterLayout(
      { width: 320, height: 400 },
      { top: 300, right: 0, bottom: 300, left: 0 },
      10,
    );
    expect(layout.maxVisibleRows).toBe(0);
    expect(layout.rows.length).toBe(0);
    expect(Number.isFinite(layout.contentRect.height)).toBe(true);
  });

  it('does not let the Start button collide with the Back button at any viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeInternetLobbyRosterLayout(viewport, ZERO_INSETS, 4);
      expect(layout.startButton.y + layout.startButton.height).toBeLessThanOrEqual(
        layout.backButton.y + 1,
      );
    }
  });
});
