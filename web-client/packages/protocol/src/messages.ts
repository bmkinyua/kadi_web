/**
 * KADI - hand-kept TypeScript mirror of the server's JSON message
 * shapes. NOT auto-generated -- Python and TS can't literally share
 * one source file, so this is kept in sync by hand against
 * server/kadi_server.py's _handle_message() (the source of truth for
 * what the server accepts) and every `self.conns.send_to(...)` /
 * `self.conns.broadcast(...)` call in that same file (the source of
 * truth for what it sends). See KADI_web_port_implementation_plan.md
 * §8 for the CI drift-check this file is meant to be paired with --
 * not implemented yet, so for now: if you add/change a message type
 * on the Python side, update this file in the SAME change, not later.
 *
 * SCOPE OF THIS FIRST PASS: only the lobby-level messages a client
 * needs before/outside an active game (connect, ask "what's my rank",
 * browse/create/join games) are modeled below. The full in-game
 * message set (game actions, state_sync snapshots, chat, reconnect)
 * is real and exists server-side today, but modeling it accurately
 * needs the renderer's game-table scene to exist first to know what
 * shape is actually useful client-side -- deliberately NOT guessed at
 * here. Extend this file when that scene gets built, not before.
 */

// ── client -> server ────────────────────────────────────────────────────

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

export interface CreateGameMsg {
  type: 'create_game';
  settings?: Record<string, unknown>;
}

export interface JoinGameMsg {
  type: 'join_game';
  game_id: string;
}

export type ClientMessage =
  | HelloMsg
  | ListGamesMsg
  | GetLeaderboardMsg
  | GetMyRankMsg
  | CreateGameMsg
  | JoinGameMsg;

// ── server -> client ─────────────────────────────────────────────────────

export interface GameSummary {
  game_id: string;
  name: string;
  // Deliberately loose beyond this -- open_games_summary()'s exact
  // extra fields aren't consumed by this first pass (no lobby-browse
  // UI yet), see file-level note above.
  [key: string]: unknown;
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

export interface WelcomeMsg {
  type: 'welcome';
  player_id: number;
  // Extended by GameRoom's own snapshot fields -- not modeled yet,
  // see file-level note above.
  [key: string]: unknown;
}

export interface RejectMsg {
  type: 'reject';
  reason: string;
}

export type ServerMessage =
  | GamesListMsg
  | LeaderboardResultMsg
  | MyRankResultMsg
  | WelcomeMsg
  | RejectMsg;
