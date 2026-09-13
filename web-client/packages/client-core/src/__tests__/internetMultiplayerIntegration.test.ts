/**
 * KADI - REAL network integration test for the Internet Multiplayer
 * browse/host/join/waiting-room flow (Part B/C of the "real
 * join/browse flow" task; see InternetLobbyScene.ts and this file's
 * sibling gameIntegration.test.ts, whose spawn pattern this copies
 * exactly).
 *
 * Unlike gameIntegration.test.ts (one human + one AI, driven straight
 * through create_game -> request_start_game), this test drives TWO
 * separate KadiConnection instances end to end through the actual
 * lobby a human would use:
 *   1. hostConn creates a named room.
 *   2. joinerConn calls list_games and finds it in the unfiltered
 *      browse list (proves the browse-by-list path).
 *   3. joinerConn applies the same name-search filter
 *      InternetLobbyScene.ts's filteredGames() uses (a local copy --
 *      same cross-package-dependency reasoning gameIntegration.test.ts
 *      already documents for its own local isPlayableForTest copy) to
 *      confirm the game is findable by typing the HOST's name (proves
 *      the search-by-name path independently of the plain list).
 *   4. joinerConn actually joins via join_game.
 *   5. Both sides see a 'lobby_state' with 2 players before start.
 *   6. The host calls request_start_game; both receive 'start_game'.
 *   7. A REAL 2-human game is played to GAME_OVER, each side driven by
 *      its own state_sync stream -- this is the assertion that proves
 *      human-vs-human actually works end to end, not just that the
 *      lobby UI renders.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { spawn, type ChildProcessByStdio } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Readable } from 'node:stream';
import { KadiConnection } from '../connection.js';
import type {
  CardDict,
  GameSummary,
  RuleEngineSnapshot,
  ServerMessage,
  StateSyncMsg,
  SuitName,
} from '@kadi/protocol';

function findPythonRoot(startDir: string): string {
  let dir = startDir;
  for (let i = 0; i < 10; i++) {
    if (existsSync(join(dir, 'server', 'kadi_server.py'))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error('Could not locate the Python project root (server/kadi_server.py) above ' + startDir);
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const PYTHON_ROOT = findPythonRoot(__dirname);

/** Local copy of scenes.InternetLobbyScene._filtered_games()'s exact
 * matching rule (also mirrored in InternetLobbyScene.ts's own
 * filteredGames()) -- duplicated here rather than imported for the
 * same reason gameIntegration.test.ts duplicates its rule-engine
 * helper: this package sits below packages/renderer in the dependency
 * graph, so a client-core test can't import from renderer. This
 * exercises the REAL server-provided GameSummary fields (game_name/
 * host_name), not a hand-built fixture. */
function filterGamesByQuery(games: GameSummary[], query: string): GameSummary[] {
  const q = query.trim().toLowerCase();
  if (!q) return games;
  return games.filter(
    (g) => g.game_name.toLowerCase().includes(q) || g.host_name.toLowerCase().includes(q),
  );
}

// Same minimal single-card playability port gameIntegration.test.ts
// uses, duplicated for the same reason (see that file's own note).
function isPlayableForTest(card: CardDict, rule: RuleEngineSnapshot, pickupPending: boolean): boolean {
  const top = rule.top_card;
  if (!top) return true;
  if (rule.joker_on_top && !pickupPending) return true;
  if (pickupPending) {
    if (card.rank === 'ACE') {
      if (!rule.ace_suit_integrity) return true;
      if (rule.pickup_suit === null) return true;
      return card.suit === rule.pickup_suit;
    }
    if (card.rank === 'JOKER') return true;
    if (!(card.rank === '2' || card.rank === '3')) return false;
    if (top && card.rank === top.rank) return true;
    if (rule.pickup_suit === null) return true;
    return card.suit === rule.pickup_suit;
  }
  if (card.rank === 'JOKER') return true;
  if (card.rank === 'ACE') {
    if (!rule.ace_suit_integrity) return true;
    return card.suit === rule.current_suit || (!!top && card.rank === top.rank);
  }
  if (card.rank === '8' || card.rank === 'Q' || card.rank === 'K' || card.rank === 'J') {
    if (card.suit === rule.current_suit) return true;
    if (top && card.rank === top.rank) return true;
    return false;
  }
  if (card.suit === rule.current_suit) return true;
  if (top && card.rank === top.rank) return true;
  return false;
}

