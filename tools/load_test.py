#!/usr/bin/env python3
"""
tools/load_test.py — stress-tests a REAL, already-running KADI
Internet Multiplayer server (server/kadi_server.py) with many
concurrent simulated players spread across many concurrent games, so
you can watch actual CPU/RAM usage on the server box while it happens
instead of guessing at a ceiling, and get a saved, timestamped report
you can compare across runs to spot where bottlenecks actually show up
(connecting/joining vs. starting vs. gameplay throughput itself).

Deliberately stdlib-only plus network/protocol.py (which is itself
pygame-free — see that module) — no pygame, no importing scenes.py or
constants.py, nothing from the rendering/audio side of the project at
all. That means this script runs anywhere Python 3 runs, and it can
never accidentally diverge from "speaks the real wire protocol exactly
like any other client would," since it doesn't reimplement framing —
it reuses the same FrameBuffer/encode_message every real client and
the server itself already use. MIN_PLAYERS/MAX_PLAYERS below are
plain local constants mirroring constants.py's own values (2/6) rather
than importing that module, specifically to avoid pulling pygame in
just for this.

Each simulated player is genuinely as dumb as possible on purpose: it
only ever sends intent_draw (always legal whenever it's actually their
turn), and intent_post_play_proceed / intent_pass_counter for the
POST_PLAY / JUMP_COUNTER_WINDOW windows — the same "draw until the
30-consecutive-draws stall rule forces a real GAME_OVER" script
tests/test_internet_phase2_authority.py already uses for a single
game, just scaled out across many concurrent connections and rooms.
This deliberately does NOT exercise realistic play strategy — it's a
LOAD test (how many concurrent connections/rooms/messages-per-second
can the server sustain), not a gameplay-quality test; that's already
covered by the project's own tests/ suite.

USAGE
-----
    python3 tools/load_test.py --host kadigame.ddns.net --port 52010 \\
        --games 30 --players-per-game 4

    # Randomized (but evenly spread, not skewed toward one number) player
    # counts per game, between 2 and 6:
    python3 tools/load_test.py --host kadigame.ddns.net --port 52010 \\
        --games 30 --randomize-players

While this runs, watch the server box's own resource usage in a
separate terminal (SSH'd into the box):

    watch -n1 'free -h; echo; systemctl status kadi-server | head -8'

Every game this script starts is a REAL room on your REAL server, and
every player is a REAL connection from wherever you run this script —
if you run it against your public address, make sure the load you're
about to generate is one you actually want to place on that box right
now (and mind your own machine's/network's ability to open that many
outbound connections too, for a large --games x --players-per-game).

REPORTS
-------
Every run writes two timestamped files to tools/reports/ (created
automatically if it doesn't exist yet):

    Internet-MP-Test_DDMMYYYY_HHMMSS.csv   one row per game, every
                                            timing stage broken out
                                            separately, for real
                                            analysis (Excel/Sheets, or
                                            just eyeballing which
                                            column blows up first)
    Internet-MP-Test_DDMMYYYY_HHMMSS.txt   the same human-readable
                                            summary that also prints to
                                            your terminal, saved so you
                                            can diff it against a later
                                            run

CSV over .xlsx deliberately: zero extra dependencies (Python's csv
module is stdlib — an .xlsx writer would need a third-party package
like openpyxl, which may not even be installable on an offline/
locked-down box), opens fine in Excel/Sheets/LibreOffice regardless,
and is trivially diffable/greppable/scriptable if you ever want to
compare many runs' CSVs against each other.

Each per-game row breaks the timeline into 3 independently-timed
stages, which is what actually tells you WHERE a bottleneck is rather
than just THAT one exists:

    connect_seconds  time to create/join the room and get every
                      connection's 'welcome' -- a slow number here
                      points at matchmaking/connection-handling load,
                      not gameplay itself
    start_seconds    time from request_start_game to every connection
                      confirming 'start_game' -- a slow number here
                      points at GameManager.new_game() / room-startup
                      cost, or broadcast fan-out cost
    play_seconds     time from start to a real GAME_OVER -- a slow
                      number here (relative to turns taken) points at
                      per-tick game-loop cost under concurrent load

ARGUMENTS
---------
    --host                  Server address (default: 127.0.0.1)
    --port                  Server port (default: 52010)
    --games                 Number of concurrent games to run (default: 5)
    --players-per-game      Fixed human-like connections per game
                             (default: 3). Ignored if --randomize-players
                             is set.
    --randomize-players     Each game gets its own player count instead of
                             one fixed number for every game. Counts are
                             drawn from --min-players..--max-players using
                             a round-robin-then-shuffle scheme (NOT pure
                             random-per-game) specifically so a small
                             --games count can't, by chance, land mostly
                             on one number -- the distribution across
                             possible counts is as even as integer
                             division allows, only the ORDER games get
                             assigned a count is randomized.
    --min-players           Lower bound for --randomize-players (default: 2,
                             matches the server's own MIN_PLAYERS)
    --max-players           Upper bound for --randomize-players (default: 6,
                             matches the server's own MAX_PLAYERS)
    --ai-per-game           AI-fill seats per game, adds server-side
                             GameManager load without needing more of
                             your own outbound connections (default: 0).
                             Automatically clamped per-game so
                             players + AI never exceeds --max-players
                             (6) -- the server would reject the room
                             start otherwise.
    --max-turns             Safety cap on polling iterations per game, purely
                             as a backstop against a genuine runaway/infinite
                             loop (default: 20000 -- deliberately generous,
                             see --max-seconds below for the cap that
                             actually matters day to day)
    --max-seconds           Wall-clock budget per game before giving up
                             (default: 90). This, not --max-turns, is the
                             cap you'll actually want to tune. AI-fill seats
                             (--ai-per-game) and larger player counts make a
                             game take noticeably LONGER in real time to
                             reach GAME_OVER -- there's real per-turn
                             "thinking" pacing built into AI decisions, and
                             each extra seat dilutes how quickly the
                             30-consecutive-draws stall rule triggers, since
                             every seat gets a turn in between. Don't be
                             surprised if --ai-per-game or a 6-player game
                             needs a larger --max-seconds than a small
                             all-human game.
    --timeout               Seconds to wait for any single expected
                             response (welcome/start_game) before giving up
                             on that game entirely (default: 15)
    --no-report             Skip writing the tools/reports/ files, just
                             print to the terminal (default: off -- reports
                             are written unless you pass this)
"""
from __future__ import annotations
import argparse
import csv
import os
import queue
import random
import socket
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from network.protocol import FrameBuffer, encode_message, ProtocolError

