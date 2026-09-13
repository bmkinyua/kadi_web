import { describe, expect, it } from 'vitest';
import {
  BADGE_CATEGORIES,
  BADGE_DEFS,
  CARD_BACK_STYLES,
  FELT_THEMES,
  cosmeticUnlockHint,
  defaultProfile,
  mergeProfile,
  resolveTableCosmetics,
  totalGamesPlayed,
} from '../profileData.js';

describe('BADGE_DEFS', () => {
  it('ports exactly 74 badges from core/profile_store.py BADGE_DEFS', () => {
    expect(Object.keys(BADGE_DEFS)).toHaveLength(74);
  });

  it('assigns every badge to one of the five known categories', () => {
    for (const badge of Object.values(BADGE_DEFS)) {
      expect(BADGE_CATEGORIES).toContain(badge.category);
    }
  });

  it('gives every cosmetic-granting badge a cosmetic that actually exists', () => {
    for (const badge of Object.values(BADGE_DEFS)) {
      if (!badge.cosmetic) continue;
      const table = badge.cosmetic.kind === 'card_back' ? CARD_BACK_STYLES : FELT_THEMES;
      expect(table[badge.cosmetic.key]).toBeDefined();
    }
  });

  it('has unique badge ids', () => {
    const ids = Object.keys(BADGE_DEFS);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('cosmeticUnlockHint', () => {
  it('returns the earning badge description for a badge-locked style', () => {
    // beat_hard -> felt_theme:crimson, per BADGE_DEFS
    expect(cosmeticUnlockHint('felt_theme', 'crimson')).toBe('Beat the AI on HARD difficulty.');
  });

  it('returns null for the always-owned default style', () => {
    expect(cosmeticUnlockHint('felt_theme', 'default')).toBeNull();
    expect(cosmeticUnlockHint('card_back', 'default')).toBeNull();
  });

  it('returns null for an unknown style key', () => {
    expect(cosmeticUnlockHint('card_back', 'not_a_real_style')).toBeNull();
  });
});

describe('defaultProfile', () => {
  it('starts with only the default cosmetics owned and equipped', () => {
    const p = defaultProfile();
    expect(p.cosmetics.owned_card_backs).toEqual(['default']);
    expect(p.cosmetics.owned_felt_themes).toEqual(['default']);
    expect(p.cosmetics.equipped_card_back).toBe('default');
    expect(p.cosmetics.equipped_felt_theme).toBe('default');
  });

  it('starts with zero games played across every mode', () => {
    expect(totalGamesPlayed(defaultProfile())).toBe(0);
  });

  it('starts with no badges earned', () => {
    expect(Object.keys(defaultProfile().badges)).toHaveLength(0);
  });
});

describe('mergeProfile', () => {
  it('returns a fresh default profile for null/undefined input', () => {
    expect(mergeProfile(null)).toEqual(defaultProfile());
    expect(mergeProfile(undefined)).toEqual(defaultProfile());
  });

  it('fills in missing top-level fields from an old/partial saved blob', () => {
    const partial = { cosmetics: { owned_card_backs: ['default', 'dots'], owned_felt_themes: ['default'], equipped_card_back: 'dots', equipped_felt_theme: 'default' } };
    const merged = mergeProfile(partial);
    expect(merged.cosmetics.equipped_card_back).toBe('dots');
    // everything NOT in the partial blob still comes from defaults:
    expect(merged.undo_tokens).toBe(defaultProfile().undo_tokens);
    expect(totalGamesPlayed(merged)).toBe(0);
  });

  it('fills in missing nested single_player difficulty fields', () => {
    const partial = { games_played: { single_player: { EASY: 3 } } } as never;
    const merged = mergeProfile(partial);
    expect(merged.games_played.single_player.EASY).toBe(3);
    expect(merged.games_played.single_player.MEDIUM).toBe(0);
    expect(merged.games_played.single_player.HARD).toBe(0);
    expect(merged.games_played.lan).toBe(0);
  });

  it('preserves earned badges from the saved blob', () => {
    const merged = mergeProfile({ badges: { beat_hard: '2026-01-01T00:00:00Z' } });
    expect(merged.badges.beat_hard).toBe('2026-01-01T00:00:00Z');
  });
});

describe('totalGamesPlayed', () => {
  it('sums every mode bucket, including both difficulty tables', () => {
    const p = defaultProfile();
    p.games_played.lan = 2;
    p.games_played.internet = 1;
    p.games_played.hot_seat = 3;
    p.games_played.single_player.EASY = 4;
    p.games_played.single_player_elimination.HARD = 5;
    expect(totalGamesPlayed(p)).toBe(2 + 1 + 3 + 4 + 5);
  });
});

describe('resolveTableCosmetics', () => {
  it('resolves the default profile to the default felt/card-back colors', () => {
    const c = resolveTableCosmetics(defaultProfile());
    expect(c.feltFill).toBe(FELT_THEMES.default.felt);
    expect(c.feltEdge).toBe(FELT_THEMES.default.edge);
    expect(c.cardBackA).toBe(CARD_BACK_STYLES.default.colorA);
    expect(c.cardBackB).toBe(CARD_BACK_STYLES.default.colorB);
  });

  it('resolves a different equipped felt theme to that theme\'s own colors', () => {
    const p = defaultProfile();
    p.cosmetics.equipped_felt_theme = 'crimson';
    const c = resolveTableCosmetics(p);
    expect(c.feltFill).toBe(FELT_THEMES.crimson.felt);
    expect(c.feltFill).not.toBe(FELT_THEMES.default.felt);
  });

  it('resolves a different equipped card back to that style\'s own colors', () => {
    const p = defaultProfile();
    p.cosmetics.equipped_card_back = 'starfield';
    const c = resolveTableCosmetics(p);
    expect(c.cardBackA).toBe(CARD_BACK_STYLES.starfield.colorA);
    expect(c.cardBackA).not.toBe(CARD_BACK_STYLES.default.colorA);
  });

  it('falls back to default for a corrupt/unknown equipped key rather than throwing', () => {
    const p = defaultProfile();
    p.cosmetics.equipped_felt_theme = 'not_a_real_theme';
    p.cosmetics.equipped_card_back = 'not_a_real_back';
    expect(() => resolveTableCosmetics(p)).not.toThrow();
    const c = resolveTableCosmetics(p);
    expect(c.feltFill).toBe(FELT_THEMES.default.felt);
    expect(c.cardBackA).toBe(CARD_BACK_STYLES.default.colorA);
  });
});
