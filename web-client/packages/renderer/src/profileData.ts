/**
 * KADI web-client — profile data model, ported from core/profile_store.py
 * (`default_profile()`, `BADGE_DEFS`, `cosmetic_unlock_hint`,
 * `total_games_played`, `difficulties_played`, `award_badge`,
 * `check_badges_after_game`) and constants.py (`CARD_BACK_STYLES`,
 * `FELT_THEMES`), for ProfileScene.ts / layout/ProfileLayout.ts /
 * GameTableScene.ts's cosmetics wiring (Part D) AND (this delivery)
 * GameTableScene.ts's GAME_OVER -> saveProfile() hook.
 *
 * `counters` (the lifetime running-total bucket feeding the tiered
 * "Meta" badge ladders -- cards_played_250, kadi_50, streak_5, ...)
 * and win-streak tracking are NEW in this delivery: the earlier
 * Profile-screen-only pass deliberately left them out (see this
 * file's prior revision's own docstring: "nothing in this web pass's
 * task brief asks for GameTableScene to start writing win/loss/badge
 * data on GAME_OVER, and no such hook exists yet"). That hook now
 * exists (GameTableScene.ts's 'game_summary' handler -> applyGameSummary
 * below), so the bucket that check_badges_after_game's tier ladders
 * actually read had to be added here first -- there was nowhere to
 * fold a finished game's tallies into otherwise. See §9.
 *
 * applyGameSummary() is the client-side counterpart to
 * core.game_manager.GameManager.finalize_profile_stats() +
 * core.profile_store.check_badges_after_game(): the PC combines both
 * into one call because GameManager already holds the live counters;
 * here the equivalent raw inputs arrive over the wire instead (see
 * @kadi/protocol's GameSummaryMsg), so this file's version takes that
 * message directly rather than a GameManager instance.
 *
 * total_time_played_secs is NOT accumulated by applyGameSummary --
 * this web client has no session-elapsed-time tracker anywhere yet
 * (GameTableScene.ts never starts one), unlike core/game_manager.py's
 * self._session_elapsed. Left at whatever the profile already had
 * (never regresses it) rather than guessing a delta; the "time_1h/
 * time_25h/time_100h" tier badges are consequently unreachable on web
 * until a real session timer exists to feed this -- flagged here
 * explicitly, not silently almost-right.
 *
 * Colors are exposed as Phaser-style 0xRRGGBB numbers (not CSS hex
 * strings), matching every other color constant already used in
 * GameTableScene.ts/SettingsScene.ts, converted once here from the
 * PC's (r, g, b) tuples rather than re-guessed.
 */
import type { GameSummaryMsg } from '@kadi/protocol';

export type Rgb = [number, number, number];

function rgbToHexNumber([r, g, b]: Rgb): number {
  return ((r & 0xff) << 16) | ((g & 0xff) << 8) | (b & 0xff);
}

// ─── Cosmetics: table felt themes (constants.py FELT_THEMES) ──────────────
export interface FeltThemeStyle {
  felt: number;
  edge: number;
  bg: number;
  label: string;
}

const FELT_THEMES_RGB: Record<string, { felt: Rgb; edge: Rgb; bg: Rgb; label: string }> = {
  default: { felt: [34, 85, 45], edge: [18, 50, 25], bg: [27, 69, 37], label: 'Classic Green' },
  crimson: { felt: [110, 35, 35], edge: [60, 15, 15], bg: [85, 27, 27], label: 'Crimson' },
  midnight: { felt: [28, 35, 70], edge: [12, 16, 35], bg: [20, 26, 55], label: 'Midnight Blue' },
  royal_blue: { felt: [25, 70, 120], edge: [12, 35, 60], bg: [18, 55, 95], label: 'Royal Blue' },
  amber: { felt: [120, 80, 20], edge: [60, 38, 8], bg: [95, 63, 15], label: 'Amber' },
  teal_quilt: { felt: [20, 80, 85], edge: [10, 40, 45], bg: [15, 60, 65], label: 'Diamond Quilt' },
  plum_herringbone: { felt: [70, 25, 55], edge: [35, 10, 28], bg: [55, 20, 42], label: 'Plum Herringbone' },
  graphite_pinstripe: { felt: [45, 45, 50], edge: [20, 20, 24], bg: [35, 35, 40], label: 'Graphite Pinstripe' },
  copper_checker: { felt: [100, 60, 25], edge: [50, 28, 10], bg: [80, 48, 20], label: 'Copper Checkerboard' },
  gold_honeycomb: { felt: [90, 75, 20], edge: [45, 36, 8], bg: [70, 58, 15], label: 'Golden Honeycomb' },
  indigo_constellation: { felt: [20, 22, 55], edge: [10, 10, 30], bg: [15, 17, 42], label: 'Constellation Night' },
};

