// Shared by write-profile-once.ts / write-profile-different.ts, same
// "deliberately untyped, not importing ProfileData from
// packages/renderer" reasoning as sampleSettings.ts -- see that
// file's own comment and PlatformAdapter.ts's docstring on
// getProfile()/saveProfile() staying untyped at this layer.
export const SAMPLE_PROFILE_A = {
  games_played: {
    single_player: { EASY: 5, MEDIUM: 2, HARD: 1 },
    single_player_elimination: { EASY: 0, MEDIUM: 0, HARD: 0 },
    lan: 3,
    internet: 1,
    hot_seat: 0,
  },
  games_won: {
    single_player: { EASY: 3, MEDIUM: 1, HARD: 0 },
    single_player_elimination: { EASY: 0, MEDIUM: 0, HARD: 0 },
    lan: 2,
    internet: 0,
    hot_seat: 0,
  },
  multi_card_finishes: { question_chain: 1, kickback_run: 0, jump_bundle: 0, ace_finisher: 0 },
  msomi: { models_trained: 0, games_played_with_msomi: 0, games_won_with_msomi: 0 },
  total_time_played_secs: 3600,
  undo_tokens: 3,
  badges: { finish_question_chain: '2026-02-02T00:00:00Z' },
  cosmetics: {
    owned_card_backs: ['default', 'crosshatch'],
    owned_felt_themes: ['default'],
    equipped_card_back: 'crosshatch',
    equipped_felt_theme: 'default',
  },
};

export const SAMPLE_PROFILE_B = {
  ...SAMPLE_PROFILE_A,
  games_played: { ...SAMPLE_PROFILE_A.games_played, lan: 10 },
  badges: { ...SAMPLE_PROFILE_A.badges, beat_hard: '2026-02-05T00:00:00Z' },
  cosmetics: {
    owned_card_backs: ['default', 'crosshatch'],
    owned_felt_themes: ['default', 'crimson'],
    equipped_card_back: 'crosshatch',
    equipped_felt_theme: 'crimson',
  },
};
