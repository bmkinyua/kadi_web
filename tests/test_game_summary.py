"""
Verification for the new 'game_summary' message (Profile Part 5
disclosure -- see network/game_summary.py, server/game_room.py's
game_summary_for()/_mode_and_difficulty(), and server/kadi_server.py's
GAME_OVER hook in tick()).

Same real-server-over-loopback approach as tests/test_global_leaderboard.py
(reuses its run_full_game_to_completion, imported directly rather than
copy-pasted) -- an actual KadiServer, real LANClient connections, a
genuine GAME_OVER reached via the same intent_draw-until-stall-
resolution script. Because that script only ever sends intent_draw
(no real card plays), most of the mechanic-specific tallies
(aces_played, kadi_declarations, ...) stay at zero for real, which is
itself a value worth asserting (the always-zero defaulting path
works) -- the one tally guaranteed to move is cards_drawn, since every
turn in this script is a draw, which is what the per-player-
attribution checks below key off.

Run (from the kadi/ directory):  python -m tests.test_game_summary
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState
from network.client import LANClient
from server.kadi_server import KadiServer
from tests.test_global_leaderboard import (
    run_full_game_to_completion, drain_for, wait_until, check, FAILURES, PORT,
)

SUMMARY_FIELDS = {
    'won', 'mode', 'difficulty', 'finish_kind', 'opponent_had_msomi',
    'elimination_mode', 'cards_played', 'cards_drawn',
    'biggest_pickup_absorbed', 'kadi_declarations', 'aces_played',
    'jump_skips_dealt', 'kickback_reversals', 'ace_shield_uses',
    'ace_shield_biggest', 'jump_counter_depth', 'near_kadi_count',
    'undo_used_this_game', 'bluff_suit_win', 'kuficha_trap_win',
}


def run_two_human_game():
    print("\n-- Two-human internet game --")
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="kadi_summary_test_")
    lb_path = os.path.join(tmp_dir, "leaderboard.json")

    server, host, c1, room = run_full_game_to_completion(lb_path)
    gm = room.gm
    seat_by_conn = room._seat_by_conn
    winner = gm.winner
    check("a genuine winner exists", winner is not None)

    host_summary = drain_for(server, host, 'game_summary', timeout=2.0)
    c1_summary = drain_for(server, c1, 'game_summary', timeout=2.0)
    check("host received a game_summary", host_summary is not None)
    check("client 1 received a game_summary", c1_summary is not None)
    if host_summary is None or c1_summary is None:
        return

    check("game_summary carries exactly the documented field set (plus type/you)",
          set(host_summary.keys()) == SUMMARY_FIELDS | {'type', 'you'})

    check("mode is 'internet' for a 2-human room", host_summary['mode'] == 'internet')
    check("mode is 'internet' for a 2-human room (other recipient)", c1_summary['mode'] == 'internet')
    check("difficulty is None for internet mode", host_summary['difficulty'] is None)

    host_won = host_summary['you'] == winner.player_id
    c1_won = c1_summary['you'] == winner.player_id
    check("exactly one recipient's summary reports won=True", host_won != c1_won)
    check("the winning recipient's own summary says won=True",
          host_summary['won'] == host_won and c1_summary['won'] == c1_won)

    # Per-player attribution: this room's two humans drew on different
    # turns, so their own personal cards_drawn must independently sum
    # back to the room's real aggregate -- proof the split isn't
    # accidentally attributing one player's draws to the other, or
    # double-counting/dropping any (see network/game_summary.py's
    # module docstring for why this mattered enough to fix).
    check("neither recipient's summary is silently zeroed out",
          host_summary['cards_drawn'] > 0 and c1_summary['cards_drawn'] > 0)
    check("per-player cards_drawn sums back to the room's real aggregate, "
          "exactly (no player's draws attributed to the other, none dropped)",
          host_summary['cards_drawn'] + c1_summary['cards_drawn'] == gm._g_cards_drawn)

    check("undo_used_this_game is always False over the network (undo isn't exposed)",
          host_summary['undo_used_this_game'] is False and c1_summary['undo_used_this_game'] is False)

    # Fired exactly once: further ticks (the room is already closed and
    # removed from the lobby by now) must not produce a second message.
    for _ in range(5):
        server.tick(0.02)
    extra = drain_for(server, host, 'game_summary', timeout=0.3)
    check("no duplicate game_summary arrives on later ticks", extra is None)

    server.stop()


def run_single_human_vs_ai_game():
    print("\n-- Single human vs AI (Quick Play) --")
    server = KadiServer(port=PORT + 1)
    server.start()
    host = LANClient()
    host.connect('127.0.0.1', PORT + 1, name='Solo')
    server.tick(0.02)
    host.send({'type': 'create_game', 'settings': {'ai_count': 1, 'ai_difficulty': 'HARD'}})
    welcome = drain_for(server, host, 'welcome')
    check("solo host created a vs-AI game", welcome is not None)
    if welcome is None:
        server.stop()
        return
    game_id = welcome['game_id']
    room = server.lobby.get(game_id)
    host.send({'type': 'request_start_game'})
    started = wait_until(server, lambda: room.started, timeout=3.0)
    check("solo vs-AI game started", started)

    # Unlike run_full_game_to_completion's 2-human stall-resolution
    # script (every seat always draws, deliberately never converging
    # "naturally" so the 30-consecutive-draws force-resolve kicks in),
    # a real AI opponent here keeps playing normal legal moves and
    # keeps resetting that same consecutive-draw counter -- so a
    # human who ONLY ever draws can't trigger it either (the counter
    # is global to the round, not per-player; see
    # GameManager._resolve_stall/_consecutive_draws). The AI has to
    # actually finish the round for real, which takes wall-clock time
    # for its own "thinking pause" (AIDifficulty.HARD: 0.3-0.7s per
    # decision, see models/player.py's _get_think_time) across
    # however many real turns the round needs -- so this drives with
    # a real time budget instead of a fixed iteration count.
    gm = room.gm

    def human_turn_acted():
        if gm.state == GameState.POST_PLAY and gm._post_play_player is gm.players[0]:
            host.send({'type': 'intent_post_play_proceed'})
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED) and gm.current_player is gm.players[0]:
            host.send({'type': 'intent_draw'})
        return gm.state == GameState.GAME_OVER

    reached_over = wait_until(server, human_turn_acted, timeout=90.0, interval=0.02)
    check("solo vs-AI game reached a genuine GAME_OVER", reached_over)

    summary = drain_for(server, host, 'game_summary', timeout=2.0)
    check("solo human received a game_summary", summary is not None)
    if summary is not None:
        check("mode is 'single_player' for a 1-human room", summary['mode'] == 'single_player')
        check("difficulty reflects this room's configured AI difficulty",
              summary['difficulty'] == 'HARD')
    server.stop()


def run():
    run_two_human_game()
    run_single_human_vs_ai_game()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All game_summary checks passed.")


if __name__ == '__main__':
    run()
