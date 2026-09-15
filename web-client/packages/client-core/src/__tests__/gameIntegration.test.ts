/**
 * KADI - REAL network integration test.
 *
 * Spawns the actual `python3 -m server.kadi_server` process (the same
 * one a real deployment runs -- core/game_manager.GameManager
 * completely unmodified underneath it) and drives a full game to
 * completion through `KadiConnection`, exactly as GameTableScene
 * does, over a real WebSocket, real RFC 6455 handshake
 * (network/ws_protocol.py), real JSON wire frames. This is NOT a
 * mock server / fake transport test -- if the protocol types in
 * packages/protocol/src/messages.ts drift from what the Python side
 * actually sends, THIS is the test that catches it, not the unit
 * tests (which only check this package's own pure functions against
 * hand-built fixtures).
 *
 * Scope: one human connection + one AI opponent (Quick Play's own
 * shape, see LobbyScene.ts's Part E wiring) -- the simplest
 * configuration that exercises every state_sync state a real game
 * passes through (PLAYING, SUIT_PICK, JUMP_COUNTER_WINDOW, POST_PLAY,
 * GAME_OVER at minimum; PAUSED is intentionally not exercised here --
 * nothing about pause changes wire compatibility of the states above,
 * and toggling it mid-game would just make an already-long game
 * longer for no additional signal). The human side plays via the
 * SAME single-card playability rule cardPlayability.ts uses (a small
 * local copy, not an import -- see that file's own note on why
 * client-core doesn't depend on the renderer package: the dependency
 * would run backwards, renderer depends on client-core, not the
 * other way).
 */
import { afterEach, describe, expect, it } from 'vitest';
import { spawn, type ChildProcessByStdio } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Readable } from 'node:stream';
import { KadiConnection } from '../connection.js';
import type {
  CardDict,
  RuleEngineSnapshot,
  ServerMessage,
  StateSyncMsg,
} from '@kadi/protocol';

// ── locate the Python project root from this test file's own path,
// rather than assuming a fixed relative depth -- robust to this
// package being run from a different cwd (npm workspaces sometimes
// invoke scripts from the repo root, sometimes from the package dir).
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

// ── minimal local copy of core/rule_engine.py's single-card
// is_playable()/_can_counter_pickup() -- same logic
// packages/renderer/src/cardPlayability.ts ports for the UI hint, but
// duplicated (not imported) here on purpose: client-core sits BELOW
// renderer in the dependency graph (renderer depends on client-core,
// see that package's package.json), so this test can't import from
// renderer without an inverted/circular dependency. This copy exists
// solely to let the test's fake "human" pick a legal move each turn
// -- it is not shipped, not exported, and not the production hint.
//
// NOTE, single-card pickup counter branch: this intentionally does
// NOT treat a Question card (8/Q) as pickup-resolving on its own.
// core/rule_engine.py's own _can_counter_pickup() says a Question
// card CAN lead a counter, but core/game_manager.py's _do_play()
// separately rejects one played ALONE ("cannot be played alone" --
// the sequence must end in an actual resolving card). This test only
// ever submits single-card plays, so treating Question cards as
// pickup-resolving here made the fake human repeatedly submit a
// doomed lone-8/Q play every tick while a real pickup sat unresolved
// -- the actual, previously-undiagnosed reason this test could hang
// past its message cap without the game being genuinely stuck. See
// packages/renderer/src/cardPlayability.ts's canCounterPickup() for
// the fuller explanation (same fix, same root cause, found via this
// exact test).
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

// stdio: ['ignore', 'pipe', 'pipe'] means stdin is discarded (null),
// so this is a ChildProcessByStdio<null, Readable, Readable>, not the
// looser ChildProcessWithoutNullStreams (which requires a writable
// stdin) -- the two are easy to conflate since both come from
// node:child_process's spawn() overloads, but only the former
// actually matches this spawn() call's own stdio config.
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

