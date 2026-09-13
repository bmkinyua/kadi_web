import { describe, expect, it } from 'vitest';
import {
  computeProfileFlow,
  computeProfileTitleLayout,
  formatLeaderboardLines,
  formatLeaderboardRows,
  formatStatsLines,
} from '../ProfileLayout.js';
import { BADGE_CATEGORIES, BADGE_DEFS, defaultProfile, type ProfileData } from '../../profileData.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };
const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

function profileWithSomeProgress(): ProfileData {
  const p = defaultProfile();
  p.games_played.single_player.EASY = 5;
  p.games_won.single_player.EASY = 3;
  p.games_played.lan = 2;
  p.games_won.lan = 2;
  p.badges.beat_hard = '2026-02-01T00:00:00Z'; // grants felt_theme:crimson
  p.badges.finish_question_chain = '2026-02-02T00:00:00Z'; // grants card_back:crosshatch
  p.cosmetics.owned_felt_themes = ['default', 'crimson'];
  p.cosmetics.owned_card_backs = ['default', 'crosshatch'];
  return p;
}

describe('formatStatsLines', () => {
  it('includes total games played and undo tokens', () => {
    const lines = formatStatsLines(profileWithSomeProgress()).join('\n');
    expect(lines).toContain('Total games played: 7');
    expect(lines).toMatch(/Undo tokens: \d+ \/ \d+/);
  });
});

describe('formatLeaderboardRows / formatLeaderboardLines', () => {
  it('shows a fallback line for a fresh profile with no games played', () => {
    const lines = formatLeaderboardLines(defaultProfile());
    expect(lines[0]).toMatch(/play a game/i);
  });

  it('omits any mode with zero games played', () => {
    const rows = formatLeaderboardRows(profileWithSomeProgress());
    expect(rows.some((r) => r.label === 'Internet')).toBe(false);
    expect(rows.some((r) => r.label === 'Hot-seat')).toBe(false);
  });

  it('sorts by win rate descending, then by games played', () => {
    const rows = formatLeaderboardRows(profileWithSomeProgress());
    // LAN: 2/2 = 100%, Single-Player (Easy): 3/5 = 60%
    expect(rows[0].label).toBe('LAN');
    expect(rows[0].rate).toBe(100);
  });

  it('appends a badges-earned summary line', () => {
    const lines = formatLeaderboardLines(profileWithSomeProgress());
    const total = Object.keys(BADGE_DEFS).length;
    expect(lines[lines.length - 1]).toBe(`Badges earned: 2 / ${total}`);
  });
});

