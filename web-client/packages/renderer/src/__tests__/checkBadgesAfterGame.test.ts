import { describe, expect, it } from 'vitest';
import type { GameSummaryMsg } from '@kadi/protocol';
import {
  applyGameSummary,
  awardBadge,
  checkBadgesAfterGame,
  defaultProfile,
  difficultiesPlayed,
  type ProfileData,
} from '../profileData.js';

function summary(overrides: Partial<GameSummaryMsg> = {}): GameSummaryMsg {
  return {
    type: 'game_summary',
    you: 0,
    won: true,
    mode: 'single_player',
    difficulty: 'MEDIUM',
    finish_kind: null,
    opponent_had_msomi: false,
    elimination_mode: false,
    cards_played: 0,
    cards_drawn: 0,
    biggest_pickup_absorbed: 0,
    kadi_declarations: 0,
    aces_played: 0,
    jump_skips_dealt: 0,
    kickback_reversals: 0,
    ace_shield_uses: 0,
    ace_shield_biggest: 0,
    jump_counter_depth: 0,
    near_kadi_count: 0,
    undo_used_this_game: false,
    bluff_suit_win: false,
    kuficha_trap_win: false,
    ...overrides,
  };
}

describe('awardBadge', () => {
  it('awards an unearned badge and unlocks its cosmetic', () => {
    const profile = defaultProfile();
    const newly = awardBadge(profile, 'beat_hard'); // -> felt_theme 'crimson'
    expect(newly).toBe(true);
    expect(profile.badges.beat_hard).toBeDefined();
    expect(profile.cosmetics.owned_felt_themes).toContain('crimson');
  });

  it('is a no-op for an already-earned badge', () => {
    const profile = defaultProfile();
    awardBadge(profile, 'beat_hard');
    const earnedAt = profile.badges.beat_hard;
    const again = awardBadge(profile, 'beat_hard');
    expect(again).toBe(false);
    expect(profile.badges.beat_hard).toBe(earnedAt);
  });

  it('is a silent no-op for an unknown badge id (matches Python award_badge)', () => {
    const profile = defaultProfile();
    expect(awardBadge(profile, 'not_a_real_badge')).toBe(false);
    expect(profile.badges['not_a_real_badge']).toBeUndefined();
  });
});

describe('checkBadgesAfterGame', () => {
  it('only awards beat_hard for a single_player HARD win, not other modes/difficulties', () => {
    const p1 = defaultProfile();
    checkBadgesAfterGame(p1, { won: true, mode: 'single_player', difficulty: 'HARD', finish_kind: null, opponent_had_msomi: false });
    expect(p1.badges.beat_hard).toBeDefined();

    const p2 = defaultProfile();
    checkBadgesAfterGame(p2, { won: true, mode: 'single_player', difficulty: 'MEDIUM', finish_kind: null, opponent_had_msomi: false });
    expect(p2.badges.beat_hard).toBeUndefined();

    const p3 = defaultProfile();
    checkBadgesAfterGame(p3, { won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false });
    expect(p3.badges.beat_hard).toBeUndefined();
  });

  it('never awards win-gated badges on a loss', () => {
    const profile = defaultProfile();
    checkBadgesAfterGame(profile, {
      won: false, mode: 'single_player', difficulty: 'HARD', finish_kind: 'ace_finisher',
      opponent_had_msomi: true, bluff_suit_win: true, kuficha_trap_win: true,
      jump_counter_depth: 5, near_kadi_count: 5, cards_drawn: 0,
    });
    expect(Object.keys(profile.badges)).toHaveLength(0);
  });

  it('folds this game\'s tallies into lifetime counters (cumulative for sums, max for "biggest")', () => {
    const profile = defaultProfile();
    checkBadgesAfterGame(profile, {
      won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false,
      cards_played: 5, ace_shield_biggest: 3,
    });
    checkBadgesAfterGame(profile, {
      won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false,
      cards_played: 7, ace_shield_biggest: 2,
    });
    expect(profile.counters.cards_played).toBe(12); // 5 + 7, cumulative
    expect(profile.counters.ace_shield_biggest).toBe(3); // max(3, 2), not summed
  });

  it('awards a cards_played tier badge once the lifetime counter crosses the threshold', () => {
    const profile = defaultProfile();
    checkBadgesAfterGame(profile, {
      won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false,
      cards_played: 249,
    });
    expect(profile.badges.cards_played_250).toBeUndefined();
    checkBadgesAfterGame(profile, {
      won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false,
      cards_played: 1,
    });
    expect(profile.badges.cards_played_250).toBeDefined();
  });

  it('tracks a win streak across calls and resets it on a loss', () => {
    const profile = defaultProfile();
    for (let i = 0; i < 5; i++) {
      checkBadgesAfterGame(profile, { won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false });
    }
    expect(profile.counters.win_streak_current).toBe(5);
    expect(profile.badges.streak_5).toBeDefined();

    checkBadgesAfterGame(profile, { won: false, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false });
    expect(profile.counters.win_streak_current).toBe(0);
    expect(profile.counters.win_streak_best).toBe(5); // best is a high-water mark, doesn't reset
  });

  it('awards all_difficulties only once EASY/MEDIUM/HARD have each been played', () => {
    const profile = defaultProfile();
    profile.games_played.single_player.EASY = 1;
    profile.games_played.single_player.MEDIUM = 1;
    expect(difficultiesPlayed(profile).size).toBe(2);
    checkBadgesAfterGame(profile, { won: false, mode: 'single_player', difficulty: 'MEDIUM', finish_kind: null, opponent_had_msomi: false });
    expect(profile.badges.all_difficulties).toBeUndefined();

    profile.games_played.single_player.HARD = 1;
    checkBadgesAfterGame(profile, { won: false, mode: 'single_player', difficulty: 'HARD', finish_kind: null, opponent_had_msomi: false });
    expect(profile.badges.all_difficulties).toBeDefined();
  });

  it('requires a win AND a 10+ card pickup absorb for chain_breaker_10', () => {
    const lost = defaultProfile();
    checkBadgesAfterGame(lost, { won: false, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false, biggest_pickup_absorbed: 12 });
    expect(lost.badges.chain_breaker_10).toBeUndefined();

    const won = defaultProfile();
    checkBadgesAfterGame(won, { won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false, biggest_pickup_absorbed: 10 });
    expect(won.badges.chain_breaker_10).toBeDefined();
  });

  it('requires all three of lan/internet/hot_seat games_won for grand_slam', () => {
    const profile = defaultProfile();
    profile.games_won.internet = 1;
    profile.games_won.lan = 1;
    // hot_seat still 0
    checkBadgesAfterGame(profile, { won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false });
    expect(profile.badges.grand_slam).toBeUndefined();

    profile.games_won.hot_seat = 1;
    checkBadgesAfterGame(profile, { won: true, mode: 'internet', difficulty: null, finish_kind: null, opponent_had_msomi: false });
    expect(profile.badges.grand_slam).toBeDefined();
  });
});