describe('KadiConnection against a real Python server (network integration)', () => {
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
    'creates a Quick-Play-vs-AI game, plays it to GAME_OVER, and never leaks an opponent hand over the wire',
    async () => {
      const port = 58000 + (Math.floor(Date.now() / 7) % 900);
      const wsPort = port + 1000;
      tmpDir = mkdtempSync(join(tmpdir(), 'kadi-leaderboard-'));
      const leaderboardPath = join(tmpDir, 'leaderboard.json');

      proc = spawn(
        'python3',
        ['-m', 'server.kadi_server', '--port', String(port), '--ws-port', String(wsPort), '--leaderboard-path', leaderboardPath],
        { cwd: PYTHON_ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      await waitForOutput(proc, /listening on port/i, 10_000);

      const connection = new KadiConnection(`ws://127.0.0.1:${wsPort}/`);

      await new Promise<void>((resolve, reject) => {
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

      let sawOpponentHandLeak = false;
      let sawOpponentHandCountPresent = false;
      let finalSync: StateSyncMsg | null = null;
      let seenStates = new Set<string>();
      let messageCount = 0;

      connection.send({ type: 'hello', name: 'IntegrationTestPlayer' });
      // MEDIUM here (not HARD): HARD's stronger defensive/pickup-chain
      // play measurably prolongs a 2-player game against this test's
      // deliberately simple heuristic opponent (observed empirically
      // while writing this test); MEDIUM keeps AI think-time short
      // (0.5-1.0s/turn, see models/player.py's _get_think_time) while
      // converging to GAME_OVER in a bounded number of real-world
      // turns far more reliably. Unrelated to Quick Play's own MEDIUM
      // default in LobbyScene.ts, which is a separate UX choice.
      connection.send({ type: 'create_game', settings: { ai_count: 1, ai_difficulty: 'MEDIUM' } });

      const gameOverPromise = new Promise<StateSyncMsg>((resolve, reject) => {
        // 320s / 8000-message ceiling, not the original 260s/5000 --
        // widened after this test genuinely timed out on a real run
        // and re-running the identical bot logic manually 7x in a row
        // afterward (2.3s-144s observed, mean ~60s) never reproduced
        // a stall -- every one of those 7 runs reached GAME_OVER
        // cleanly with the message-count-vs-wall-clock ratio exactly
        // matching the server's fixed 20Hz broadcast tick (see
        // server/kadi_server.py's TICK_HZ), i.e. this cap was a WALL-
        // CLOCK limit in disguise, not a stuck-state detector. A
        // genuinely stuck game (server deadlocked, or both sides
        // waiting on each other) still gets caught well within this
        // window -- it would stop advancing at all, not merely run
        // long -- whereas the old 260s ceiling was tight enough to
        // occasionally fail a game that was still making perfectly
        // normal progress on its 5000th real tick.
        const hardTimeout = setTimeout(() => {
          reject(
            new Error(
              `Game did not reach GAME_OVER within the time limit. States seen: ${[...seenStates].join(', ')}. ` +
                `Last sync: ${finalSync ? JSON.stringify(finalSync).slice(0, 500) : 'none'}`,
            ),
          );
        }, 320_000);

        const unsubscribe = connection.onMessage((msg: ServerMessage) => {
          if (msg.type === 'welcome') {
            connection.send({ type: 'request_start_game' });
            return;
          }
          if (msg.type === 'reject') {
            clearTimeout(hardTimeout);
            unsubscribe();
            reject(new Error(`Server rejected: ${msg.reason}`));
            return;
          }
          if (msg.type !== 'state_sync') return;

          messageCount += 1;
          if (messageCount > 8000) {
            clearTimeout(hardTimeout);
            unsubscribe();
            reject(new Error('Exceeded 8000 state_sync messages without reaching GAME_OVER -- likely stuck'));
            return;
          }

          finalSync = msg;
          seenStates.add(msg.state);

          // Privacy boundary check (network/state_sync.py's whole
          // reason for existing): the AI opponent's hand must NEVER
          // be present on the wire to this connection, only its
          // count. Checked on every single sync, not just once.
          for (const p of msg.players) {
            if (p.player_id !== msg.you) {
              sawOpponentHandCountPresent = sawOpponentHandCountPresent || p.hand_count >= 0;
              if (p.hand !== null) sawOpponentHandLeak = true;
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
            connection.send({ type: 'intent_choose_suit', suit: 'SPADES' });
          } else if (msg.state === 'JUMP_COUNTER_WINDOW' && msg.counter_player_idx === msg.you) {
            const jump = myHand.find((c) => c.rank === 'J');
            if (jump) connection.send({ type: 'intent_counter', cards: [jump] });
            else connection.send({ type: 'intent_pass_counter' });
          } else if (msg.state === 'POST_PLAY' && msg.post_play?.player_id === msg.you) {
            connection.send({ type: 'intent_post_play_proceed' });
          } else if (msg.state === 'PLAYING' || msg.state === 'KADI_DECLARED') {
            if (msg.current_player_idx === msg.you) {
              const firstPlayable = myHand.find((c) => isPlayableForTest(c, msg.rule_engine, pickupPending));
              if (firstPlayable) {
                // Single card ONLY -- see this file's own history: an
                // earlier version of this test bundled every other
                // same-rank card in behind firstPlayable, reasoning
                // that core/rule_engine.py's is_valid_sequence() calls
                // "all same rank" unconditionally valid. That's true,
                // but core/game_manager.py's _do_play() checks
                // is_playable(cards[0]) FIRST, before ever reaching
                // the same-rank-set check -- and cards[0] after a
                // blind rank filter isn't guaranteed to be
                // firstPlayable itself (hand order, not playability,
                // decides filter() order). A same-rank sibling of a
                // DIFFERENT suit can individually fail is_playable()
                // (its suit-match term differs) even though
                // firstPlayable passed via a suit match rather than a
                // rank match -- landing that sibling at cards[0] got
                // the whole play silently rejected while pickup_
                // pending sat unresolved, hanging this test
                // intermittently depending on hand order/suit
                // distribution. Sending exactly the one card this
                // loop already verified is playable (n==1 is always a
                // structurally valid sequence, per that same function)
                // removes the whole bug class rather than special-
                // casing the ordering.
                connection.send({ type: 'intent_play', cards: [firstPlayable] });
              } else {
                connection.send({ type: 'intent_draw' });
              }
            }
          }
        });
      });

      const finished = await gameOverPromise;

      expect(finished.state).toBe('GAME_OVER');
      expect(finished.players).toHaveLength(2);
      // A 2-player non-elimination game ends the instant one player
      // empties their hand -- finish_order_ids only accumulates
      // incrementally as players finish (see core/game_manager.py),
      // which with just 2 players may never get a chance to record
      // more than the winner before GAME_OVER fires, so the real
      // "did this actually finish" signal is winner_id, checked
      // first; finish_order_ids (when present) must be self-consistent
      // with it.
      expect(finished.winner_id).not.toBeNull();
      if (finished.finish_order_ids.length > 0) {
        expect(finished.finish_order_ids[0]).toBe(finished.winner_id);
      }
      expect(finished.undo_available).toBe(false); // never exposed over the network
      expect(sawOpponentHandCountPresent).toBe(true); // sanity: we actually observed the opponent seat
      expect(sawOpponentHandLeak).toBe(false); // the actual privacy assertion

      connection.close();
    },
    340_000,
  );
});
