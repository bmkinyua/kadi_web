"""
Regression test for a gap found while investigating web-side Local
Multiplayer/GameConfigScene parity: server/game_room.py's start_game()
previously hardcoded elimination_ai_only_continue=True on every call
to GameManager.new_game(), ignoring whatever a client actually sent
in create_game's settings -- even though new_game() itself
(core/game_manager.py) has accepted this parameter all along, and
settings_summary_rows() unconditionally showed "AI continues alone:
ON" regardless of the real value. A client that wanted "End the game"
(the PC's own second choice for this toggle, scenes.py's
ModeSelectScene) had no way to actually get that behavior from a web
room. Both are fixed together here: start_game() now reads
elimination_ai_only_continue from self.settings (default True,
matching the prior hardcoded behavior and the PC's own default, so
this is backward compatible with every existing client that never
set the key), and settings_summary_rows() reflects the real value.

Run: SDL_VIDEODRIVER=dummy python -m tests.test_game_room_elimination_ai_only_continue
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import AIDifficulty
from server.game_room import GameRoom

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def _ai_config(name="Bot"):
    return {'name': name, 'is_human': False, 'difficulty': AIDifficulty.MEDIUM}


def run_default_stays_true():
    print("\n-- Omitting the key entirely preserves the old hardcoded True --")
    room = GameRoom('g1', 100, 'Alice', {'elimination_mode': True})
    err = room.start_game(extra_ai_configs=[_ai_config()])
    check("start_game succeeded", err is None)
    check("elimination_ai_only_continue defaults True on GameManager",
          room.gm.elimination_ai_only_continue is True)
    rows = dict(room.settings_summary_rows())
    check("settings_summary_rows shows ON by default",
          rows.get("  AI continues alone") == "ON")


def run_explicit_false_is_honored():
    print("\n-- Explicit elimination_ai_only_continue=False is honored, not silently forced True --")
    room = GameRoom('g2', 101, 'Bob',
                    {'elimination_mode': True, 'elimination_ai_only_continue': False})
    err = room.start_game(extra_ai_configs=[_ai_config()])
    check("start_game succeeded", err is None)
    check("elimination_ai_only_continue is actually False on GameManager",
          room.gm.elimination_ai_only_continue is False)
    rows = dict(room.settings_summary_rows())
    check("settings_summary_rows reflects OFF, not the old hardcoded ON",
          rows.get("  AI continues alone") == "OFF")


def run_explicit_true_still_works():
    print("\n-- Explicit elimination_ai_only_continue=True still works --")
    room = GameRoom('g3', 102, 'Carol',
                    {'elimination_mode': True, 'elimination_ai_only_continue': True})
    err = room.start_game(extra_ai_configs=[_ai_config()])
    check("start_game succeeded", err is None)
    check("elimination_ai_only_continue is True on GameManager",
          room.gm.elimination_ai_only_continue is True)


def run_non_elimination_room_has_no_row():
    print("\n-- Elimination Mode off: no 'AI continues alone' row at all --")
    room = GameRoom('g4', 103, 'Dan', {'elimination_mode': False})
    rows = dict(room.settings_summary_rows())
    check("no 'AI continues alone' row when Elimination Mode is off",
          "  AI continues alone" not in rows)


if __name__ == '__main__':
    run_default_stays_true()
    run_explicit_false_is_honored()
    run_explicit_true_still_works()
    run_non_elimination_room_has_no_row()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"ELIMINATION AI-ONLY-CONTINUE: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ELIMINATION AI-ONLY-CONTINUE: ALL CHECKS PASSED")
        sys.exit(0)