type ServerProcess = ChildProcessByStdio<null, Readable, Readable>;

function waitForOutput(proc: ServerProcess, pattern: RegExp, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => {
      reject(new Error(`Server did not print ${pattern} within ${timeoutMs}ms. Output so far:\n${buf}`));
    }, timeoutMs);
    const onData = (chunk: Buffer) => {
      buf += chunk.toString();
      if (pattern.test(buf)) {
        clearTimeout(timer);
        proc.stdout.off('data', onData);
        resolve();
      }
    };
    proc.stdout.on('data', onData);
    proc.stderr.on('data', (chunk: Buffer) => {
      buf += chunk.toString();
    });
  });
}

function waitForOpen(connection: KadiConnection): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Connection never reached open state')), 5000);
    const unsub = connection.onStateChange((state) => {
      if (state === 'open') {
        clearTimeout(timer);
        unsub();
        resolve();
      }
    });
    connection.connect();
  });
}

/** Waits for the next server message matching `pred`, rejecting if a
 * 'reject' arrives first (unless 'reject' is itself what's being
 * waited for) so a lobby-level failure surfaces immediately instead
 * of hanging until the outer timeout. */
function waitForMessage<T extends ServerMessage>(
  connection: KadiConnection,
  pred: (msg: ServerMessage) => msg is T,
  timeoutMs: number,
  label: string,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      unsub();
      reject(new Error(`Timed out waiting for ${label}`));
    }, timeoutMs);
    const unsub = connection.onMessage((msg) => {
      if (msg.type === 'reject' && label !== 'reject') {
        clearTimeout(timer);
        unsub();
        reject(new Error(`Server rejected while waiting for ${label}: ${msg.reason}`));
        return;
      }
      if (pred(msg)) {
        clearTimeout(timer);
        unsub();
        resolve(msg);
      }
    });
  });
}

