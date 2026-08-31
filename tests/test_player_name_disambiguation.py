"""
Regression test for a field-reported UX gap: two human players who
both leave the name field at its default ("Player") were completely
indistinguishable everywhere in a match — the roster, the turn
indicator ("Player's turn" on both screens at once, per the field
screenshots), the settings panel. network.player_names.disambiguate_names
now renames any collision to "Player 1"/"Player 2" (etc, in seat order)
right where each roster is finally assembled — server/game_room.py for
Internet Multiplayer, network/host_game.py for LAN.

Run: SDL_VIDEODRIVER=dummy python -m tests.test_player_name_disambiguation
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.player_names import disambiguate_names

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def run_unit_tests():
    print("\n-- disambiguate_names() unit behavior --")
    check("no collisions -> names returned completely untouched",
          disambiguate_names(["Alice", "Bob", "Carol"]) == ["Alice", "Bob", "Carol"])
    check("two identical defaults -> numbered in seat order",
          disambiguate_names(["Player", "Player"]) == ["Player 1", "Player 2"])
    check("three identical -> numbered 1/2/3",
          disambiguate_names(["Player", "Player", "Player"])
          == ["Player 1", "Player 2", "Player 3"])
    check("mixed: one collision among otherwise-unique names",
          disambiguate_names(["Alice", "Player", "Player"])
          == ["Alice", "Player 1", "Player 2"])
    check("case-sensitive: 'Player' and 'player' are NOT considered a collision",
          disambiguate_names(["Player", "player"]) == ["Player", "player"])
    check("order and length are preserved",
          len(disambiguate_names(["Player"] * 5)) == 5)
    check("empty list handled without error", disambiguate_names([]) == [])


def run_internet_integration():
    print("\n-- Internet Multiplayer: two default-named humans get disambiguated --")
    from server.game_room import GameRoom
    room = GameRoom(game_id="test_game", host_conn_id=1, host_name="Player")
    room.member_names[2] = "Player"  # joiner ALSO left the default unchanged
    err = room.start_game(extra_ai_configs=[])
    check("room started successfully despite the name collision", err is None)
    names = [p.name for p in room.gm.players] if err is None else []
    check("server's real GameManager players got disambiguated names",
          names == ["Player 1", "Player 2"])


def run_lan_integration():
    print("\n-- LAN Multiplayer: two default-named humans get disambiguated --")
    from network.host_game import HostGame

    class _FakeNet:
        def broadcast(self, msg):
            pass

        def player_ids(self):
            return []

        def send_to(self, pid, msg):
            pass

    hg = HostGame.__new__(HostGame)  # bypass __init__'s real LANHost/socket setup
    from core.game_manager import GameManager
    hg.gm = GameManager()
    hg.net = _FakeNet()
    hg.player_names = {0: "Host", 1: "Host"}  # host AND joiner both left default
    hg._pending_events = []
    hg.started = False
    err = hg.start_game(elimination_mode=False, elimination_ai_only_continue=True,
                        extra_ai_configs=[])
    names = [p.name for p in hg.gm.players]
    check("LAN's real GameManager players got disambiguated names",
          names == ["Host 1", "Host 2"])


if __name__ == '__main__':
    run_unit_tests()
    run_internet_integration()
    run_lan_integration()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"PLAYER NAME DISAMBIGUATION: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PLAYER NAME DISAMBIGUATION: ALL CHECKS PASSED")
        sys.exit(0)