export const FELT_THEMES: Record<string, FeltThemeStyle> = Object.fromEntries(
  Object.entries(FELT_THEMES_RGB).map(([key, v]) => [
    key,
    { felt: rgbToHexNumber(v.felt), edge: rgbToHexNumber(v.edge), bg: rgbToHexNumber(v.bg), label: v.label },
  ]),
);

// ─── Cosmetics: card back designs (constants.py CARD_BACK_STYLES) ─────────
// PC generates a real procedural pattern (diagonal/dots/chevron/etc.)
// per style from these (a, b) color pairs -- see AssetLoader's card-
// back generator. This web pass has no card-art pipeline at all yet
// (GameTableScene.ts's own header: cards are drawn as code, not image
// sprites), so `pattern` is carried over as data (for a future pass)
// but not yet rendered; GameTableScene.ts's cosmetics wiring (Part D)
// only applies the two flat colors as a gradient -- see
// resolveTableCosmetics() below.
export interface CardBackStyle {
  colorA: number;
  colorB: number;
  pattern: string;
  label: string;
}

const CARD_BACK_STYLES_RGB: Record<string, { a: Rgb; b: Rgb; pattern: string; label: string }> = {
  default: { a: [60, 30, 100], b: [90, 50, 150], pattern: 'diagonal', label: 'Classic Purple' },
  crosshatch: { a: [30, 60, 60], b: [50, 100, 100], pattern: 'crosshatch', label: 'Teal Crosshatch' },
  dots: { a: [80, 40, 20], b: [140, 80, 40], pattern: 'dots', label: 'Copper Dots' },
  chevron: { a: [20, 55, 25], b: [45, 100, 50], pattern: 'chevron', label: 'Forest Chevron' },
  starfield: { a: [15, 15, 40], b: [40, 40, 90], pattern: 'starfield', label: 'Starfield' },
  houndstooth: { a: [15, 60, 65], b: [40, 130, 140], pattern: 'houndstooth', label: 'Houndstooth' },
  hex_lattice: { a: [70, 20, 55], b: [150, 45, 100], pattern: 'hex_lattice', label: 'Hex Lattice' },
  herringbone_back: { a: [25, 25, 25], b: [170, 170, 170], pattern: 'herringbone_back', label: 'Herringbone' },
  pinwheel: { a: [12, 12, 12], b: [190, 150, 50], pattern: 'pinwheel', label: 'Pinwheel' },
  concentric_diamonds: { a: [15, 60, 65], b: [40, 130, 140], pattern: 'concentric_diamonds', label: 'Concentric Diamonds' },
  basket_weave: { a: [70, 20, 55], b: [150, 45, 100], pattern: 'basket_weave', label: 'Basket Weave' },
  checkerboard_back: { a: [110, 40, 30], b: [230, 120, 60], pattern: 'checkerboard_back', label: 'Checkerboard' },
  honeycomb_back: { a: [12, 12, 12], b: [190, 150, 50], pattern: 'honeycomb_back', label: 'Honeycomb' },
  sunburst: { a: [15, 60, 65], b: [40, 130, 140], pattern: 'sunburst', label: 'Sunburst' },
  bullseye: { a: [70, 20, 55], b: [150, 45, 100], pattern: 'bullseye', label: 'Bullseye' },
  zigzag: { a: [25, 25, 25], b: [170, 170, 170], pattern: 'zigzag', label: 'Zigzag' },
};

export const CARD_BACK_STYLES: Record<string, CardBackStyle> = Object.fromEntries(
  Object.entries(CARD_BACK_STYLES_RGB).map(([key, v]) => [
    key,
    { colorA: rgbToHexNumber(v.a), colorB: rgbToHexNumber(v.b), pattern: v.pattern, label: v.label },
  ]),
);

// ─── Badges (core/profile_store.py BADGE_DEFS) ─────────────────────────────
// [id, name, desc, category, cosmeticKind|null, cosmeticKey|null] --
// a flat tuple list (rather than a nested object literal per badge)
// purely to keep this 74-entry table scannable; ported verbatim
// (names/descriptions are the real player-facing copy, not
// paraphrased) against core/profile_store.py's BADGE_DEFS, in the
// same order, so a future diff against the Python source stays easy.
type BadgeTuple = [string, string, string, string, string | null, string | null];

