"""
Regression test for a real bug report: 2 human players + 1 AI, in
Elimination Mode. One human disconnects early (before anyone has
legitimately finished). The remaining human correctly won, but the
disconnected player was ranked #2 in the standings -- AHEAD of the AI,
who was still actively playing when the round ended. Leaving the
match early must never earn a better placement than a player (human
or AI) who was still at the table when the round actually ended.

Run: SDL_VIDEODRIVER=dummy python -m tests.test_disconnect_ranking
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_manager import GameManager

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def run_reported_scenario():
    print("\n-- 2 humans + 1 AI, elimination mode: one human disconnects early --")
    gm = GameManager()
    gm.new_game([
        {'name': 'Alice', 'is_human': True},
        {'name': 'Bob', 'is_human': True},
        {'name': 'Bot', 'is_human': False},
    ], elimination_mode=True)

    alice, bob, bot = gm.players
    # Bob disconnects right away -- nobody has finished yet.
    gm.force_remove_player(bob)

    check("game continues (2 still active: Alice + Bot)", gm.state.name != 'GAME_OVER')
    check("Bob is marked finished (skipped in rotation) but NOT yet ranked",
          bob.finished and bob not in gm.finish_order)

    # Alice now legitimately empties her hand and finishes the round.
    gm._eliminate_player(alice, {})

    check("round ended", gm.state.name == 'GAME_OVER')
    check("Alice (stayed, actually finished) is the winner", gm.winner is alice)
    check("Alice is ranked 1st", alice.finish_place == 1)
    check("Bot (kept playing) ranks ahead of Bob (who left)",
          bot.finish_place < bob.finish_place)
    check("Bob (who disconnected) is ranked LAST", bob.finish_place == len(gm.finish_order))
    order = [p.name for p in gm.finish_order]
    check(f"final order is Alice, Bot, Bob (got {order})",
          order == ['Alice', 'Bot', 'Bob'])


def run_two_player_standard_mode():
    print("\n-- 2 humans, standard (non-elimination) mode: one disconnects --")
    gm = GameManager()
    gm.new_game([
        {'name': 'Alice', 'is_human': True},
        {'name': 'Bob', 'is_human': True},
    ], elimination_mode=False)
    alice, bob = gm.players
    gm.force_remove_player(bob)

    check("round ends immediately (only 1 human left in a 2-player game)",
          gm.state.name == 'GAME_OVER')
    check("the remaining player wins", gm.winner is alice)
    check("winner is ranked 1st, disconnector ranked last",
          alice.finish_place == 1 and bob.finish_place == 2)


def run_disconnect_after_ai_already_finished():
    print("\n-- AI legitimately finishes FIRST, THEN a human disconnects --")
    gm = GameManager()
    gm.new_game([
        {'name': 'Alice', 'is_human': True},
        {'name': 'Bob', 'is_human': True},
        {'name': 'Bot', 'is_human': False},
    ], elimination_mode=True)
    alice, bob, bot = gm.players
    gm._eliminate_player(bot, {})  # Bot legitimately finishes first, fair and square
    check("game continues after Bot's legitimate finish", gm.state.name != 'GAME_OVER')

    gm.force_remove_player(bob)  # Bob disconnects afterward
    check("round ends (only Alice left)", gm.state.name == 'GAME_OVER')
    check("Bot's EARLIER legitimate finish still ranks ahead of Alice merely surviving",
          bot.finish_place == 1)
    check("Bob (disconnected) is still ranked LAST, behind Alice",
          bob.finish_place == len(gm.finish_order) and alice.finish_place < bob.finish_place)


if __name__ == '__main__':
    run_reported_scenario()
    run_two_player_standard_mode()
    run_disconnect_after_ai_already_finished()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"DISCONNECT RANKING: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("DISCONNECT RANKING: ALL CHECKS PASSED")
        sys.exit(0)
