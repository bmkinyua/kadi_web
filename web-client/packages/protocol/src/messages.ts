/**
 * KADI - hand-kept TypeScript mirror of the server's JSON message
 * shapes. NOT auto-generated -- Python and TS can't literally share
 * one source file, so this is kept in sync by hand against
 * server/kadi_server.py's _handle_message() (the source of truth for
 * what the server accepts), server/game_room.py's handle_intent()
 * (the source of truth for in-game intents), network/state_sync.py's
 * build_snapshot_for() (the exact state_sync shape), and every
 * `self.conns.send_to(...)` / `self.conns.broadcast(...)` call in
 * kadi_server.py/game_room.py (the source of truth for what the
 * server sends). See KADI_web_port_implementation_plan.md §8 for the
 * CI drift-check this file is meant to be paired with -- not
 * implemented yet, so for now: if you add/change a message type on
 * the Python side, update this file in the SAME change, not later.
 *
 * SCOPE: this now covers both lobby-level messages AND the full
 * in-game message set (game actions, state_sync snapshots, chat,
 * reconnect) -- the game-table scene that needed these shapes now
 * exists (see packages/renderer/src/GameTableScene.ts), closing the
 * gap this file's previous version deliberately left open.
 *
 * GameSummary is now the REAL open_games_summary() shape (see that
 * interface's own docstring below) -- InternetLobbyScene.ts's browse
 * list needs the actual fields (host_name, player_count, max_players,
 * rows), not the placeholder `name: string` this file previously
 * guessed at before a real browse UI existed to consume it.
 *
 * NOT MODELED (deliberately, matching server/README.md's own scope
 * cuts, not an oversight here):
 * - Undo. server/game_room.py's handle_intent() comment: "Undo is
 *   deliberately NOT exposed over the network" -- there is no
 *   intent_undo message and never has been.
 * - Multi-card *sequence* validation (question chains, K/J bundles,
 *   pickup-mix rules -- see core/rule_engine.py's
 *   is_valid_sequence/_validate_question_chain/etc). The wire shape
 *   for a multi-card play (IntentPlayMsg.cards: CardDict[]) already
 *   supports sending more than one card -- the server is the sole
 *   validator of whether a given combo is legal, exactly as it is for
 *   every other client. What this file does NOT attempt is mirroring
 *   that validation logic client-side for anything beyond the
 *   single-card case (see GameTableLayout.ts / GameTableScene.ts's
 *   own notes on the resulting UI scope cut).
 */

// ── shared value shapes ─────────────────────────────────────────────────

/** Mirrors constants.Suit's four members exactly (constants.py). */
export type SuitName = 'SPADES' | 'LOVE' | 'DICE' | 'FLOWERS';

/** Mirrors constants.RANKS exactly -- note 'ACE', not 'A' (that's only
 * the *display* string, RANK_DISPLAY['ACE'] == 'A') -- and 'JOKER',
 * which isn't in RANKS but is a valid Card.rank (models/card.py). */
export type RankName =
  | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '10'
  | 'J' | 'Q' | 'K' | 'ACE' | 'JOKER';

/** Mirrors network/codec.py's card_to_dict/card_from_dict exactly. */
export interface CardDict {
  suit: SuitName | null; // null only for a Joker
  rank: RankName;
  is_red_joker: boolean;
}

// ── client -> server: lobby ─────────────────────────────────────────────

export interface HelloMsg {
  type: 'hello';
  name: string;
  /** Web clients only -- see server/kadi_server.py's 'hello' handling
   * and server/leaderboard_store.py's identity-key docstring. Omit
   * both fields entirely (not just set to undefined) for a client
   * that has no platform identity to offer -- the server keys purely
   * by name in that case, same as the desktop client always has. */
  platform?: string;
  external_id?: string;
}

export interface ListGamesMsg {
  type: 'list_games';
}

export interface GetLeaderboardMsg {
  type: 'get_leaderboard';
  n?: number;
}

export interface GetMyRankMsg {
  type: 'get_my_rank';
}