const BADGE_TUPLES: BadgeTuple[] = [
  ['beat_hard', 'Hard-Mode Champion', 'Beat the AI on HARD difficulty.', 'Single-Player Skill', 'felt_theme', 'crimson'],
  ['finish_question_chain', 'Interrogator', 'Win with a Question-chain finish.', 'Single-Player Skill', 'card_back', 'crosshatch'],
  ['finish_kickback_run', 'Boomerang', 'Win with an even-Kickback-run finish.', 'Single-Player Skill', 'card_back', 'dots'],
  ['finish_jump_bundle', 'Leapfrog', 'Win with a Jump-bundle finish.', 'Single-Player Skill', 'card_back', 'chevron'],
  ['finish_ace_finisher', 'Ace Up the Sleeve', 'Win with an ACE-finisher.', 'Single-Player Skill', 'felt_theme', 'royal_blue'],
  ['first_lan_win', 'LAN Party Champ', 'Win your first LAN multiplayer match.', 'Multiplayer', 'felt_theme', 'midnight'],
  ['first_internet_win', 'Global Contender', 'Win your first Internet multiplayer match.', 'Multiplayer', 'card_back', 'starfield'],
  ['first_hotseat_win', 'Couch Champion', 'Win your first hot-seat match.', 'Multiplayer', null, null],
  ['first_model_trained', 'Chuo Apprentice', 'Train your first model in Chuo.', 'MSOMI / Chuo', null, null],
  ['beat_msomi', 'Machine Slayer', 'Win a game with a MSOMI model attached to an opponent.', 'MSOMI / Chuo', 'felt_theme', 'amber'],
  ['games_played_10', 'Getting the Hang of It', 'Play 10 games.', 'Meta', null, null],
  ['games_played_50', 'Regular', 'Play 50 games.', 'Meta', null, null],
  ['games_played_100', 'Century Club', 'Play 100 games.', 'Meta', 'felt_theme', 'royal_blue'],
  ['all_difficulties', 'Well Rounded', 'Play on all three difficulties at least once.', 'Meta', null, null],
  ['chain_breaker_10', 'Chain Breaker', 'Absorb a pickup chain of 10+ cards in one turn and still win the round.', 'Single-Player Skill', 'card_back', 'hex_lattice'],
  ['clean_sweep', 'Clean Sweep', 'Win a game without ever drawing a card.', 'Single-Player Skill', 'felt_theme', 'teal_quilt'],
  ['kuficha_joker', 'The Trap', 'Hoard a pickup card, then play it and declare KADI in the same move.', 'Single-Player Skill', 'card_back', 'houndstooth'],
  ['poker_face', 'Poker Face', 'Win off a decoy suit-request bluff on a lone-ACE KADI declare.', 'Single-Player Skill', 'card_back', 'pinwheel'],
  ['jump_master', 'Jump Master', 'Win a round after countering a Jump with a Jump three or more times deep.', 'Single-Player Skill', 'card_back', 'zigzag'],
  ['nine_lives', 'Nine Lives', 'Win a game after dropping to exactly 1 card three or more separate times.', 'Single-Player Skill', 'felt_theme', 'plum_herringbone'],
  ['ace_shield_big', 'Shield Wall', 'Block a pickup chain of 5+ with an ACE shield.', 'Single-Player Skill', 'card_back', 'bullseye'],
  ['ace_shield_50', 'Guardian', 'Block a pickup chain with an ACE shield 50 times.', 'Single-Player Skill', 'felt_theme', 'copper_checker'],
  ['last_one_standing', 'Last One Standing', 'Win an Elimination Mode match.', 'Elimination Mode', 'card_back', 'basket_weave'],
  ['iron_will', 'Iron Will', 'Win an Elimination Mode match on HARD.', 'Elimination Mode', 'felt_theme', 'gold_honeycomb'],
  ['grand_slam', 'Grand Slam', 'Win at least one LAN, one Internet, and one hot-seat match.', 'Multiplayer', 'card_back', 'honeycomb_back'],
  ['streak_5', 'On a Roll', 'Win 5 games in a row.', 'Multiplayer', 'card_back', 'sunburst'],
  ['streak_10', 'Unstoppable', 'Win 10 games in a row.', 'Multiplayer', null, null],
  ['streak_20', 'Untouchable', 'Win 20 games in a row.', 'Multiplayer', 'felt_theme', 'indigo_constellation'],
  ['msomi_whisperer', 'MSOMI Whisperer', 'Beat a MSOMI-attached opponent 10 times.', 'MSOMI / Chuo', null, null],
  ['iterator', 'Iterator', 'Train 5 separate models in Chuo.', 'MSOMI / Chuo', null, null],
  ['cards_played_250', 'Dealt In', 'Play 250 cards, lifetime.', 'Meta', null, null],
  ['cards_played_1000', 'Card Shark', 'Play 1,000 cards, lifetime.', 'Meta', null, null],
  ['cards_played_5000', 'Table Regular', 'Play 5,000 cards, lifetime.', 'Meta', 'card_back', 'concentric_diamonds'],
  ['cards_played_15000', 'Kadi Institution', 'Play 15,000 cards, lifetime.', 'Meta', null, null],
  ['cards_drawn_100', 'Deck Diver', 'Draw 100 cards, lifetime.', 'Meta', null, null],
  ['cards_drawn_500', 'Glutton for Punishment', 'Draw 500 cards, lifetime.', 'Meta', null, null],
  ['cards_drawn_2000', 'Bottomless Hand', 'Draw 2,000 cards, lifetime.', 'Meta', null, null],
  ['pickup_hit_7', 'Took the Hit', 'Absorb a pickup of 7+ cards in one turn.', 'Meta', null, null],
  ['pickup_hit_12', 'Absorbed', 'Absorb a pickup of 12+ cards in one turn.', 'Meta', null, null],
  ['pickup_hit_18', 'Human Shield', 'Absorb a pickup of 18+ cards in one turn.', 'Meta', null, null],
  ['kadi_10', 'Calling It', 'Declare KADI 10 times, lifetime.', 'Meta', null, null],
  ['kadi_50', 'Confident', 'Declare KADI 50 times, lifetime.', 'Meta', null, null],
  ['kadi_200', 'Kadi! Kadi! Kadi!', 'Declare KADI 200 times, lifetime.', 'Meta', null, null],
  ['aces_25', 'Shapeshifter', 'Play 25 ACEs, lifetime.', 'Meta', null, null],
  ['aces_100', 'Suit Yourself', 'Play 100 ACEs, lifetime.', 'Meta', null, null],
  ['aces_400', 'Master of Suits', 'Play 400 ACEs, lifetime.', 'Meta', null, null],
  ['jump_skips_20', 'Skip Happens', 'Play 20 Jump cards, lifetime.', 'Meta', null, null],
  ['jump_skips_100', 'Turn Thief', 'Play 100 Jump cards, lifetime.', 'Meta', null, null],
  ['kickback_20', 'Reversal of Fortune', 'Play 20 Kickback cards, lifetime.', 'Meta', null, null],
  ['kickback_100', 'Spin Doctor', 'Play 100 Kickback cards, lifetime.', 'Meta', null, null],
  ['games_played_250', 'Card Table Fixture', 'Play 250 games.', 'Meta', null, null],
  ['games_played_500', 'Kadi Veteran', 'Play 500 games.', 'Meta', null, null],
  ['games_played_1000', 'Kadi Lifer', 'Play 1,000 games.', 'Meta', null, null],
  ['finish_question_chain_5', 'Interrogator II', 'Win with a Question-chain finish 5 times.', 'Meta', null, null],
  ['finish_question_chain_25', 'Interrogator III', 'Win with a Question-chain finish 25 times.', 'Meta', null, null],
  ['finish_question_chain_100', 'Grand Inquisitor', 'Win with a Question-chain finish 100 times.', 'Meta', null, null],
  ['finish_kickback_run_5', 'Boomerang II', 'Win with a Kickback-run finish 5 times.', 'Meta', null, null],
  ['finish_kickback_run_25', 'Boomerang III', 'Win with a Kickback-run finish 25 times.', 'Meta', null, null],
  ['finish_kickback_run_100', 'Perpetual Motion', 'Win with a Kickback-run finish 100 times.', 'Meta', null, null],
  ['finish_jump_bundle_5', 'Leapfrog II', 'Win with a Jump-bundle finish 5 times.', 'Meta', null, null],
  ['finish_jump_bundle_25', 'Leapfrog III', 'Win with a Jump-bundle finish 25 times.', 'Meta', null, null],
  ['finish_jump_bundle_100', 'Long Jump Legend', 'Win with a Jump-bundle finish 100 times.', 'Meta', null, null],
  ['finish_ace_finisher_5', 'Ace Up the Sleeve II', 'Win with an ACE-finisher 5 times.', 'Meta', null, null],
  ['finish_ace_finisher_25', 'Ace Up the Sleeve III', 'Win with an ACE-finisher 25 times.', 'Meta', null, null],
  ['finish_ace_finisher_100', "Card Counter's Nightmare", 'Win with an ACE-finisher 100 times.', 'Meta', null, null],
  ['undo_used_10', 'Do-Over', 'Use an undo token 10 times, lifetime.', 'Meta', null, null],
  ['undo_used_50', 'Ctrl+Z', 'Use an undo token 50 times, lifetime.', 'Meta', null, null],
  ['second_wind', 'Second Wind', 'Win a game after using an undo token.', 'Meta', 'card_back', 'herringbone_back'],
  ['purist_20', 'Purist', 'Complete 20 games without using an undo token.', 'Meta', 'card_back', 'checkerboard_back'],
  ['flawless_10', 'Immaculate', 'Win 10 games without ever drawing a card.', 'Meta', 'felt_theme', 'graphite_pinstripe'],
  ['flawless_50', 'Perfectionist', 'Win 50 games without ever drawing a card.', 'Meta', null, null],
  ['time_1h', 'Warming the Seat', '1 hour total time played.', 'Meta', null, null],
  ['time_25h', 'Dedicated', '25 hours total time played.', 'Meta', null, null],
  ['time_100h', 'Kadi Addict', '100 hours total time played.', 'Meta', null, null],
];