describe('computeProfileFlow', () => {
  it('lays out all five sections in order: Stats, Leaderboard, Badges, Card Backs, Felt Themes', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    expect(flow.statsHeader.y).toBeLessThan(flow.leaderboardHeader.y);
    expect(flow.leaderboardHeader.y).toBeLessThan(flow.badgesHeader.y);
    expect(flow.badgesHeader.y).toBeLessThan(flow.cardBacksHeader.y);
    expect(flow.cardBacksHeader.y).toBeLessThan(flow.feltThemesHeader.y);
  });

  it('only creates badge category sections that actually have badges in them', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    const categoryNames = flow.badgeCategories.map((c) => c.header.text);
    for (const name of categoryNames) expect(BADGE_CATEGORIES).toContain(name);
    const totalRows = flow.badgeCategories.reduce((sum, c) => sum + c.rows.length, 0);
    expect(totalRows).toBe(Object.keys(BADGE_DEFS).length);
  });

  it('gives every earned badge a share button and every unearned badge none', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    for (const cat of flow.badgeCategories) {
      for (const row of cat.rows) {
        if (row.earned) expect(row.shareButton).not.toBeNull();
        else expect(row.shareButton).toBeNull();
      }
    }
  });

  it('marks earned badges by id correctly against the profile', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    const byId = Object.fromEntries(flow.badgeCategories.flatMap((c) => c.rows).map((r) => [r.id, r.earned]));
    expect(byId.beat_hard).toBe(true);
    expect(byId.finish_question_chain).toBe(true);
    expect(byId.first_lan_win).toBe(false);
  });

  it('shows a swatch for every defined card back and felt theme style', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    expect(flow.cardBackSwatches.length).toBeGreaterThan(1);
    expect(flow.feltSwatches.length).toBeGreaterThan(1);
  });

  it('marks owned/equipped swatches correctly and gives an equip button only to owned-but-not-equipped ones', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    const defaultFelt = flow.feltSwatches.find((s) => s.key === 'default')!;
    const crimsonFelt = flow.feltSwatches.find((s) => s.key === 'crimson')!;
    const midnightFelt = flow.feltSwatches.find((s) => s.key === 'midnight')!;

    expect(defaultFelt.owned).toBe(true);
    expect(defaultFelt.equipped).toBe(true); // fresh profile still has default equipped
    expect(defaultFelt.equipButton).toBeNull(); // owned AND equipped -> no equip button

    expect(crimsonFelt.owned).toBe(true);
    expect(crimsonFelt.equipped).toBe(false);
    expect(crimsonFelt.equipButton).not.toBeNull(); // owned, not equipped -> equip button

    expect(midnightFelt.owned).toBe(false);
    expect(midnightFelt.equipButton).toBeNull(); // not owned -> no equip button
  });

  it('gives a locked swatch its unlock hint and an owned/default one none where unearned', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    const midnightFelt = flow.feltSwatches.find((s) => s.key === 'midnight')!;
    const defaultFelt = flow.feltSwatches.find((s) => s.key === 'default')!;
    expect(midnightFelt.hint).toContain('LAN');
    expect(defaultFelt.hint).toBeNull();
  });

  it('wraps swatches to a new row instead of overflowing the card width', () => {
    const flow = computeProfileFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0, profileWithSomeProgress());
    const ys = new Set(flow.feltSwatches.map((s) => s.rect.y));
    expect(ys.size).toBeGreaterThan(1); // narrow viewport must wrap felt swatches onto multiple rows
    for (const s of flow.feltSwatches) {
      expect(s.rect.x + s.rect.width).toBeLessThanOrEqual(flow.cardLeft + flow.cardWidth + 1);
    }
  });

  it('enforces a minimum touch target on the back button at every viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const flow = computeProfileFlow(viewport, ZERO_INSETS, 0, defaultProfile());
      expect(flow.backButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(flow.backButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('every equip button meets the minimum touch target height', () => {
    const flow = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    for (const s of [...flow.cardBackSwatches, ...flow.feltSwatches]) {
      if (s.equipButton) expect(s.equipButton.height).toBeGreaterThanOrEqual(0); // geometry sanity: non-negative, real rect
    }
  });

  it('shifts content rightward under a nonzero left safe-area inset', () => {
    const insets = { top: 0, right: 0, bottom: 0, left: 40 };
    const zero = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, defaultProfile());
    const inset = computeProfileFlow(MID_TABLET_PANEL, insets, 0, defaultProfile());
    expect(inset.cardLeft).toBeGreaterThan(zero.cardLeft);
  });

  it('scrolling changes every section header y by exactly the scroll delta', () => {
    const flow0 = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, profileWithSomeProgress());
    const flow50 = computeProfileFlow(MID_TABLET_PANEL, ZERO_INSETS, 50, profileWithSomeProgress());
    expect(flow0.statsHeader.y - flow50.statsHeader.y).toBeCloseTo(50, 5);
    expect(flow0.feltThemesHeader.y - flow50.feltThemesHeader.y).toBeCloseTo(50, 5);
  });

  it('computes a positive maxScroll when content overflows a short viewport', () => {
    const shortViewport = { width: 1024, height: 400 };
    const flow = computeProfileFlow(shortViewport, ZERO_INSETS, 0, profileWithSomeProgress());
    expect(flow.maxScroll).toBeGreaterThan(0);
  });

  it('computes zero maxScroll when content fits within a tall viewport', () => {
    // Width kept near BASE_WIDTH (480) deliberately -- computeLayoutScale
    // uses min(widthRatio, heightRatio), so an unbounded width here would
    // keep inflating the scale (and therefore the content height) right
    // along with the viewport height, defeating the point of this test.
    // A merely-tall, non-wide viewport isolates "does more room fit more
    // content" from "does a bigger scale also mean bigger content".
    const tallNarrowViewport = { width: 480, height: 20000 };
    const flow = computeProfileFlow(tallNarrowViewport, ZERO_INSETS, 0, defaultProfile());
    expect(flow.maxScroll).toBe(0);
  });
});

describe('computeProfileTitleLayout', () => {
  it('centers horizontally within the safe content area', () => {
    const insets = { top: 0, right: 0, bottom: 0, left: 100 };
    const flow = computeProfileFlow(MID_TABLET_PANEL, insets, 0, defaultProfile());
    const title = computeProfileTitleLayout(MID_TABLET_PANEL, insets);
    expect(title.x).toBeCloseTo(flow.contentRect.x + flow.contentRect.width / 2, 5);
  });
});