/** settings is intentionally loose beyond the fields the web client
 * itself populates (server/game_room.py's __init__ reads many more --
 * game_name, rules, ai_msomi_model, ... -- but this first game-table
 * pass only ever needs to set ai_count/ai_difficulty for a "quick
 * match vs AI", see GameTableScene.ts's lobby-transition wiring). Any
 * of server/game_room.py's other recognized keys can still be passed
 * through the index signature; they just aren't individually typed
 * here yet since nothing in this client sets them. */
export interface CreateGameSettings {
  game_name?: string;
  ai_count?: number;
  ai_difficulty?: 'EASY' | 'MEDIUM' | 'HARD';
  elimination_mode?: boolean;
  /** Only meaningful when elimination_mode is true -- mirrors
   * scenes.ModeSelectScene's "AI-only continue" sub-toggle
   * (GameManager.new_game()'s own elimination_ai_only_continue
   * param, which server/game_room.py's start_game() previously
   * hardcoded to True rather than reading from here -- see that
   * file's own note on the fix). Server default (unset) is True,
   * matching the PC's own default and this field's prior hardcoded
   * behavior, so omitting it is backward compatible. */
  elimination_ai_only_continue?: boolean;
  /** Embedded MSOMI model dict (core/msomi_trainer.save_model's
   * format) -- see server/game_room.py's __init__ for why this is
   * embedded rather than a filename (the trained model lives on the
   * PLAYER's own device, not the server). Validated server-side;
   * silently ignored (falls back to plain AI) if invalid. */
  ai_msomi_model?: Record<string, unknown>;
  /** Display label for ai_msomi_model, shown in settings_summary_rows()
   * -- purely cosmetic, has no effect on gameplay. */
  ai_msomi_model_label?: string;
  [key: string]: unknown;
}

export interface CreateGameMsg {
  type: 'create_game';
  settings?: CreateGameSettings;
}

export interface JoinGameMsg {
  type: 'join_game';
  game_id: string;
}

/** A fresh connection presenting a token from an earlier
 * welcome/rejoined message, trying to resume a match that's already
 * running (server/game_room.py's reconnect()). */
export interface RejoinGameMsg {
  type: 'rejoin_game';
  game_id: string;
  token: string;
}

export interface RequestStartGameMsg {
  type: 'request_start_game';
}

/** Works both pre-start (lobby banter) and mid-game -- see
 * server/kadi_server.py's 'chat' handling. */
export interface ChatMsg {
  type: 'chat';
  text: string;
}

// ── client -> server: in-game intents ───────────────────────────────────
// Mirrors server/game_room.py's handle_intent() exactly -- each intent
// below is only acted on when it's actually this connection's decision
// to make (turn/counter/post-play ownership is re-checked server-side
// regardless of what the client sends).

export interface IntentPlayMsg {
  type: 'intent_play';
  cards: CardDict[];
  declare_kadi?: boolean;
  /** Only meaningful when the play includes an ACE (suit-change) --
   * see core/game_manager.py's human_play(). */
  declared_suit?: SuitName;
}

export interface IntentDrawMsg {
  type: 'intent_draw';
}

export interface IntentDeclareKadiMsg {
  type: 'intent_declare_kadi';
}

/** Only valid while state === 'SUIT_PICK' -- following an ACE play
 * that requires the actor to name the new current suit. */
export interface IntentChooseSuitMsg {
  type: 'intent_choose_suit';
  suit: SuitName;
}

/** Only valid while state === 'JUMP_COUNTER_WINDOW', and only for
 * whichever seat counter_player_idx currently names. */
export interface IntentCounterMsg {
  type: 'intent_counter';
  cards: CardDict[];
}

export interface IntentPassCounterMsg {
  type: 'intent_pass_counter';
}

/** Only valid while state === 'POST_PLAY', and only for
 * post_play.player_id. */
export interface IntentPostPlayDeclareKadiMsg {
  type: 'intent_post_play_declare_kadi';
}

export interface IntentPostPlayProceedMsg {
  type: 'intent_post_play_proceed';
}