export interface BadgeDef {
  id: string;
  name: string;
  desc: string;
  category: string;
  cosmetic: { kind: 'card_back' | 'felt_theme'; key: string } | null;
}

export const BADGE_DEFS: Record<string, BadgeDef> = Object.fromEntries(
  BADGE_TUPLES.map(([id, name, desc, category, kind, key]) => [
    id,
    { id, name, desc, category, cosmetic: kind && key ? { kind: kind as 'card_back' | 'felt_theme', key } : null },
  ]),
);

/** Category display order -- matches BADGE_DEFS's own definition
 * order in profile_store.py (a plain dict, insertion-ordered), which
 * is what `by_cat` in scenes.ProfileScene.draw() iterates in. */
export const BADGE_CATEGORIES: string[] = [
  'Single-Player Skill',
  'Multiplayer',
  'MSOMI / Chuo',
  'Meta',
  'Elimination Mode',
];

// ─── Profile shape (core/profile_store.py default_profile()) ──────────────
export const DIFFICULTIES = ['EASY', 'MEDIUM', 'HARD'] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export interface ModeBuckets {
  single_player: Record<Difficulty, number>;
  single_player_elimination: Record<Difficulty, number>;
  lan: number;
  internet: number;
  hot_seat: number;
}

export interface ProfileData {
  games_played: ModeBuckets;
  games_won: ModeBuckets;
  multi_card_finishes: {
    question_chain: number;
    kickback_run: number;
    jump_bundle: number;
    ace_finisher: number;
  };
  msomi: {
    models_trained: number;
    games_played_with_msomi: number;
    games_won_with_msomi: number;
  };
  total_time_played_secs: number;
  undo_tokens: number;
  /** Lifetime running totals feeding the tiered "Meta" badge ladders
   * -- ported from core/profile_store.py's default_profile()
   * `counters` dict verbatim (field names match exactly). See this
   * file's own header for why this was missing until now. */
  counters: {
    cards_played: number;
    cards_drawn: number;
    biggest_pickup_absorbed: number; // high-water mark, not cumulative
    kadi_declarations: number;
    aces_played: number;
    jump_skips_dealt: number;
    kickback_reversals: number;
    ace_shield_uses: number;
    ace_shield_biggest: number; // high-water mark, not cumulative
    undo_tokens_used_total: number;
    flawless_game_count: number; // games won with 0 cards drawn
    undo_free_game_count: number; // completed games with no undo used
    win_streak_current: number;
    win_streak_best: number;
  };
  badges: Record<string, string>; // badge id -> ISO earned timestamp
  cosmetics: {
    owned_card_backs: string[];
    owned_felt_themes: string[];
    equipped_card_back: string;
    equipped_felt_theme: string;
  };
}

