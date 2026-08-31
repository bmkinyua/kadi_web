"""
INTERNET MULTIPLAYER — PHASE 1 verification: the server's lobby /
matchmaking logic in isolation (create game, list open games, join a
game), with the server and several client connections all on loopback
(127.0.0.1). Confirms lobby state is correct from every client's view
before any game-authority logic is exercised.

Reuses network.client.LANClient completely unmodified as the client
transport -- exactly the point of extending the existing protocol/
client architecture rather than inventing a new one.

Run (from the kadi/ directory):  python -m tests.test_internet_phase1_lobby
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.client import LANClient
from server.kadi_server import KadiServer

PORT = 52091
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


class Inbox:
    """Accumulates every message a LANClient receives, indexed by
    type, across many poll() calls -- so checking for one message
    type doesn't silently discard a different one that arrived in the
    same batch (poll() drains the queue every time it's called)."""
    def __init__(self, client: LANClient):
        self.client = client
        self.by_type: dict = {}

    def pump(self):
        for m in self.client.poll():
            self.by_type[m.get('type')] = m

    def has(self, type_name: str) -> bool:
        self.pump()
        return type_name in self.by_type

    def get(self, type_name: str):
        self.pump()
        return self.by_type.get(type_name)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    """Ticks the server once per poll iteration (this standalone test
    has no separately-running server process) and polls `pred`."""
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def test_create_list_join():
    print("\n-- create_game / list_games / join_game --")
    server = KadiServer(port=PORT)
    server.start()
    try:
        host = LANClient()
        host.connect('127.0.0.1', PORT, name='Alice')
        host_box = Inbox(host)

        server.tick(0.02)
        host.send({'type': 'create_game', 'settings': {'elimination_mode': True,
                                                        'ai_count': 0}})

        ok = wait_until(server, lambda: host_box.has('welcome'))
        check("host received welcome after create_game", ok)
        welcome = host_box.get('welcome')
        check("host is player_id-consistent with LANClient.player_id",
              ok and welcome['player_id'] == host.player_id)
        check("welcome identifies this connection as its own host_id",
              ok and welcome['host_id'] == host.player_id)
        game_id = welcome['game_id']
        check("welcome carries a game_id", bool(game_id))

        ok = wait_until(server, lambda: host_box.has('lobby_state'))
        lobby_state = host_box.get('lobby_state')
        check("host received an initial lobby_state with itself as sole member",
              ok and len(lobby_state['players']) == 1)

        # A second client should now be able to LIST this open game.
        joiner = LANClient()
        joiner.connect('127.0.0.1', PORT, name='Bob')
        joiner_box = Inbox(joiner)
        server.tick(0.02)
        joiner.send({'type': 'list_games'})

        ok = wait_until(server, lambda: joiner_box.has('games_list'))
        games = joiner_box.get('games_list')['games'] if ok else []
        check("joiner's list_games returned at least one open game", ok and len(games) >= 1)
        if ok and games:
            game_entry = next((g for g in games if g['game_id'] == game_id), None)
            check("listed game found by game_id", game_entry is not None)
            if game_entry:
                check("listed game shows correct host_name", game_entry['host_name'] == 'Alice')
                check("listed game shows player_count 1", game_entry['player_count'] == 1)
                check("listed game's settings rows reflect Elimination Mode ON",
                      any(r[0] == 'Elimination Mode' and r[1] == 'ON'
                         for r in game_entry['rows']))

        # Now the joiner actually joins.
        joiner.send({'type': 'join_game', 'game_id': game_id})
        ok = wait_until(server, lambda: joiner_box.has('welcome'))
        check("joiner received welcome after join_game", ok)
        if ok:
            check("joiner's assigned host_id matches the actual host's connection id",
                  joiner_box.get('welcome')['host_id'] == host.player_id)

        # Both host and joiner should now see a 2-player roster --
        # each poll of lobby_state overwrites the Inbox entry, so this
        # naturally checks the LATEST one once both have converged.
        def both_see_two():
            host_box.pump()
            joiner_box.pump()
            h = host_box.by_type.get('lobby_state')
            j = joiner_box.by_type.get('lobby_state')
            return (h is not None and len(h['players']) == 2
                   and j is not None and len(j['players']) == 2)

        ok = wait_until(server, both_see_two)
        check("both host and joiner converge on a 2-player roster view", ok)

        host.close()
        joiner.close()
    finally:
        server.stop()


def test_room_full_and_reject():
    print("\n-- reject on unknown game_id --")
    server = KadiServer(port=PORT + 1)
    server.start()
    try:
        c = LANClient()
        c.connect('127.0.0.1', PORT + 1, name='Solo')
        box = Inbox(c)
        server.tick(0.02)
        c.send({'type': 'join_game', 'game_id': 'game_does_not_exist'})

        ok = wait_until(server, lambda: box.has('reject'))
        check("joining a nonexistent game_id yields a reject", ok)
        c.close()
    finally:
        server.stop()


def test_host_leaves_lobby_closes_room():
    print("\n-- host disconnecting pre-start closes the room --")
    server = KadiServer(port=PORT + 2)
    server.start()
    try:
        host = LANClient()
        host.connect('127.0.0.1', PORT + 2, name='Alice')
        host_box = Inbox(host)
        server.tick(0.02)
        host.send({'type': 'create_game', 'settings': {}})

        ok = wait_until(server, lambda: host_box.has('welcome'))
        check("host created a game", ok)
        game_id = host_box.get('welcome')['game_id']

        joiner = LANClient()
        joiner.connect('127.0.0.1', PORT + 2, name='Bob')
        joiner_box = Inbox(joiner)
        server.tick(0.02)
        joiner.send({'type': 'join_game', 'game_id': game_id})
        wait_until(server, lambda: joiner_box.has('welcome'))

        # Host disconnects before starting -- the joiner should be
        # told the room closed, and the game should no longer be listed.
        host.close()

        ok = wait_until(server, lambda: joiner_box.has('room_closed'))
        check("joiner is notified the room closed after the host disconnected", ok)

        joiner.send({'type': 'list_games'})
        # A fresh games_list may arrive after the one already cached
        # from earlier in the Inbox -- clear it so we check the reply
        # to THIS list_games, not a stale one.
        joiner_box.by_type.pop('games_list', None)
        ok = wait_until(server, lambda: joiner_box.has('games_list'))
        games = joiner_box.get('games_list')['games'] if ok else []
        check("closed room no longer appears in list_games",
              ok and game_id not in [g['game_id'] for g in games])
        joiner.close()
    finally:
        server.stop()


if __name__ == '__main__':
    test_create_list_join()
    test_room_full_and_reject()
    test_host_leaves_lobby_closes_room()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET PHASE 1: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET PHASE 1: ALL CHECKS PASSED")
        sys.exit(0)
