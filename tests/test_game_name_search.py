"""
Feature test: hosts can give their Internet-hosted game a friendly
name ("Friday Night KADI") so a friend can find it in a long browse
list instead of scanning opaque game ids, and the browse list can be
filtered by that name (or the host's own name).

Covers:
  - a named game shows its name in the browse list and lobby_state
  - an unnamed game falls back to "<host>'s game", same as before
  - the name survives to the waiting-room (lobby_state's game_name)
  - client-side search filtering (scenes.InternetLobbyScene._filtered_games)
    matches by game name OR host name, case-insensitively

Run: SDL_VIDEODRIVER=dummy python -m tests.test_game_name_search
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.client import LANClient
from server.kadi_server import KadiServer

PORT = 52107
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
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def run_server_side():
    print("\n-- server: named + unnamed games in the browse list --")
    server = KadiServer(port=PORT)
    server.start()
    try:
        named = LANClient()
        named.connect('127.0.0.1', PORT, name='Alice')
        named_box = Inbox(named)
        server.tick(0.02)
        named.send({'type': 'create_game',
                   'settings': {'elimination_mode': False, 'ai_count': 0,
                               'game_name': "Friday Night KADI"}})
        ok = wait_until(server, lambda: named_box.has('welcome'))
        check("named game created", ok)
        named_game_id = named_box.get('welcome')['game_id']

        unnamed = LANClient()
        unnamed.connect('127.0.0.1', PORT, name='Bob')
        unnamed_box = Inbox(unnamed)
        server.tick(0.02)
        unnamed.send({'type': 'create_game',
                     'settings': {'elimination_mode': False, 'ai_count': 0}})
        ok = wait_until(server, lambda: unnamed_box.has('welcome'))
        check("unnamed game created", ok)
        unnamed_game_id = unnamed_box.get('welcome')['game_id']

        room_named = server.lobby.get(named_game_id)
        room_unnamed = server.lobby.get(unnamed_game_id)
        check("named room stores the exact name given",
              room_named.game_name == "Friday Night KADI")
        check("named room's display_name() is the custom name",
              room_named.display_name() == "Friday Night KADI")
        check("unnamed room's game_name is empty",
              room_unnamed.game_name == "")
        check("unnamed room's display_name() falls back to '<host>'s game'",
              room_unnamed.display_name() == "Bob's game")

        summary = server.lobby.open_games_summary()
        named_entry = next(g for g in summary if g['game_id'] == named_game_id)
        unnamed_entry = next(g for g in summary if g['game_id'] == unnamed_game_id)
        check("browse-list entry for the named game carries game_name",
              named_entry['game_name'] == "Friday Night KADI")
        check("browse-list entry for the unnamed game has an empty game_name "
             "(client decides the '<host>'s game' fallback text, not the server)",
              unnamed_entry['game_name'] == "")

        # Oversized / malicious client input shouldn't blow past the cap
        # even if InternetLobbyScene's own 40-char client-side cap were
        # somehow bypassed.
        third = LANClient()
        third.connect('127.0.0.1', PORT, name='Carol')
        third_box = Inbox(third)
        server.tick(0.02)
        third.send({'type': 'create_game',
                   'settings': {'elimination_mode': False, 'ai_count': 0,
                               'game_name': "X" * 500}})
        ok = wait_until(server, lambda: third_box.has('welcome'))
        room3 = server.lobby.get(third_box.get('welcome')['game_id']) if ok else None
        check("server caps an oversized game_name defensively, not just trusting "
             "the client's own cap",
              room3 is not None and len(room3.game_name) <= 40)

        named.close()
        unnamed.close()
        third.close()
    finally:
        server.stop()


def run_client_side_filter():
    print("\n-- client: _filtered_games() search behavior --")
    import pygame
    pygame.init()
    pygame.font.init()
    from scenes import InternetLobbyScene

    # _filtered_games only reads self._games / self._search_text, so a
    # bare, un-on_enter'd instance is enough to exercise it in isolation.
    scene = InternetLobbyScene.__new__(InternetLobbyScene)
    scene._games = [
        {'game_id': 'g1', 'game_name': "Friday Night KADI", 'host_name': "Alice"},
        {'game_id': 'g2', 'game_name': "", 'host_name': "Bob"},
        {'game_id': 'g3', 'game_name': "Casual Sunday Game", 'host_name': "Carol"},
    ]

    scene._search_text = ""
    check("empty search returns every game, untouched",
          scene._filtered_games() == scene._games)

    scene._search_text = "friday"
    check("search matches game_name case-insensitively",
          [g['game_id'] for g in scene._filtered_games()] == ['g1'])

    scene._search_text = "bob"
    check("search also matches host_name for unnamed games",
          [g['game_id'] for g in scene._filtered_games()] == ['g2'])

    scene._search_text = "  CASUAL  "
    check("search is trimmed and case-insensitive",
          [g['game_id'] for g in scene._filtered_games()] == ['g3'])

    scene._search_text = "nonexistent game xyz"
    check("no matches returns an empty list, not an error",
          scene._filtered_games() == [])


if __name__ == '__main__':
    run_server_side()
    run_client_side_filter()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"GAME NAME / SEARCH: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("GAME NAME / SEARCH: ALL CHECKS PASSED")
        sys.exit(0)