function freshModeBuckets(): ModeBuckets {
  return {
    single_player: { EASY: 0, MEDIUM: 0, HARD: 0 },
    single_player_elimination: { EASY: 0, MEDIUM: 0, HARD: 0 },
    lan: 0,
    internet: 0,
    hot_seat: 0,
  };
}

export function defaultProfile(): ProfileData {
  return {
    games_played: freshModeBuckets(),
    games_won: freshModeBuckets(),
    multi_card_finishes: { question_chain: 0, kickback_run: 0, jump_bundle: 0, ace_finisher: 0 },
    msomi: { models_trained: 0, games_played_with_msomi: 0, games_won_with_msomi: 0 },
    total_time_played_secs: 0,
    undo_tokens: 3, // UNDO_TOKENS_DEFAULT
    counters: {
      cards_played: 0, cards_drawn: 0, biggest_pickup_absorbed: 0,
      kadi_declarations: 0, aces_played: 0, jump_skips_dealt: 0,
      kickback_reversals: 0, ace_shield_uses: 0, ace_shield_biggest: 0,
      undo_tokens_used_total: 0, flawless_game_count: 0,
      undo_free_game_count: 0, win_streak_current: 0, win_streak_best: 0,
    },
    badges: {},
    cosmetics: {
      owned_card_backs: ['default'],
      owned_felt_themes: ['default'],
      equipped_card_back: 'default',
      equipped_felt_theme: 'default',
    },
  };
}

export const UNDO_TOKENS_MAX = 5;

/** Field-by-field merge over defaultProfile(), same purpose as
 * profile_store.py's `_deep_merge_defaults()`: a partial/older
 * profile blob (or one predating a newly-added field) never leaves a
 * field `undefined`. Shallow-merges each top-level bucket rather than
 * a generic deep merge -- sufficient here since every nested value in
 * ProfileData is itself a flat record, not arbitrarily nested. */
export function mergeProfile(stored: Partial<ProfileData> | null | undefined): ProfileData {
  const base = defaultProfile();
  if (!stored) return base;
  return {
    games_played: { ...base.games_played, ...stored.games_played,
      single_player: { ...base.games_played.single_player, ...stored.games_played?.single_player },
      single_player_elimination: { ...base.games_played.single_player_elimination, ...stored.games_played?.single_player_elimination } },
    games_won: { ...base.games_won, ...stored.games_won,
      single_player: { ...base.games_won.single_player, ...stored.games_won?.single_player },
      single_player_elimination: { ...base.games_won.single_player_elimination, ...stored.games_won?.single_player_elimination } },
    multi_card_finishes: { ...base.multi_card_finishes, ...stored.multi_card_finishes },
    msomi: { ...base.msomi, ...stored.msomi },
    total_time_played_secs: stored.total_time_played_secs ?? base.total_time_played_secs,
    undo_tokens: stored.undo_tokens ?? base.undo_tokens,
    counters: { ...base.counters, ...stored.counters },
    badges: { ...base.badges, ...stored.badges },
    cosmetics: { ...base.cosmetics, ...stored.cosmetics },
  };
}