/** Any seated player, not just the host -- see server/game_room.py's
 * comment on why this has no host-only gate the way other intents
 * don't need either (every client is equally a thin client here). */
export interface IntentTogglePauseMsg {
  type: 'intent_toggle_pause';
}

export type ClientMessage =
  | HelloMsg
  | ListGamesMsg
  | GetLeaderboardMsg
  | GetMyRankMsg
  | CreateGameMsg
  | JoinGameMsg
  | RejoinGameMsg
  | RequestStartGameMsg
  | ChatMsg
  | IntentPlayMsg
  | IntentDrawMsg
  | IntentDeclareKadiMsg
  | IntentChooseSuitMsg
  | IntentCounterMsg
  | IntentPassCounterMsg
  | IntentPostPlayDeclareKadiMsg
  | IntentPostPlayProceedMsg
  | IntentTogglePauseMsg;

// ── server -> client: lobby ──────────────────────────────────────────────

/** Mirrors server/lobby.py's Lobby.open_games_summary() EXACTLY, field
 * for field -- this was previously guessed (a bare `name: string`
 * that doesn't exist on the wire at all) before InternetLobbyScene.ts
 * needed the real shape. `game_name` is the empty string, NOT the
 * "<host>'s game" display fallback, when the host left it blank --
 * the server deliberately leaves that fallback to the client (see
 * lobby.py's own comment), same as the PC client's
 * scenes.InternetLobbyScene.draw() does with
 * `g.get('game_name') or f"{host}'s game"`. */
export interface GameSummary {
  game_id: string;
  host_name: string;
  game_name: string;
  player_count: number;
  max_players: number;
  /** Short settings-summary rows (elimination mode, AI fill, ...) --
   * see server/game_room.py's settings_summary_rows(). Each row is a
   * [label, value] pair, already display-ready strings. */
  rows: [string, string][];
}

export interface GamesListMsg {
  type: 'games_list';
  games: GameSummary[];
}

export interface LeaderboardEntry {
  name: string;
  wins: number;
}

export interface LeaderboardResultMsg {
  type: 'leaderboard_result';
  entries: LeaderboardEntry[];
}

export interface MyRankResultMsg {
  type: 'my_rank_result';
  rank: number | null;
  wins: number;
}

/** Sent on both create_game and join_game -- server/kadi_server.py
 * builds this identically in both branches. */
export interface WelcomeMsg {
  type: 'welcome';
  player_id: number;
  game_id: string;
  host_id: number;
  /** null is never actually sent for 'welcome' (every seated
   * connection gets one, see server/game_room.py's _assign_token) --
   * typed nullable only because RejoinedMsg reuses this same shape
   * and JSON has no "always a string" guarantee worth asserting past
   * TS's own type. */
  reconnect_token: string | null;
  server_version: string;
}

/** Sent in reply to a successful 'rejoin_game'. */
export interface RejoinedMsg {
  type: 'rejoined';
  player_id: number;
  game_id: string;
  host_id: number;
  reconnect_token: string | null;
}

export interface RejectMsg {
  type: 'reject';
  reason: string;
}

/** Broadcast to every member of a room whenever its roster/settings
 * change (join/leave/create) -- see server/kadi_server.py's
 * _broadcast_lobby_state(). Only meaningful before start_game. */
export interface LobbyStateMsg {
  type: 'lobby_state';
  players: { player_id: number; name: string }[];
  host_id: number;
  game_name: string;
  settings: { rows: [string, string][] };
}

/** Host left (or the room emptied out) before the game started --
 * see server/kadi_server.py's _remove_from_room(). */
export interface RoomClosedMsg {
  type: 'room_closed';
  reason: string;
}

/** Sent to every room member the instant request_start_game
 * succeeds -- this is the signal to transition from the lobby scene
 * into GameTableScene (the first real state_sync for this game
 * follows on the very next server tick, see kadi_server.py's tick()). */
export interface StartGameMsg {
  type: 'start_game';
}

/** Relayed chat -- server/kadi_server.py never echoes a message back
 * to its own sender (see that handler's comment); the sender is
 * expected to render its own message locally when it sends one. */
