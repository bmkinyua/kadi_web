"""
Feature test: LAN multiplayer disconnect handling -- the LAN-side
mirror of tests/test_disconnect_timeout.py's Internet Multiplayer
coverage. See network/host_game.py's module docstring for the design
(same grace-period-then-evict, reconnect-clears-the-timer contract as
server/game_room.GameRoom, just keyed by LANHost's own pid).

Run: SDL_VIDEODRIVER=dummy python -m tests.test_lan_disconnect_timeout
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import network.host_game as host_game_module
from network.host_game import HostGame
from network.client import LANClient

PORT = 52210
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(pred, timeout=3.0, interval=0.02, host=None, dt=0.02):
    start = time.time()
    while time.time() - start < timeout:
        if host is not None:
            host.tick(dt)
        if pred():
            return True
        time.sleep(interval)
    return False


def run_eviction_test():
    print("\n-- LAN: disconnect past the grace period ends the round for the survivor --")
    host_game_module.DISCONNECT_GRACE_SECONDS = 0.15
    host = HostGame(port=PORT)
    host.start_listening(host_name="Host")
    try:
        joiner = LANClient()
        joiner.connect('127.0.0.1', PORT, name='Joiner')
        ok = wait_until(lambda: host.poll_lobby() and 'Joiner' in host.player_names.values(),
                        timeout=2.0)
        check("joiner connected to the LAN host", ok)

        welcome = None
        deadline = time.time() + 2.0
        while time.time() < deadline and welcome is None:
            for m in joiner.poll():
                if m.get('type') == 'welcome':
                    welcome = m
            time.sleep(0.02)
        check("joiner's welcome carries a reconnect token",
              welcome is not None and bool(welcome.get('reconnect_token')))

        host.start_game(elimination_mode=False)
        check("game started with 2 active players",
              sum(1 for p in host.gm.players if not p.finished) == 2)

        joiner.close()
        ok = wait_until(lambda: host.gm.state.name == 'GAME_OVER', timeout=3.0, host=host)
        check("round ends once the grace period elapses with Joiner still gone", ok)
        check("Host is declared the winner",
              host.gm.winner is not None and host.gm.winner.name == 'Host')
        check("Joiner's player object is marked finished+disconnected, not a normal win",
              any(p.name == 'Joiner' and p.finished and p.disconnected
                  for p in (host.gm.finish_order or [])))
    finally:
        host.stop()
        host_game_module.DISCONNECT_GRACE_SECONDS = 30.0


def run_reconnect_test():
    print("\n-- LAN: reconnecting inside the grace period resumes the seat --")
    host_game_module.DISCONNECT_GRACE_SECONDS = 2.0
    host = HostGame(port=PORT + 1)
    host.start_listening(host_name="Host")
    try:
        joiner = LANClient()
        joiner.connect('127.0.0.1', PORT + 1, name='Joiner')
        wait_until(lambda: host.poll_lobby() and 'Joiner' in host.player_names.values(),
                  timeout=2.0)

        token = None
        deadline = time.time() + 2.0
        while time.time() < deadline and token is None:
            for m in joiner.poll():
                if m.get('type') == 'welcome':
                    token = m.get('reconnect_token')
            time.sleep(0.02)
        check("got a reconnect token before starting", bool(token))

        host.start_game(elimination_mode=False)
        joiner_seat = host._seat_by_token.get(token)
        check("joiner has a seat assigned", joiner_seat is not None)

        joiner.close()
        wait_until(lambda: False, timeout=0.4, host=host)
        check("host recorded the disconnect",
              any(host._seat_by_pid.get(pid) == joiner_seat for pid in host._disconnected_at))

        rejoiner = LANClient()
        rejoiner.connect('127.0.0.1', PORT + 1, name='Joiner (reconnecting)')
        # Let the fresh 'hello' get drained harmlessly by a tick before
        # sending the actual reconnect intent.
        host.tick(0.02)
        rejoiner.send({'type': 'rejoin_game', 'token': token})

        rejoined_msg = None
        deadline = time.time() + 2.0
        while time.time() < deadline and rejoined_msg is None:
            host.tick(0.02)
            for m in rejoiner.poll():
                if m.get('type') in ('rejoined', 'reject'):
                    rejoined_msg = m
            time.sleep(0.02)
        check("reconnect request got a reply", rejoined_msg is not None)
        check("reconnect succeeded ('rejoined', not 'reject')",
              rejoined_msg is not None and rejoined_msg.get('type') == 'rejoined')

        check("joiner's seat no longer pending eviction",
              not any(host._seat_by_pid.get(pid) == joiner_seat for pid in host._disconnected_at))

        wait_until(lambda: False, timeout=2.3, host=host)
        check("game still running (joiner was NOT evicted after reconnecting)",
              host.gm.state.name != 'GAME_OVER')
        check("joiner's seat is still active",
              not host.gm.players[joiner_seat].finished)

        rejoiner.close()
    finally:
        host.stop()
        host_game_module.DISCONNECT_GRACE_SECONDS = 30.0


if __name__ == '__main__':
    run_eviction_test()
    run_reconnect_test()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"LAN DISCONNECT TIMEOUT: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("LAN DISCONNECT TIMEOUT: ALL CHECKS PASSED")
        sys.exit(0)