export function totalGamesPlayed(profile: ProfileData): number {
  const gp = profile.games_played;
  return (
    gp.lan +
    gp.internet +
    gp.hot_seat +
    gp.single_player.EASY + gp.single_player.MEDIUM + gp.single_player.HARD +
    gp.single_player_elimination.EASY + gp.single_player_elimination.MEDIUM + gp.single_player_elimination.HARD
  );
}

/** Same purpose as profile_store.py's `cosmetic_unlock_hint()` --
 * which badge (if any) grants a locked cosmetic, for the tooltip. */
export function cosmeticUnlockHint(kind: 'card_back' | 'felt_theme', styleId: string): string | null {
  for (const info of Object.values(BADGE_DEFS)) {
    if (info.cosmetic && info.cosmetic.kind === kind && info.cosmetic.key === styleId) {
      return info.desc;
    }
  }
  return null;
}

// ─── Table cosmetics (Part D) ──────────────────────────────────────────────
export interface TableCosmetics {
  feltFill: number;
  feltEdge: number;
  cardBackA: number;
  cardBackB: number;
}

/**
 * Pure resolution of "which colors should the game table actually
 * draw", given a profile's equipped cosmetics -- the one function
 * GameTableScene.ts's rendering calls into for Part D, kept separate
 * from GameTableScene.ts itself so it's unit-testable without a
 * canvas/WebGL context (same "pure decision, thin Scene applier"
 * split as every layout/*.ts module -- see
 * __tests__/tableCosmetics.test.ts). Falls back to the 'default' style
 * for an equipped key that isn't a real style (shouldn't happen from
 * a real ProfileScene equip action, but keeps this total rather than
 * throwing on a corrupt/foreign persisted value).
 */
export function resolveTableCosmetics(profile: ProfileData): TableCosmetics {
  const felt = FELT_THEMES[profile.cosmetics.equipped_felt_theme] ?? FELT_THEMES.default;
  const back = CARD_BACK_STYLES[profile.cosmetics.equipped_card_back] ?? CARD_BACK_STYLES.default;
  return {
    feltFill: felt.felt,
    feltEdge: felt.edge,
    cardBackA: back.colorA,
    cardBackB: back.colorB,
  };
}

// ─── Badge awarding + end-of-game check (core/profile_store.py
// award_badge() / check_badges_after_game()) ────────────────────────────────

/** Same purpose as profile_store.py's `award_badge()`: award a badge
 * if not already earned (unlocking its cosmetic, if any), returning
 * whether this was newly earned (false for an already-owned or
 * unknown id — an unknown id is a silent no-op here too, matching
 * Python, rather than throwing on a typo'd badge id). */
export function awardBadge(profile: ProfileData, badgeId: string): boolean {
  if (!(badgeId in BADGE_DEFS) || badgeId in profile.badges) return false;
  profile.badges[badgeId] = new Date().toISOString();
  const unlock = BADGE_DEFS[badgeId].cosmetic;
  if (unlock) {
    const key = unlock.kind === 'card_back' ? 'owned_card_backs' : 'owned_felt_themes';
    const owned = profile.cosmetics[key];
    if (!owned.includes(unlock.key)) owned.push(unlock.key);
  }
  return true;
}

/** Same purpose as profile_store.py's `difficulties_played()`. */
export function difficultiesPlayed(profile: ProfileData): Set<Difficulty> {
  const gp = profile.games_played;
  const played = new Set<Difficulty>();
  for (const d of DIFFICULTIES) {
    if (gp.single_player[d] > 0 || gp.single_player_elimination[d] > 0) played.add(d);
  }
  return played;
}

const _FINISH_TIERS: Record<string, (number | string)[]> = {
  question_chain: [5, 'finish_question_chain_5', 25, 'finish_question_chain_25', 100, 'finish_question_chain_100'],
  kickback_run: [5, 'finish_kickback_run_5', 25, 'finish_kickback_run_25', 100, 'finish_kickback_run_100'],
  jump_bundle: [5, 'finish_jump_bundle_5', 25, 'finish_jump_bundle_25', 100, 'finish_jump_bundle_100'],
  ace_finisher: [5, 'finish_ace_finisher_5', 25, 'finish_ace_finisher_25', 100, 'finish_ace_finisher_100'],
};

