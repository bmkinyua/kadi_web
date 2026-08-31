"""
Regression test for GameplayScene._draw_kadi_mini (the post-play
chess-clock panel next to the human hand).

Found from a real screenshot (waitingBoxNotUseful.png): this panel
used to draw a translucent box with a bare "Waiting..." label — no
name, no button — during ordinary play, any time no post-play
decision was open for anyone. It conveyed nothing (the current
player's turn is already shown elsewhere, via the "X's turn" banner)
and just sat there.

The fix: _draw_kadi_mini now returns immediately, drawing nothing at
all, when there's no post-play decision open for me AND nobody else's
is open either. The two cases that ARE informative are unaffected:
  - "Waiting on <name>..." when someone else's post-play window is
    open (worth knowing, since it explains a pause in a multiplayer
    game).
  - The full active panel (KADI/Proceed/Undo buttons) when it's MY
    post-play decision.

Run (from the kadi/ directory):  python -m tests.test_kadi_mini_panel_visibility
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
pygame.init()
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
screen = pygame.display.set_mode((1024, 640))

from constants import AIDifficulty
from core.game_manager import GameManager, GameState
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import SceneManager, GameplayScene
from models.player import HumanPlayer, AIPlayer

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def _make_scene():
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    gm = GameManager()
    gm.resolution = (1024, 640)
    gm.players = [HumanPlayer("Player 1", 0), AIPlayer("Bot", 1, AIDifficulty.MEDIUM)]
    board.setup_layout(len(gm.players), *gm.resolution)

    sm = SceneManager(screen, assets)
    sm.gm = gm
    sm.singleplayer_gm = gm
    sm.board = board
    sm.anim = anim
    sm.make_screen = lambda *a, **kw: screen
    scene = GameplayScene(sm)
    scene.on_enter()
    return scene, gm


def _drew_anything(scene, surf):
    """A blank (all-zero-alpha) surface before and after tells us
    whether _draw_kadi_mini actually put anything on screen."""
    before = pygame.image.tostring(surf, 'RGBA')
    scene._draw_kadi_mini(surf)
    after = pygame.image.tostring(surf, 'RGBA')
    return before != after


def test_idle_draws_nothing():
    """Nobody is in a post-play decision — the common, most-of-the-time
    case — so the panel should draw nothing at all."""
    scene, gm = _make_scene()
    gm.state = GameState.PLAYING
    gm._post_play_player = None
    surf = pygame.Surface((1024, 640), pygame.SRCALPHA)
    check("idle: _draw_kadi_mini draws nothing",
          not _drew_anything(scene, surf))


def test_waiting_on_other_player_still_draws():
    """Someone else's post-play window is open — still worth showing,
    since it's genuinely informative in a multiplayer game."""
    scene, gm = _make_scene()
    gm.state = GameState.POST_PLAY
    gm._post_play_player = gm.players[1]
    surf = pygame.Surface((1024, 640), pygame.SRCALPHA)
    check("waiting on another player: _draw_kadi_mini still draws something",
          _drew_anything(scene, surf))


def test_my_own_post_play_still_draws_full_panel():
    """It's my own post-play decision — the full active panel
    (KADI/Proceed/Undo) must still render and its buttons must still
    get real click rects."""
    scene, gm = _make_scene()
    gm.state = GameState.POST_PLAY
    gm._post_play_player = gm.players[0]
    gm._post_play_can_kadi = False
    surf = pygame.Surface((1024, 640), pygame.SRCALPHA)
    check("my own post-play: _draw_kadi_mini still draws something",
          _drew_anything(scene, surf))
    check("my own post-play: Proceed button gets a real (non-zero) click rect",
          scene._btn_kadi_no.rect.width > 0 and scene._btn_kadi_no.rect.height > 0)


def main():
    print("=== test_kadi_mini_panel_visibility ===")
    test_idle_draws_nothing()
    test_waiting_on_other_player_still_draws()
    test_my_own_post_play_still_draws_full_panel()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
