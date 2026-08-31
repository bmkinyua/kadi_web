"""
Feature test: Internet multiplayer disconnect handling.

Covers:
  - a mid-game disconnect doesn't hang the room forever -- after
    server.game_room.DISCONNECT_GRACE_SECONDS with no reconnect, the
    disconnected seat is force-removed (GameManager.force_remove_player)
  - if that leaves only one player in the match, they're declared the
    winner immediately and the round ends
  - a client that reconnects (same token) BEFORE the grace period
    expires resumes their seat and the timer is forgotten, rather than
    still being evicted later
  - an internet server prompt-visibility corollary: nothing above ever
    hangs the server tick loop or the other player's own client

Run: SDL_VIDEODRIVER=dummy python -m tests.test_disconnect_timeout
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.game_room as game_room_module
from network.client import LANClient
from server.kadi_server import KadiServer

PORT = 52109
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


class Inbox:
    def __init__(self, client: LANClient):
        self.client = client
        self.by_type: dict = {}
        self.all_msgs: list = []

    def pump(self):
        for m in self.client.poll():
            self.by_type[m.get('type')] = m
            self.all_msgs.append(m)

    def has(self, type_name: str) -> bool:
        self.pump()
        return type_name in self.by_type

    def get(self, type_name: str):
        self.pump()
        return self.by_type.get(type_name)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def run_eviction_test():
    print("\n-- disconnect past the grace period ends the round for the survivor --")
    game_room_module.DISCONNECT_GRACE_SECONDS = 0.15  # sped up just for this test
    server = KadiServer(port=PORT)
    server.start()
    try:
        alice = LANClient()
        alice.connect('127.0.0.1', PORT, name='Alice')
        alice_box = Inbox(alice)
        server.tick(0.02)
        alice.send({'type': 'create_game',
                   'settings': {'elimination_mode': False, 'ai_count': 0}})
        ok = wait_until(server, lambda: alice_box.has('welcome'))
        check("Alice's room created", ok)
        game_id = alice_box.get('welcome')['game_id']

        bob = LANClient()
        bob.connect('127.0.0.1', PORT, name='Bob')
        bob_box = Inbox(bob)
        server.tick(0.02)
        bob.send({'type': 'join_game', 'game_id': game_id})
        ok = wait_until(server, lambda: bob_box.has('welcome'))
        check("Bob joined", ok)
        bob_token = bob_box.get('welcome').get('reconnect_token')
        check("Bob's welcome carries a reconnect token", bool(bob_token))

        alice.send({'type': 'request_start_game'})
        ok = wait_until(server, lambda: alice_box.has('start_game') and bob_box.has('start_game'))
        check("game started", ok)

        room = server.lobby.get(game_id)
        check("room shows 2 active (non-finished) players before disconnect",
              sum(1 for p in room.gm.players if not p.finished) == 2)

        # Bob's connection dies mid-game (app crash / network drop) --
        # NOT a clean 'leave the lobby' scenario, since the game has
        # already started.
        bob.close()
        ok = wait_until(server, lambda: game_id not in [r.game_id for r in server.lobby.all_rooms()]
                        or room.gm.state.name == 'GAME_OVER', timeout=3.0)
        check("round ends once the grace period elapses with Bob still gone", ok)
        check("Alice is declared the winner", room.gm.winner is not None
              and room.gm.winner.name == 'Alice')
        check("Bob's player object is marked finished (removed) not a normal win",
              any(p.name == 'Bob' and p.finished and p.disconnected for p in
                  (room.gm.finish_order or [])))

        alice.close()
    finally:
        server.stop()
        game_room_module.DISCONNECT_GRACE_SECONDS = 30.0  # restore default


def run_reconnect_test():
    print("\n-- reconnecting inside the grace period resumes the seat and clears the timer --")
    game_room_module.DISCONNECT_GRACE_SECONDS = 2.0
    server = KadiServer(port=PORT + 1)
    try:
        server.start()
        alice = LANClient()
        alice.connect('127.0.0.1', PORT + 1, name='Alice')
        alice_box = Inbox(alice)
        server.tick(0.02)
        alice.send({'type': 'create_game',
                   'settings': {'elimination_mode': False, 'ai_count': 0}})
        wait_until(server, lambda: alice_box.has('welcome'))
        game_id = alice_box.get('welcome')['game_id']

        bob = LANClient()
        bob.connect('127.0.0.1', PORT + 1, name='Bob')
        bob_box = Inbox(bob)
        server.tick(0.02)
        bob.send({'type': 'join_game', 'game_id': game_id})
        wait_until(server, lambda: bob_box.has('welcome'))
        bob_token = bob_box.get('welcome')['reconnect_token']

        alice.send({'type': 'request_start_game'})
        wait_until(server, lambda: alice_box.has('start_game') and bob_box.has('start_game'))

        room = server.lobby.get(game_id)
        bob_seat = room._seat_by_token.get(bob_token)
        check("Bob has a seat assigned at game start", bob_seat is not None)

        bob.close()
        wait_until(server, lambda: False, timeout=0.4)  # let the disconnect register
        check("room recorded Bob's disconnect", any(
            room._seat_by_conn.get(cid) == bob_seat for cid in room._disconnected_at))

        # Bob reconnects well within the (sped-up) 2s grace window.
        bob2 = LANClient()
        bob2.connect('127.0.0.1', PORT + 1, name='Bob (reconnecting)')
        bob2_box = Inbox(bob2)
        server.tick(0.02)
        bob2.send({'type': 'rejoin_game', 'game_id': game_id, 'token': bob_token})
        ok = wait_until(server, lambda: bob2_box.has('rejoined') or bob2_box.has('reject'))
        check("reconnect request got a reply", ok)
        check("reconnect succeeded ('rejoined', not 'reject')", bob2_box.has('rejoined'))

        check("Bob's seat is no longer pending eviction after reconnecting",
              not any(room._seat_by_conn.get(cid) == bob_seat for cid in room._disconnected_at))

        # Give it well past the (sped-up) grace window and confirm Bob
        # is NOT evicted, since he successfully reconnected in time.
        wait_until(server, lambda: False, timeout=2.3)
        check("game is still running (Bob was NOT evicted after reconnecting)",
              room.gm.state.name != 'GAME_OVER')
        check("Bob's seat is still active, not finished",
              not room.gm.players[bob_seat].finished)

        alice.close()
        bob2.close()
    finally:
        server.stop()
        game_room_module.DISCONNECT_GRACE_SECONDS = 30.0


if __name__ == '__main__':
    run_eviction_test()
    run_reconnect_test()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"DISCONNECT TIMEOUT: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("DISCONNECT TIMEOUT: ALL CHECKS PASSED")
        sys.exit(0)