/** Real port (not a reduced subset) of core/profile_store.py's
 * check_badges_after_game() — same 20 inputs (all but `profile` itself
 * optional/defaulted exactly as the Python signature defaults them),
 * same order of checks, same tier ladders, same lifetime-counter
 * folding. See that function's own docstring for the precondition
 * this shares: games_played/games_won/multi_card_finishes/msomi must
 * already be incremented for this game before calling this — see
 * applyGameSummary() below, this function's one real caller, which
 * does that first exactly like core.game_manager.finalize_profile_stats
 * does on the PC side. Mutates `profile` in place (badges, cosmetics,
 * counters) and returns the newly-earned badge ids, in the same
 * display order Python's `newly` list builds them in. */
export function checkBadgesAfterGame(profile: ProfileData, input: {
  won: boolean;
  mode: string;
  difficulty: Difficulty | null;
  finish_kind: 'question_chain' | 'kickback_run' | 'jump_bundle' | 'ace_finisher' | null;
  opponent_had_msomi: boolean;
  cards_played?: number;
  cards_drawn?: number;
  biggest_pickup_absorbed?: number;
  kadi_declarations?: number;
  aces_played?: number;
  jump_skips_dealt?: number;
  kickback_reversals?: number;
  ace_shield_uses?: number;
  ace_shield_biggest?: number;
  jump_counter_depth?: number;
  near_kadi_count?: number;
  undo_used_this_game?: boolean;
  bluff_suit_win?: boolean;
  kuficha_trap_win?: boolean;
  elimination_mode?: boolean;
}): string[] {
  const {
    won, mode, difficulty, finish_kind, opponent_had_msomi,
    cards_played = 0, cards_drawn = 0, biggest_pickup_absorbed = 0,
    kadi_declarations = 0, aces_played = 0, jump_skips_dealt = 0,
    kickback_reversals = 0, ace_shield_uses = 0, ace_shield_biggest = 0,
    jump_counter_depth = 0, near_kadi_count = 0,
    undo_used_this_game = false, bluff_suit_win = false,
    kuficha_trap_win = false, elimination_mode = false,
  } = input;

  const newly: string[] = [];
  const award = (bid: string) => { if (awardBadge(profile, bid)) newly.push(bid); };
  const tier = (value: number, ladder: (number | string)[]) => {
    for (let i = 0; i < ladder.length; i += 2) {
      if (value >= (ladder[i] as number)) award(ladder[i + 1] as string);
    }
  };

  if (won) {
    if (mode === 'single_player' && difficulty === 'HARD') award('beat_hard');
    if ((mode === 'single_player' || mode === 'single_player_elimination') && finish_kind) {
      award(({
        question_chain: 'finish_question_chain',
        kickback_run: 'finish_kickback_run',
        jump_bundle: 'finish_jump_bundle',
        ace_finisher: 'finish_ace_finisher',
      } as Record<string, string>)[finish_kind]);
    }
    if (mode === 'lan') award('first_lan_win');
    if (mode === 'internet') award('first_internet_win');
    if (mode === 'hot_seat') award('first_hotseat_win');
    if (opponent_had_msomi) award('beat_msomi');
    if (elimination_mode) {
      award('last_one_standing');
      if (difficulty === 'HARD') award('iron_will');
    }
    if (bluff_suit_win) award('poker_face');
    if (kuficha_trap_win) award('kuficha_joker');
    if (jump_counter_depth >= 3) award('jump_master');
    if (near_kadi_count >= 3) award('nine_lives');
    if (cards_drawn === 0) award('clean_sweep');
    if (undo_used_this_game) award('second_wind');
    const gw = profile.games_won;
    if (gw.lan >= 1 && gw.internet >= 1 && gw.hot_seat >= 1) award('grand_slam');
  }

  if (biggest_pickup_absorbed >= 10 && won) award('chain_breaker_10');
  if (ace_shield_biggest >= 5) award('ace_shield_big');

  const total = totalGamesPlayed(profile);
  tier(total, [10, 'games_played_10', 50, 'games_played_50', 100, 'games_played_100',
               250, 'games_played_250', 500, 'games_played_500', 1000, 'games_played_1000']);
  if (difficultiesPlayed(profile).size >= 3) award('all_difficulties');

  // Fold this game's tallies into lifetime counters.
  const c = profile.counters;
  c.cards_played += cards_played;
  c.cards_drawn += cards_drawn;
  c.biggest_pickup_absorbed = Math.max(c.biggest_pickup_absorbed, biggest_pickup_absorbed);
  c.kadi_declarations += kadi_declarations;
  c.aces_played += aces_played;
  c.jump_skips_dealt += jump_skips_dealt;
  c.kickback_reversals += kickback_reversals;
  c.ace_shield_uses += ace_shield_uses;
  c.ace_shield_biggest = Math.max(c.ace_shield_biggest, ace_shield_biggest);
  if (undo_used_this_game) {
    c.undo_tokens_used_total += 1;
  } else {
    c.undo_free_game_count += 1;
  }
  if (won && cards_drawn === 0) c.flawless_game_count += 1;
  if (won) {
    c.win_streak_current += 1;
    c.win_streak_best = Math.max(c.win_streak_best, c.win_streak_current);
  } else {
    c.win_streak_current = 0;
  }

  tier(c.cards_played, [250, 'cards_played_250', 1000, 'cards_played_1000', 5000, 'cards_played_5000', 15000, 'cards_played_15000']);
  tier(c.cards_drawn, [100, 'cards_drawn_100', 500, 'cards_drawn_500', 2000, 'cards_drawn_2000']);
  tier(c.biggest_pickup_absorbed, [7, 'pickup_hit_7', 12, 'pickup_hit_12', 18, 'pickup_hit_18']);
  tier(c.kadi_declarations, [10, 'kadi_10', 50, 'kadi_50', 200, 'kadi_200']);
  tier(c.aces_played, [25, 'aces_25', 100, 'aces_100', 400, 'aces_400']);
  tier(c.jump_skips_dealt, [20, 'jump_skips_20', 100, 'jump_skips_100']);
  tier(c.kickback_reversals, [20, 'kickback_20', 100, 'kickback_100']);
  tier(c.ace_shield_uses, [50, 'ace_shield_50']);
  tier(c.undo_tokens_used_total, [10, 'undo_used_10', 50, 'undo_used_50']);
  tier(c.undo_free_game_count, [20, 'purist_20']);
  tier(c.flawless_game_count, [10, 'flawless_10', 50, 'flawless_50']);
  tier(c.win_streak_best, [5, 'streak_5', 10, 'streak_10', 20, 'streak_20']);

  if (finish_kind && finish_kind in _FINISH_TIERS) {
    tier(profile.multi_card_finishes[finish_kind], _FINISH_TIERS[finish_kind]);
  }

  const hours = profile.total_time_played_secs / 3600;
  tier(hours, [1, 'time_1h', 25, 'time_25h', 100, 'time_100h']);

  if (profile.msomi.games_won_with_msomi >= 10) award('msomi_whisperer');

  return newly;
}

