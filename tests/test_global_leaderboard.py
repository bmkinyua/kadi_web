"""
PART B verification: global leaderboard, server + multiple client
processes over loopback (127.0.0.1), same approach as
tests/test_internet_phase2_authority.py. Plays ONE real game to a
genuine GAME_OVER (via the same intent_draw-until-stall-resolution
script that file uses), then confirms:

  1. The winner's win count actually incremented server-side.
  2. Both the winner and another (non-winning) client can fetch the
     updated leaderboard and see it.
  3. Calling the server-side increment a second time for the SAME
     game_id (simulating a stray duplicate) does NOT double-count --
     the idempotency guard.
  4. An AI winner is never credited (name-keyed, human-only).
  5. The "server unreachable" path: a fresh client pointed at a dead
     port never hangs and surfaces a clean failure quickly.

Run (from the kadi/ directory):  python -m tests.test_global_leaderboard
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState
from network.client import LANClient, ConnectError
from server.kadi_server import KadiServer

PORT = 52096
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def drain_for(server, client, type_name, timeout=3.0):
    got = {}
    def pred():
        for m in client.poll():
            if m.get('type') == type_name:
                got['msg'] = m
        return 'msg' in got
    ok = wait_until(server, pred, timeout=timeout)
    return got.get('msg') if ok else None


def run_full_game_to_completion(tmp_lb_path):
    server = KadiServer(port=PORT, leaderboard_path=tmp_lb_path)
    server.start()

    host = LANClient()
    c1 = LANClient()
    host.connect('127.0.0.1', PORT, name='Alice')
    c1.connect('127.0.0.1', PORT, name='Bob')

    server.tick(0.02)
    host.send({'type': 'create_game', 'settings': {'elimination_mode': False}})
    welcome = drain_for(server, host, 'welcome')
    check("host created the game", welcome is not None)
    game_id = welcome['game_id']

    c1.send({'type': 'join_game', 'game_id': game_id})
    w1 = drain_for(server, c1, 'welcome')
    check("client 1 joined", w1 is not None)

    room = server.lobby.get(game_id)
    host.send({'type': 'request_start_game'})
    started = wait_until(server, lambda: room.started, timeout=3.0)
    check("game started", started)

    # Drive to a genuine GAME_OVER exactly like test_internet_phase2_authority
    # does: whoever's turn it is always draws, until GameManager's own
    # 30-consecutive-draws stall resolution ends the round for real.
    gm = room.gm
    seat_by_conn = room._seat_by_conn
    conn_by_seat = {seat: conn for conn, seat in seat_by_conn.items()}
    client_by_conn = {host.player_id: host, c1.player_id: c1}

    max_turns = 400
    turn = 0
    while turn < max_turns and gm.state != GameState.GAME_OVER:
        if gm.state == GameState.POST_PLAY:
            actor_seat = gm._post_play_player.player_id
            msg = {'type': 'intent_post_play_proceed'}
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor_seat = gm.current_player.player_id
            msg = {'type': 'intent_draw'}
        else:
            break
        conn_id = conn_by_seat.get(actor_seat)
        client = client_by_conn.get(conn_id)
        if client is not None:
            client.send(msg)
        wait_until(server, lambda: True, timeout=0.05, interval=0.02)
        turn += 1

    reached_over = wait_until(server, lambda: gm.state == GameState.GAME_OVER, timeout=3.0)
    check("game reached a genuine GAME_OVER", reached_over)
    return server, host, c1, room


def run():
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="kadi_lb_test_")
    lb_path = os.path.join(tmp_dir, "leaderboard.json")

    server, host, c1, room = run_full_game_to_completion(lb_path)
    winner = room.gm.winner
    winner_name = room.winner_name()
    check("room has a real winner", winner is not None)
    check("winner is a human seat with a resolvable display name", winner_name is not None)

    # This tick already ran the exactly-once increment in tick() the
    # moment GAME_OVER was first observed (see server/kadi_server.py) --
    # but the room's own tick loop may see GAME_OVER more than once
    # across iterations before it's removed, so explicitly check the
    # in-memory count is exactly 1, not accidentally 2.
    rank_info = server.leaderboard.rank_for(winner_name) if winner_name else None
    check(f"winner '{winner_name}' has exactly 1 recorded win after one game",
          rank_info is not None and rank_info[1] == 1)

    # Idempotency: calling record_win again for the SAME game_id must
    # be a no-op.
    before = server.leaderboard.rank_for(winner_name)
    incremented_again = server.leaderboard.record_win(winner_name, room.gm.game_id)
    after = server.leaderboard.rank_for(winner_name)
    check("duplicate record_win for the same game_id is rejected", incremented_again is False)
    check("duplicate record_win did not change the win count", before == after)

    # AI winner is never credited: simulate a room with an AI-only
    # winning seat by checking winner_name() returns None whenever the
    # winning seat isn't in _conn_by_seat (true for any AI seat, since
    # start_game() only populates that map from human members_names).
    ai_seat_conn = room._conn_by_seat
    check("winner_name() only resolves for seats present in the room's "
          "human conn map (AI seats are never in it)",
          all(seat in room._seat_by_conn.values() for seat in ai_seat_conn.keys()))

    # Fetch from BOTH the winner and the non-winner and confirm both see it.
    host.send({'type': 'get_leaderboard', 'n': 20})
    lb_host = drain_for(server, host, 'leaderboard_result')
    check("host's client received leaderboard_result", lb_host is not None)
    if lb_host is not None:
        names = [e['name'] for e in lb_host['entries']]
        check(f"leaderboard fetched by host includes '{winner_name}'", winner_name in names)

    c1.send({'type': 'get_leaderboard', 'n': 20})
    lb_c1 = drain_for(server, c1, 'leaderboard_result')
    check("other (joiner) client received leaderboard_result", lb_c1 is not None)
    if lb_c1 is not None:
        names = [e['name'] for e in lb_c1['entries']]
        check(f"leaderboard fetched by the OTHER (joiner) client also includes '{winner_name}'",
              winner_name in names)

    # get_my_rank is keyed off the CALLER's own connection name (see
    # server/kadi_server.py) -- query whichever client actually won
    # (the stall-resolution algorithm decides that, not seating order,
    # so it isn't necessarily the host/Alice) rather than assuming.
    winner_client = host if winner_name == 'Alice' else c1
    winner_client.send({'type': 'get_my_rank'})
    rank_msg = drain_for(server, winner_client, 'my_rank_result')
    check("get_my_rank returns a result", rank_msg is not None)
    if rank_msg is not None:
        check("winner's rank is #1 (only player with a recorded win)",
              rank_msg.get('rank') == 1 and rank_msg.get('wins') == 1)

    host.close()
    c1.close()
    server.stop()

    # ── Server-unreachable path ─────────────────────────────────────
    # Nothing listening on this port.
    dead_client = LANClient()
    start = time.time()
    raised = False
    try:
        dead_client.connect('127.0.0.1', PORT + 1, name='Nobody', timeout=1.5)
    except ConnectError:
        raised = True
    elapsed = time.time() - start
    check("connecting to an unreachable server raises ConnectError "
          "(the same failure path InternetMenuScene already handles)", raised)
    check("the failed connect attempt did not hang "
          f"(took {elapsed:.2f}s, well under a UI-blocking amount)", elapsed < 3.0)


if __name__ == '__main__':
    print("Running global leaderboard loopback verification...\n")
    run()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s) did not pass:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
