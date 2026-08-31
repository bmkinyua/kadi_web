"""
Field-reported UX gap: in Local Multiplayer (hot-seat), only seat 0
("Player 1") could be given a custom name before the game started —
every other seat was hardcoded to "Player 2", "Player 3", etc. with no
way to enter names, so players didn't know who was who at the table
until they saw whose turn it was.

This test drives the real ModeSelectScene (headless, no display
needed) through: picking Local Multiplayer, setting an opponent count,
typing custom names into the new per-opponent fields, changing the
opponent count again (layout must not break), and finally starting the
game — asserting the real names make it into GameManager's player
roster, with the existing disambiguate_names() collision guard still
applied.

Run (from the kadi/ directory):  python -m tests.test_local_multiplayer_naming
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from scenes import SceneManager, ModeSelectScene, GameplayScene
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def make_scene():
    pygame.init()
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    gm = GameManager()
    sm = SceneManager(screen, assets)
    sm.gm = gm
    sm.singleplayer_gm = gm
    sm.board = BoardRenderer(assets)
    sm.anim = AnimationManager()
    sm.make_screen = lambda *a, **kw: screen
    scene = ModeSelectScene(sm)
    sm.register('gameplay', GameplayScene(sm))
    return sm, scene


def run_custom_names_reach_roster():
    print("\n-- Custom local-player names reach the real game roster --")
    sm, scene = make_scene()
    scene.on_enter(vs_ai=False)
    scene._n_opponents = 3
    scene._relayout()

    check("a name field exists for every configured opponent",
          len(scene._local_name_rects) == 3)

    scene._local_names[0] = "Penny"
    scene._local_names[1] = "Amos"
    scene._local_names[2] = "  Kip  "  # whitespace should be trimmed

    scene._player_name = "BMK"
    scene._start_game()

    names = [p.name for p in sm.gm.players]
    check("seat 0 keeps the custom Player-1 name", names[0] == "BMK")
    check("seat 1 got its typed name", names[1] == "Penny")
    check("seat 2 got its typed name", names[2] == "Amos")
    check("seat 3's name was trimmed of surrounding whitespace", names[3] == "Kip")


def run_blank_name_falls_back():
    print("\n-- A blank opponent name field falls back to Player N, not empty --")
    sm, scene = make_scene()
    scene.on_enter(vs_ai=False)
    scene._n_opponents = 2
    scene._relayout()
    scene._local_names[0] = ""       # left blank
    scene._local_names[1] = "   "    # whitespace-only
    scene._start_game()

    names = [p.name for p in sm.gm.players]
    check("blank field falls back to a default, not an empty name",
          names[1] == "Player 2")
    check("whitespace-only field also falls back to a default",
          names[2] == "Player 3")


def run_duplicate_names_disambiguated():
    print("\n-- Duplicate local-player names get disambiguated, same as LAN/Internet --")
    sm, scene = make_scene()
    scene.on_enter(vs_ai=False)
    scene._n_opponents = 2
    scene._relayout()
    scene._player_name = "Sam"
    scene._local_names[0] = "Sam"
    scene._local_names[1] = "Sam"
    scene._start_game()

    names = [p.name for p in sm.gm.players]
    check("collision guard renamed the duplicates in seat order",
          names == ["Sam 1", "Sam 2", "Sam 3"])


def run_opponent_count_change_reflows_layout():
    print("\n-- Changing opponent count reflows the name-field layout without error --")
    sm, scene = make_scene()
    scene.on_enter(vs_ai=False)
    scene._n_opponents = 1
    scene._relayout()
    check("starts with exactly 1 name field", len(scene._local_name_rects) == 1)

    scene._local_names[0] = "Penny"
    scene._n_opponents = 5
    scene._relayout()
    check("growing opponent count grows the field list", len(scene._local_name_rects) == 5)
    check("a previously-typed name survives a re-layout",
          scene._local_names[0] == "Penny")

    scene._n_opponents = 2
    scene._relayout()
    check("shrinking opponent count shrinks the field list", len(scene._local_name_rects) == 2)

    # Drawing after every reflow should never raise.
    surf = pygame.Surface((1280, 800))
    try:
        scene.draw(surf)
        check("scene draws cleanly after multiple re-layouts", True)
    except Exception as e:
        check(f"scene draws cleanly after multiple re-layouts (raised {e!r})", False)


def run_vs_ai_mode_unaffected():
    print("\n-- vs-AI mode still has no local-player name fields (unchanged behavior) --")
    sm, scene = make_scene()
    scene.on_enter(vs_ai=True)
    check("no per-opponent name fields in vs-AI mode",
          len(scene._local_name_rects) == 0)

    scene._player_name = "BMK"
    scene._n_opponents = 2
    scene._start_game()
    names = [p.name for p in sm.gm.players]
    check("AI opponents still get their AI names, not player names",
          names[1:] != ["Player 2", "Player 3"] and names[0] == "BMK")


if __name__ == '__main__':
    run_custom_names_reach_roster()
    run_blank_name_falls_back()
    run_duplicate_names_disambiguated()
    run_opponent_count_change_reflows_layout()
    run_vs_ai_mode_unaffected()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"LOCAL MULTIPLAYER NAMING: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("LOCAL MULTIPLAYER NAMING: ALL CHECKS PASSED")
        sys.exit(0)