export interface ChatBroadcastMsg {
  type: 'chat';
  from: string;
  text: string;
}

// ── server -> client: in-game state ─────────────────────────────────────
// Mirrors network/state_sync.py's build_snapshot_for() field-for-field.

export interface PlayerSnapshot {
  player_id: number;
  name: string;
  is_human: boolean;
  difficulty: 'EASY' | 'MEDIUM' | 'HARD' | null;
  score: number;
  has_declared_kadi: boolean;
  finished: boolean;
  finish_place: number | null;
  hand_count: number;
  /** Only populated for the recipient's OWN entry (player_id === the
   * state_sync's `you`) -- every other seat gets null here, mirroring
   * the exact privacy boundary GameManager._opponent_context already
   * enforces for AI decision-making (hand counts, never contents, for
   * anyone who isn't the recipient). Never trust a `hand` on any
   * other player's entry even if one were somehow present. */
  hand: CardDict[] | null;
}

export interface PostPlaySnapshot {
  player_id: number | null;
  can_kadi: boolean;
  timer: number;
}

export interface RuleEngineSnapshot {
  current_suit: SuitName | null;
  pickup_pending: number;
  pickup_rank: RankName | null;
  pickup_suit: SuitName | null;
  top_card: CardDict | null;
  skip_count: number;
  joker_on_top: boolean;
  ace_suit_integrity: boolean;
  pickup_shield_qk_allowed: boolean;
  ace_finisher_enabled: boolean;
  jump_multi_card_enabled: boolean;
}

export interface DeckSnapshot {
  draw_count: number;
  discard_count: number;
}

/** GameEvent's generic dict shape (network/event_codec.py's
 * encode_event) -- a Player reference becomes {__player_id__}, a Card
 * reference becomes {__card__}, everything else (str/int/float/bool/
 * enum-.name/list) passes through more or less as-is. `kind` is one
 * of core/game_manager.py's ~25 GameEvent kinds (e.g. 'card_played',
 * 'pickup_forced', 'kadi_declared', 'player_finished', 'game_over',
 * ...) -- deliberately NOT enumerated here as a closed union, mirroring
 * event_codec.py's own "walk whatever attributes exist" genericness so
 * a new event kind added server-side doesn't need a client-side type
 * change to arrive intact; GameTableScene.ts's toast/sound handling
 * switches on `kind` and only needs to recognize the ones it actually
 * reacts to. */
export type EncodedEventValue =
  | string
  | number
  | boolean
  | null
  | { __player_id__: number }
  | { __card__: CardDict | null }
  | EncodedEventValue[];

export interface EncodedGameEvent {
  kind: string;
  fields: Record<string, EncodedEventValue>;
}

/** The one big periodic push -- see network/state_sync.py's
 * build_snapshot_for() docstring: safe to read at any point during
 * PLAYING/POST_PLAY/SUIT_PICK/JUMP_COUNTER_WINDOW/GAME_OVER, every
 * field either has a sensible default or is null when not applicable
 * to the current state. */
export interface StateSyncMsg {
  type: 'state_sync';
  /** This recipient's OWN seat index (== their entry's player_id in
   * `players` below) -- NOT this connection's conn_id. See
   * server/game_room.py's snapshot_for(), which passes the seat, not
   * the raw conn_id, as build_snapshot_for's recipient_id. */
  you: number;
  state:
    | 'PLAYING'
    | 'SUIT_PICK'
    | 'KADI_DECLARED'
    | 'KADI_WINDOW'
    | 'POST_PLAY'
    | 'JUMP_COUNTER_WINDOW'
    | 'PAUSED'
    | 'GAME_OVER';
  current_player_idx: number;
  direction: 'CLOCKWISE' | 'COUNTER_CLOCKWISE';
  elimination_mode: boolean;
  elimination_ai_only_continue: boolean;
  winner_id: number | null;
  finish_order_ids: number[];
  declared_kadi_player_id: number | null;
  skipped_player_id: number | null;
  last_effect_text: string | null;
  last_played_cards: CardDict[];
  pickup_pending_display: number;
  players: PlayerSnapshot[];
  rule_engine: RuleEngineSnapshot;
  deck: DeckSnapshot;
  counter_player_idx: number;
  jump_player_id: number | null;
  jump_skip_remaining: number;
  counter_timer: number;
  counter_window_secs: number;
  post_play: PostPlaySnapshot | null;
  turn_timer: number;
  turn_timer_secs: number;
  timers_enabled: boolean;
  post_play_delay_secs: number;
  hints_enabled: boolean;
  hint_threshold_pct: number;
  /** Always false over the network -- see server/game_room.py: undo
   * is host-local only and never exposed as a network intent. */
  undo_available: boolean;
  events: EncodedGameEvent[];
}