describe('applyGameSummary', () => {
  it('increments games_played/games_won for a single_player summary at the reported difficulty', () => {
    const profile = defaultProfile();
    applyGameSummary(profile, summary({ mode: 'single_player', difficulty: 'HARD', won: true }));
    expect(profile.games_played.single_player.HARD).toBe(1);
    expect(profile.games_won.single_player.HARD).toBe(1);
    expect(profile.games_played.single_player.EASY).toBe(0);
  });

  it('increments the flat internet bucket (no difficulty) for an internet summary', () => {
    const profile = defaultProfile();
    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: false }));
    expect(profile.games_played.internet).toBe(1);
    expect(profile.games_won.internet).toBe(0);
  });

  it('increments games_played_with_msomi on the RAW opponent_had_msomi even on a loss, '
    + 'but only awards beat_msomi and increments games_won_with_msomi on a win', () => {
    const profile = defaultProfile();
    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: false, opponent_had_msomi: true }));
    expect(profile.msomi.games_played_with_msomi).toBe(1);
    expect(profile.msomi.games_won_with_msomi).toBe(0);
    expect(profile.badges.beat_msomi).toBeUndefined();

    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: true, opponent_had_msomi: true }));
    expect(profile.msomi.games_played_with_msomi).toBe(2);
    expect(profile.msomi.games_won_with_msomi).toBe(1);
    expect(profile.badges.beat_msomi).toBeDefined();
  });

  it('increments multi_card_finishes only on a win with a finish_kind', () => {
    const profile = defaultProfile();
    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: false, finish_kind: 'jump_bundle' }));
    expect(profile.multi_card_finishes.jump_bundle).toBe(0);

    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: true, finish_kind: 'jump_bundle' }));
    expect(profile.multi_card_finishes.jump_bundle).toBe(1);
  });

  it('returns the list of newly-earned badge ids and persists them onto the profile', () => {
    const profile = defaultProfile();
    const newly = applyGameSummary(profile, summary({ mode: 'single_player', difficulty: 'HARD', won: true }));
    expect(newly).toContain('beat_hard');
    expect(profile.badges.beat_hard).toBeDefined();
  });

  it('never mutates total_time_played_secs (no session timer exists client-side yet)', () => {
    const profile: ProfileData = { ...defaultProfile(), total_time_played_secs: 1234 };
    applyGameSummary(profile, summary());
    expect(profile.total_time_played_secs).toBe(1234);
  });

  it('rolls per-player server tallies straight into lifetime counters unchanged', () => {
    const profile = defaultProfile();
    applyGameSummary(profile, summary({ mode: 'internet', difficulty: null, won: true, aces_played: 3, kadi_declarations: 1 }));
    expect(profile.counters.aces_played).toBe(3);
    expect(profile.counters.kadi_declarations).toBe(1);
  });
});