DEFAULT_PORT = 52010
MIN_PLAYERS = 2   # mirrors constants.MIN_PLAYERS -- see module docstring for why
MAX_PLAYERS = 6   # mirrors constants.MAX_PLAYERS -- see module docstring for why

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, 'tools', 'reports')


# ─── one simulated connection ──────────────────────────────────────────────

class LoadTestClient:
    """The same minimal shape network/client.LANClient offers (connect,
    send, poll), reimplemented standalone here rather than imported, so
    this tool has zero dependency on anything pygame-adjacent. Framing
    itself is NOT reimplemented -- FrameBuffer/encode_message are the
    real, shared wire-format code every actual client and the server
    use, imported directly."""

    def __init__(self, name: str):
        self.name = name
        self.sock: Optional[socket.socket] = None
        self.player_id: Optional[int] = None
        self._buf = FrameBuffer()
        self._incoming: "queue.Queue[dict]" = queue.Queue()
        self._alive = False

    def connect(self, host: str, port: int, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(None)
        self._alive = True
        threading.Thread(target=self._recv_loop, daemon=True).start()
        self.send({'type': 'hello', 'name': self.name})

    def _recv_loop(self):
        try:
            while self._alive:
                data = self.sock.recv(4096)
                if not data:
                    break
                try:
                    msgs = self._buf.feed(data)
                except ProtocolError:
                    break
                for m in msgs:
                    if m.get('type') == 'welcome':
                        self.player_id = m.get('player_id')
                    self._incoming.put(m)
        except OSError:
            pass
        finally:
            self._alive = False

    def send(self, msg: dict):
        if not self.sock:
            return
        try:
            self.sock.sendall(encode_message(msg))
        except OSError:
            self._alive = False

    def poll(self) -> List[dict]:
        out = []
        while True:
            try:
                out.append(self._incoming.get_nowait())
            except queue.Empty:
                break
        return out

    def close(self):
        self._alive = False
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass


class Inbox:
    """Accumulates every message a LoadTestClient receives, indexed by
    type, across many poll() calls -- mirrors the same helper the
    project's own tests/test_internet_*.py files use, for the same
    reason: poll() drains the queue every call, so checking for one
    message type must not silently discard a different one that
    arrived in the same batch."""
    def __init__(self, client: LoadTestClient):
        self.client = client
        self.by_type: dict = {}

    def pump(self):
        for m in self.client.poll():
            self.by_type[m.get('type')] = m

    def get(self, type_name: str):
        self.pump()
        return self.by_type.get(type_name)

    def has(self, type_name: str) -> bool:
        return self.get(type_name) is not None


def wait_for(inbox: Inbox, type_name: str, timeout: float) -> Optional[dict]:
    start = time.time()
    while time.time() - start < timeout:
        if inbox.has(type_name):
            return inbox.get(type_name)
        time.sleep(0.03)
    return None


# ─── per-game player-count assignment ──────────────────────────────────────

def build_player_counts(num_games: int, min_p: int, max_p: int,
                        randomize: bool, fixed: int) -> List[int]:
    """See --randomize-players in the module docstring: round-robin
    through every count in [min_p, max_p] enough times to cover
    num_games, THEN shuffle -- guarantees the distribution across
    possible counts is as even as integer division allows (never one
    number dominating just by chance, which pure per-game
    random.randint() could easily do with a small --games), while
    still randomizing which specific game gets which count."""
    if not randomize:
        return [fixed] * num_games
    choices = list(range(min_p, max_p + 1))
    counts = [choices[i % len(choices)] for i in range(num_games)]
    random.shuffle(counts)
    return counts


# ─── one simulated game (N players, played to GAME_OVER) ──────────────────

@dataclass
class GameResult:
    index: int
    players: int
    ai: int
    ok: bool = False
    error: str = ""
    turns: int = 0
    connect_seconds: float = 0.0
    start_seconds: float = 0.0
    play_seconds: float = 0.0
    total_seconds: float = 0.0


def run_one_game(index: int, host: str, port: int, players_per_game: int,
                 ai_per_game: int, max_turns: int, max_seconds: float,
                 timeout: float) -> GameResult:
    # Clamped here (not just left to the server to reject) so a
    # --randomize-players run that happens to land on 6 players plus a
    # nonzero --ai-per-game doesn't silently fail every such game with
    # "not every connection received 'start_game'" -- GameRoom.start_game()
    # itself would reject anything over MAX_PLAYERS total.
    ai_per_game = max(0, min(ai_per_game, MAX_PLAYERS - players_per_game))

    result = GameResult(index=index, players=players_per_game, ai=ai_per_game)
    t_connect_start = time.time()
    clients: List[LoadTestClient] = []
    boxes: List[Inbox] = []
    try:
        creator = LoadTestClient(f"LoadBot-{index}-0")
        creator.connect(host, port)
        clients.append(creator)
        box0 = Inbox(creator)
        boxes.append(box0)

        creator.send({'type': 'create_game', 'settings': {
            'elimination_mode': False, 'ai_count': ai_per_game,
            'ai_difficulty': 'MEDIUM',
            'game_name': f"Load Test Game {index}",
        }})
        welcome = wait_for(box0, 'welcome', timeout)
        if welcome is None:
            result.error = "creator never got 'welcome' (create_game)"
            return result
        game_id = welcome['game_id']

        for i in range(1, players_per_game):
            c = LoadTestClient(f"LoadBot-{index}-{i}")
            c.connect(host, port)
            clients.append(c)
            b = Inbox(c)
            boxes.append(b)
            c.send({'type': 'join_game', 'game_id': game_id})
            w = wait_for(b, 'welcome', timeout)
            if w is None:
                result.error = f"joiner {i} never got 'welcome' (join_game)"
                return result

        t_all_welcomed = time.time()
        result.connect_seconds = t_all_welcomed - t_connect_start

        creator.send({'type': 'request_start_game'})
        started_msgs = [wait_for(b, 'start_game', timeout) for b in boxes]
        if any(m is None for m in started_msgs):
            result.error = "not every connection received 'start_game'"
            result.total_seconds = time.time() - t_connect_start
            return result

        t_started = time.time()
        result.start_seconds = t_started - t_all_welcomed

        # driven to GAME_OVER exactly like
        # tests/test_internet_phase2_authority.py's script: every
        # acting human always draws/proceeds/passes, never plays a
        # card, which is always legal and reliably reaches a real
        # GAME_OVER via GameManager's own stall-resolution rule.
        turns = 0
        state = "PLAYING"
        loop_deadline = time.time() + max_seconds
        while turns < max_turns and time.time() < loop_deadline:
            progressed_this_round = False
            for b in boxes:
                snap = b.get('state_sync')
                if snap is None:
                    continue
                state = snap.get('state')
                if state == 'GAME_OVER':
                    t_over = time.time()
                    result.ok = True
                    result.turns = turns
                    result.play_seconds = t_over - t_started
                    result.total_seconds = t_over - t_connect_start
                    return result
                you = snap.get('you')
                players = snap.get('players', [])
                current_idx = snap.get('current_player_idx')
                current_id = (players[current_idx]['player_id']
                             if players and current_idx is not None
                             and 0 <= current_idx < len(players) else None)
                if state in ('PLAYING', 'KADI_DECLARED') and you == current_id:
                    b.client.send({'type': 'intent_draw'})
                    progressed_this_round = True
                elif state == 'POST_PLAY':
                    pp = snap.get('post_play') or {}
                    if pp.get('player_id') == you:
                        b.client.send({'type': 'intent_post_play_proceed'})
                        progressed_this_round = True
                elif state == 'JUMP_COUNTER_WINDOW':
                    cp_idx = snap.get('counter_player_idx')
                    cp_id = (players[cp_idx]['player_id']
                            if players and cp_idx is not None
                            and 0 <= cp_idx < len(players) else None)
                    if you == cp_id:
                        b.client.send({'type': 'intent_pass_counter'})
                        progressed_this_round = True
            for b in boxes:
                b.pump()
            turns += 1
            time.sleep(0.03)
            if not progressed_this_round:
                time.sleep(0.05)

        hit_turns = turns >= max_turns
        result.play_seconds = time.time() - t_started
        result.total_seconds = time.time() - t_connect_start
        result.error = (f"hit max_turns ({max_turns}) without reaching GAME_OVER "
                        if hit_turns else
                        f"hit max_seconds ({max_seconds:.0f}s) without reaching GAME_OVER "
                        f"-- try a larger --max-seconds, especially with --ai-per-game > 0 "
                        f"or more players ") \
                       + f"(last known state: {state})"
        return result
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.total_seconds = time.time() - t_connect_start
        return result
    finally:
        for c in clients:
            c.close()


# ─── report writing ─────────────────────────────────────────────────────────

def _avg(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def write_reports(results: List[GameResult], args, wall_elapsed: float) -> tuple:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%d%m%Y_%H%M%S')
    base = f"Internet-MP-Test_{stamp}"
    csv_path = os.path.join(REPORTS_DIR, base + '.csv')
    txt_path = os.path.join(REPORTS_DIR, base + '.txt')

    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['game_index', 'players', 'ai_seats', 'result',
                   'connect_seconds', 'start_seconds', 'play_seconds',
                   'total_seconds', 'turns', 'error'])
        for r in results:
            w.writerow([r.index, r.players, r.ai, "OK" if r.ok else "FAIL",
                       f"{r.connect_seconds:.3f}", f"{r.start_seconds:.3f}",
                       f"{r.play_seconds:.3f}", f"{r.total_seconds:.3f}",
                       r.turns, r.error])

    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    connect_times = [r.connect_seconds for r in results if r.connect_seconds]
    start_times = [r.start_seconds for r in results if r.start_seconds]
    play_times = [r.play_seconds for r in ok]

    lines = []
    lines.append("KADI Internet Multiplayer -- Load Test Report")
    lines.append(f"Run: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append(f"Target: {args.host}:{args.port}")
    players_desc = (f"randomized {args.min_players}-{args.max_players}"
                    if args.randomize_players else str(args.players_per_game))
    lines.append(f"Games: {args.games}, players-per-game: {players_desc}, "
                f"AI-per-game: {args.ai_per_game}")
    lines.append(f"Total real connections: {sum(r.players for r in results)}")
    lines.append(f"Wall clock: {wall_elapsed:.1f}s")
    lines.append("")
    lines.append(f"Result: {len(ok)}/{len(results)} games reached a real GAME_OVER")
    lines.append("")
    lines.append("-- Stage timing (this is what tells you WHERE a bottleneck is) --")
    if connect_times:
        lines.append(f"connect_seconds  (create/join -> every 'welcome')      "
                    f"min={min(connect_times):.2f}  avg={_avg(connect_times):.2f}  "
                    f"max={max(connect_times):.2f}")
    if start_times:
        lines.append(f"start_seconds    (request_start -> every 'start_game') "
                    f"min={min(start_times):.2f}  avg={_avg(start_times):.2f}  "
                    f"max={max(start_times):.2f}")
    if play_times:
        lines.append(f"play_seconds     (start -> real GAME_OVER, OK games)   "
                    f"min={min(play_times):.2f}  avg={_avg(play_times):.2f}  "
                    f"max={max(play_times):.2f}")
    lines.append("")
    # Flag whichever stage has the widest max/avg spread as the likely
    # bottleneck under THIS run's load -- a stage that blows out relative
    # to its own average, more than the others do, is where load is
    # actually biting.
    stage_spread = {}
    if connect_times and _avg(connect_times) > 0:
        stage_spread['connecting/joining'] = max(connect_times) / _avg(connect_times)
    if start_times and _avg(start_times) > 0:
        stage_spread['starting the match'] = max(start_times) / _avg(start_times)
    if play_times and _avg(play_times) > 0:
        stage_spread['gameplay throughput'] = max(play_times) / _avg(play_times)
    if stage_spread:
        worst = max(stage_spread, key=stage_spread.get)
        lines.append(f"Widest max-vs-average spread: {worst} "
                    f"({stage_spread[worst]:.1f}x its own average) -- if a "
                    f"bottleneck showed up under this load, this stage is "
                    f"the most likely place to look first.")
        lines.append("")
    if failed:
        lines.append(f"-- {len(failed)} game(s) did not finish --")
        for r in failed:
            lines.append(f"  Game {r.index} ({r.players}p+{r.ai}ai): {r.error}")
        lines.append("")
    lines.append("-- Per-game detail --")
    lines.append(f"{'Game':<6}{'Players':<9}{'AI':<4}{'Result':<8}{'Connect':<10}"
                f"{'Start':<9}{'Play':<9}{'Turns':<8}Notes")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        lines.append(f"{r.index:<6}{r.players:<9}{r.ai:<4}{status:<8}"
                    f"{r.connect_seconds:<10.2f}{r.start_seconds:<9.2f}"
                    f"{r.play_seconds:<9.2f}{r.turns:<8}{r.error}")

    text = "\n".join(lines) + "\n"
    with open(txt_path, 'w') as f:
        f.write(text)

    return csv_path, txt_path, text


# ─── orchestration ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Load-test a running KADI Internet Multiplayer server.")
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--games', type=int, default=5)
    parser.add_argument('--players-per-game', type=int, default=3)
    parser.add_argument('--randomize-players', action='store_true')
    parser.add_argument('--min-players', type=int, default=MIN_PLAYERS)
    parser.add_argument('--max-players', type=int, default=MAX_PLAYERS)
    parser.add_argument('--ai-per-game', type=int, default=0)
    parser.add_argument('--max-turns', type=int, default=20000)
    parser.add_argument('--max-seconds', type=float, default=90.0)
    parser.add_argument('--timeout', type=float, default=15.0)
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()

    if args.min_players < MIN_PLAYERS or args.max_players > MAX_PLAYERS \
            or args.min_players > args.max_players:
        print(f"--min-players/--max-players must be within "
             f"{MIN_PLAYERS}-{MAX_PLAYERS} and min <= max "
             f"(the server's own room limits).")
        sys.exit(2)

    player_counts = build_player_counts(args.games, args.min_players, args.max_players,
                                        args.randomize_players, args.players_per_game)
    total_players = sum(player_counts)

    if args.randomize_players:
        dist = Counter(player_counts)
        dist_str = ", ".join(f"{k}p x{v}" for k, v in sorted(dist.items()))
        print(f"Load test: {args.games} concurrent games, RANDOMIZED player counts "
             f"({args.min_players}-{args.max_players}): {dist_str} "
             f"({total_players} real connections total) against "
             f"{args.host}:{args.port}")
    else:
        print(f"Load test: {args.games} concurrent games, "
             f"{args.players_per_game} players + {args.ai_per_game} AI each "
             f"({total_players} real connections total) against "
             f"{args.host}:{args.port}")
    print("Watch the server box's own resources in another terminal:")
    print("    watch -n1 'free -h; echo; systemctl status kadi-server | head -8'")
    print()

    results: List[GameResult] = [None] * args.games  # type: ignore
    threads = []

    def worker(i):
        results[i] = run_one_game(i, args.host, args.port, player_counts[i],
                                  args.ai_per_game, args.max_turns, args.max_seconds,
                                  args.timeout)

    wall_start = time.time()
    for i in range(args.games):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    wall_elapsed = time.time() - wall_start

    ok_count = sum(1 for r in results if r.ok)
    print(f"{'Game':<6}{'Players':<9}{'AI':<4}{'Result':<8}{'Connect':<10}"
         f"{'Start':<9}{'Play':<9}{'Turns':<8}Notes")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        print(f"{r.index:<6}{r.players:<9}{r.ai:<4}{status:<8}"
             f"{r.connect_seconds:<10.2f}{r.start_seconds:<9.2f}"
             f"{r.play_seconds:<9.2f}{r.turns:<8}{r.error}")

    print()
    print(f"{ok_count}/{args.games} games reached a real GAME_OVER "
         f"({total_players} concurrent connections, "
         f"wall clock: {wall_elapsed:.1f}s)")

    if not args.no_report:
        csv_path, txt_path, _ = write_reports(results, args, wall_elapsed)
        print()
        print("Report written:")
        print(f"  {csv_path}")
        print(f"  {txt_path}")

    if ok_count < args.games:
        print()
        print("Some games did not finish -- this could mean the server is "
             "genuinely struggling at this load, OR just that --max-seconds "
             "needs to be more generous (especially with --ai-per-game > 0 "
             "or larger --players-per-game -- see the --max-seconds help "
             "text). Check the server's own logs (journalctl -u kadi-server "
             "-n 100) before concluding it's a capacity problem.")
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