describe('Internet Multiplayer browse/host/join/waiting-room flow (two real connections)', () => {
  let proc: ServerProcess | null = null;
  let tmpDir: string | null = null;

  afterEach(() => {
    if (proc) {
      proc.kill('SIGKILL');
      proc = null;
    }
    if (tmpDir) {
      rmSync(tmpDir, { recursive: true, force: true });
      tmpDir = null;
    }
  });

  it(
    'two separate KadiConnections browse, host, join by list AND by name search, both land in a real game, and play it to GAME_OVER',
    async () => {
      // Different port range from gameIntegration.test.ts's own
      // formula (58000s) so the two test files can never collide if a
      // test runner ever parallelizes vitest across files.
      const port = 61000 + Math.floor(Math.random() * 900);
      const wsPort = port + 1000;
      tmpDir = mkdtempSync(join(tmpdir(), 'kadi-internet-lobby-'));
      const leaderboardPath = join(tmpDir, 'leaderboard.json');

      proc = spawn(
        'python3',
        [
          '-m', 'server.kadi_server',
          '--port', String(port),
          '--ws-port', String(wsPort),
          '--leaderboard-path', leaderboardPath,
        ],
        { cwd: PYTHON_ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      await waitForOutput(proc, /listening on port/i, 10_000);

      const wsUrl = `ws://127.0.0.1:${wsPort}/`;
      const hostConn = new KadiConnection(wsUrl);
      const joinerConn = new KadiConnection(wsUrl);

      await Promise.all([waitForOpen(hostConn), waitForOpen(joinerConn)]);

      const HOST_NAME = 'IntegrationHost';
      const JOINER_NAME = 'IntegrationJoiner';
      const ROOM_NAME = 'Kadi Test Room Alpha';

      hostConn.send({ type: 'hello', name: HOST_NAME });
      joinerConn.send({ type: 'hello', name: JOINER_NAME });

      // ── host a named room ──
      hostConn.send({ type: 'create_game', settings: { game_name: ROOM_NAME } });
      const hostWelcome = await waitForMessage(
        hostConn,
        (m): m is Extract<ServerMessage, { type: 'welcome' }> => m.type === 'welcome',
        5000,
        'welcome (host)',
      );
      expect(hostWelcome.reconnect_token).not.toBeNull();
      const gameId = hostWelcome.game_id;
      const hostId = hostWelcome.host_id;
      expect(hostWelcome.player_id).toBe(hostId); // creator is always the host

      // ── browse-by-list: the joiner sees it in the unfiltered list ──
      joinerConn.send({ type: 'list_games' });
      const browseList = await waitForMessage(
        joinerConn,
        (m): m is Extract<ServerMessage, { type: 'games_list' }> => m.type === 'games_list',
        5000,
        'games_list (browse)',
      );
      const foundByBrowse = browseList.games.find((g) => g.game_id === gameId);
      expect(foundByBrowse).toBeDefined();
      expect(foundByBrowse?.game_name).toBe(ROOM_NAME);
      expect(foundByBrowse?.host_name).toBe(HOST_NAME);
      expect(foundByBrowse?.player_count).toBe(1);
      expect(foundByBrowse?.max_players).toBeGreaterThanOrEqual(2);
      expect(Array.isArray(foundByBrowse?.rows)).toBe(true);

      // ── join-by-name-search: same list, filtered by the HOST's name
      // (not the room's own name) -- proves "your friend tells you
      // who's hosting" works, not just an exact room-name match ──
      joinerConn.send({ type: 'list_games' });
      const searchList = await waitForMessage(
        joinerConn,
        (m): m is Extract<ServerMessage, { type: 'games_list' }> => m.type === 'games_list',
        5000,
        'games_list (search)',
      );
      const searchResults = filterGamesByQuery(searchList.games, HOST_NAME.slice(0, 6).toLowerCase());
      expect(searchResults.some((g) => g.game_id === gameId)).toBe(true);
      // A query that matches neither name should filter it out --
      // proves the filter is actually discriminating, not a no-op.
      const nonMatch = filterGamesByQuery(searchList.games, 'zzz-no-such-room-zzz');
      expect(nonMatch.some((g) => g.game_id === gameId)).toBe(false);

      // ── actually join, via the id either path resolved to ──
      joinerConn.send({ type: 'join_game', game_id: gameId });
      const joinerWelcome = await waitForMessage(
        joinerConn,
        (m): m is Extract<ServerMessage, { type: 'welcome' }> => m.type === 'welcome',
        5000,
        'welcome (joiner)',
      );
      expect(joinerWelcome.game_id).toBe(gameId);
      expect(joinerWelcome.host_id).toBe(hostId);
      expect(joinerWelcome.player_id).not.toBe(hostId);

      // ── waiting room: both sides see the 2-player roster before start ──
      const hostLobbyState = await waitForMessage(
        hostConn,
        (m): m is Extract<ServerMessage, { type: 'lobby_state' }> =>
          m.type === 'lobby_state' && m.players.length === 2,
        5000,
        'lobby_state with 2 players (host)',
      );
      expect(hostLobbyState.host_id).toBe(hostId);
      expect(hostLobbyState.game_name).toBe(ROOM_NAME);
      expect(new Set(hostLobbyState.players.map((p) => p.name))).toEqual(
        new Set([HOST_NAME, JOINER_NAME]),
      );

      // ── host starts the game; BOTH connections must see start_game ──
      const startPromises = Promise.all([
        waitForMessage(
          hostConn,
          (m): m is Extract<ServerMessage, { type: 'start_game' }> => m.type === 'start_game',
          5000,
          'start_game (host)',
        ),
        waitForMessage(
          joinerConn,
          (m): m is Extract<ServerMessage, { type: 'start_game' }> => m.type === 'start_game',
          5000,
          'start_game (joiner)',
        ),
      ]);
      hostConn.send({ type: 'request_start_game' });
      await startPromises;

      // ── real human-vs-human game to GAME_OVER, each side driven by
      // its own state_sync stream ──
      function driveToGameOver(connection: KadiConnection, myId: number): Promise<StateSyncMsg> {
        return new Promise((resolve, reject) => {
          let messageCount = 0;
          let finalSync: StateSyncMsg | null = null;
          const seenStates = new Set<string>();
          const hardTimeout = setTimeout(() => {
            unsubscribe();
            reject(
              new Error(
                `Player ${myId}: game did not reach GAME_OVER in time. States seen: ` +
                  `${[...seenStates].join(', ')}. Last sync: ` +
                  `${finalSync ? JSON.stringify(finalSync).slice(0, 500) : 'none'}`,
              ),
            );
          }, 260_000);

          const unsubscribe = connection.onMessage((msg: ServerMessage) => {
            if (msg.type !== 'state_sync') return;
            messageCount += 1;
            if (messageCount > 8000) {
              clearTimeout(hardTimeout);
              unsubscribe();
              reject(new Error(`Player ${myId}: exceeded 8000 state_sync messages without GAME_OVER`));
              return;
            }

            finalSync = msg;
            seenStates.add(msg.state);

            // Same privacy boundary check as gameIntegration.test.ts,
            // now against a REAL human opponent's connection rather
            // than an AI seat.
            for (const p of msg.players) {
              if (p.player_id !== msg.you && p.hand !== null) {
                clearTimeout(hardTimeout);
                unsubscribe();
                reject(new Error(`Player ${myId}: opponent hand leaked over the wire`));
                return;
              }
            }

            if (msg.state === 'GAME_OVER') {
              clearTimeout(hardTimeout);
              unsubscribe();
              resolve(msg);
              return;
            }

            const me = msg.players.find((p) => p.player_id === msg.you);
            const myHand = me?.hand ?? [];
            const pickupPending = msg.rule_engine.pickup_pending > 0;

            if (msg.state === 'SUIT_PICK' && msg.current_player_idx === msg.you) {
              // Pick whichever suit this hand holds the most of, rather
              // than a fixed suit -- an early version of this test
              // always chose SPADES regardless of hand contents, which
              // (combined with random shuffles) occasionally produced
              // very long games where neither bot could easily play
              // into its own suit lock. Biasing the choice toward the
              // bot's own hand shortens games without needing real
              // strategic play.
              const suitCounts: Record<string, number> = {};
              for (const c of myHand) {
                if (c.suit) suitCounts[c.suit] = (suitCounts[c.suit] ?? 0) + 1;
              }
              const bestSuit = (Object.entries(suitCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ??
                'SPADES') as CardDict['suit'] & string;
              connection.send({ type: 'intent_choose_suit', suit: bestSuit as never });
            } else if (msg.state === 'JUMP_COUNTER_WINDOW' && msg.counter_player_idx === msg.you) {
              const jump = myHand.find((c) => c.rank === 'J');
              if (jump) connection.send({ type: 'intent_counter', cards: [jump] });
              else connection.send({ type: 'intent_pass_counter' });
            } else if (msg.state === 'POST_PLAY' && msg.post_play?.player_id === msg.you) {
              // Declaring KADI here is not cosmetic -- it's how a
              // player actually WINS. Reaching an empty hand without
              // this (i.e. always sending plain 'proceed') just lets
              // the empty-handed player draw again next turn instead
              // of finishing, which is exactly what made an early
              // version of this test's bot loop for minutes without
              // ever reaching GAME_OVER.
              if (msg.post_play.can_kadi) {
                connection.send({ type: 'intent_post_play_declare_kadi' });
              } else {
                connection.send({ type: 'intent_post_play_proceed' });
              }
            } else if (msg.state === 'PLAYING' || msg.state === 'KADI_DECLARED') {
              if (msg.current_player_idx === msg.you) {
                const playable = myHand.filter((c) =>
                  isPlayableForTest(c, msg.rule_engine, pickupPending),
                );
                // Two independent naive bots choosing purely by hand
                // order can perpetually trade pickup-chain cards (2s/
                // 3s) back and forth without either hand ever shrinking
                // to zero -- an early version of this test observed
                // multi-minute, non-converging games this way. Playing
                // plain cards first, and reaching for a 2/3 only when
                // it's the sole legal move, makes convergence reliable
                // without needing real strategic play.
                const escalationWeight = (c: CardDict): number => (c.rank === '2' || c.rank === '3' ? 1 : 0);
                playable.sort((a, b) => escalationWeight(a) - escalationWeight(b));
                const firstPlayable = playable[0];
                if (firstPlayable) {
                  connection.send({ type: 'intent_play', cards: [firstPlayable] });
                } else {
                  connection.send({ type: 'intent_draw' });
                }
              }
            }
          });
        });
      }

      const [hostFinal, joinerFinal] = await Promise.all([
        driveToGameOver(hostConn, hostWelcome.player_id),
        driveToGameOver(joinerConn, joinerWelcome.player_id),
      ]);

      expect(hostFinal.state).toBe('GAME_OVER');
      expect(joinerFinal.state).toBe('GAME_OVER');
      expect(hostFinal.players).toHaveLength(2);
      expect(hostFinal.winner_id).not.toBeNull();
      expect(hostFinal.winner_id).toBe(joinerFinal.winner_id); // both sides agree on the outcome
      expect(hostFinal.undo_available).toBe(false);

      hostConn.close();
      joinerConn.close();
    },
    280_000,
  );
});