/** Sent ONCE, to every seated human, from the exact server-side
 * transition GameManager.state first becomes GAME_OVER -- see
 * server/kadi_server.py's tick() and network/game_summary.py's
 * build_game_summary_for() (the source of truth for this shape,
 * mirrored here field-for-field). Closes the gap this file's own
 * StateSyncMsg never covered: state_sync carries `winner_id` but
 * none of the per-game tallies core/profile_store.py's
 * check_badges_after_game() needs (cards played, aces, KADI
 * declarations, ...) -- see checkBadgesAfterGame() in profileData.ts,
 * the client-side port of that same function, which this message is
 * the wire input to.
 *
 * PERSONALIZED, not a broadcast: each recipient's own `you`/`won`/
 * tally fields describe THEIR OWN game only. See
 * network/game_summary.py's module docstring for why -- the
 * server-side GameManager tallies (self._g_*) are aggregated across
 * every human seated in the room (correct for the PC's one-human-
 * per-device assumption, wrong for a real multi-human internet
 * match), so the server splits them per-player_id before sending;
 * never assume two recipients' summaries for the same game share any
 * tally field.
 *
 * `mode`/`difficulty` are the server's own interpretation (see
 * server/game_room.py's _mode_and_difficulty()): a room that only
 * ever had one human (the rest AI seats -- this client's own "Play
 * vs AI" quick match) is reported as 'single_player'/
 * 'single_player_elimination' with that room's configured AI
 * difficulty; two or more humans is 'internet', difficulty null. */
export interface GameSummaryMsg {
  type: 'game_summary';
  /** This recipient's own seat index -- same meaning as
   * StateSyncMsg.you, NOT this connection's conn_id. */
  you: number;
  won: boolean;
  mode: 'single_player' | 'single_player_elimination' | 'internet';
  difficulty: 'EASY' | 'MEDIUM' | 'HARD' | null;
  finish_kind: 'question_chain' | 'kickback_run' | 'jump_bundle' | 'ace_finisher' | null;
  opponent_had_msomi: boolean;
  elimination_mode: boolean;
  cards_played: number;
  cards_drawn: number;
  biggest_pickup_absorbed: number;
  kadi_declarations: number;
  aces_played: number;
  jump_skips_dealt: number;
  kickback_reversals: number;
  ace_shield_uses: number;
  ace_shield_biggest: number;
  /** Game-level, not per-player -- see network/game_summary.py's
   * docstring: a Jump-counter chain is extended by whichever players
   * choose to counter it, not owned by any one of them, so this is
   * the same value for every recipient of the same finished game. */
  jump_counter_depth: number;
  near_kadi_count: number;
  /** Always false over the network -- see server/game_room.py:
   * undo is host-local only and never exposed as a network intent.
   * Carried for schema parity with core/profile_store.py's
   * check_badges_after_game() inputs, not hardcoded out client-side,
   * in case that ever changes. */
  undo_used_this_game: boolean;
  bluff_suit_win: boolean;
  kuficha_trap_win: boolean;
}

export type ServerMessage =
  | GamesListMsg
  | LeaderboardResultMsg
  | MyRankResultMsg
  | WelcomeMsg
  | RejoinedMsg
  | RejectMsg
  | LobbyStateMsg
  | RoomClosedMsg
  | StartGameMsg
  | ChatBroadcastMsg
  | StateSyncMsg
  | GameSummaryMsg;