/** Client-side counterpart to
 * core.game_manager.GameManager.finalize_profile_stats() — the ONE
 * caller of checkBadgesAfterGame() above, driven by a server
 * GameSummaryMsg instead of a live GameManager (see that message's
 * own doc comment in @kadi/protocol and network/game_summary.py, its
 * server-side source). Mutates `profile` in place and returns the
 * newly-earned badge ids, for GameTableScene.ts's win-screen
 * notification — same contract as finalize_profile_stats's own
 * return value on the PC side. */
export function applyGameSummary(profile: ProfileData, summary: GameSummaryMsg): string[] {
  const { mode, difficulty, won, finish_kind, opponent_had_msomi } = summary;

  const gp = profile.games_played;
  const gw = profile.games_won;
  if (mode === 'single_player' || mode === 'single_player_elimination') {
    const diffKey: Difficulty = difficulty ?? 'MEDIUM';
    gp[mode][diffKey] += 1;
    if (won) gw[mode][diffKey] += 1;
  } else if (mode === 'internet') {
    // 'lan'/'hot_seat' are never produced by this web client's server
    // (see server/game_room.py's _mode_and_difficulty() — real LAN
    // multiplayer and hot-seat are both out of scope for the web
    // build per §9) — still valid ProfileData buckets (for parity
    // with the PC profile shape/the badges that reference them, e.g.
    // grand_slam), just never incremented from this code path.
    gp.internet += 1;
    if (won) gw.internet += 1;
  }

  if (won && finish_kind) {
    profile.multi_card_finishes[finish_kind] += 1;
  }
  // games_played_with_msomi/games_won_with_msomi read the RAW
  // (not won-gated) opponent_had_msomi — see network/game_summary.py's
  // own comment on why the wire field is raw. The `won` gate only
  // applies to the 'beat_msomi' badge check below, matching
  // finalize_profile_stats's identical split on the PC.
  if (opponent_had_msomi) {
    profile.msomi.games_played_with_msomi += 1;
    if (won) profile.msomi.games_won_with_msomi += 1;
  }
  // total_time_played_secs: deliberately NOT accumulated here — see
  // this file's header note (no session timer exists client-side yet).

  return checkBadgesAfterGame(profile, {
    won,
    mode,
    difficulty,
    finish_kind,
    opponent_had_msomi: won && opponent_had_msomi,
    cards_played: summary.cards_played,
    cards_drawn: summary.cards_drawn,
    biggest_pickup_absorbed: summary.biggest_pickup_absorbed,
    kadi_declarations: summary.kadi_declarations,
    aces_played: summary.aces_played,
    jump_skips_dealt: summary.jump_skips_dealt,
    kickback_reversals: summary.kickback_reversals,
    ace_shield_uses: summary.ace_shield_uses,
    ace_shield_biggest: summary.ace_shield_biggest,
    jump_counter_depth: summary.jump_counter_depth,
    near_kadi_count: summary.near_kadi_count,
    undo_used_this_game: summary.undo_used_this_game,
    bluff_suit_win: won && summary.bluff_suit_win,
    kuficha_trap_win: won && summary.kuficha_trap_win,
    elimination_mode: summary.elimination_mode,
  });
}
