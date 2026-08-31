"""
Regression test for a reported bug: the chat toggle button used to sit
at the very bottom-left corner of the screen, directly on top of two
other HUD elements that live in that same corner -- the
"Clockwise/Anti-clockwise" direction indicator and the AI-speed badge
(see scenes.GameplayScene._draw_hud / _draw_game_speed_badge). Since
GameplayScene draws those AFTER the chat panel, they painted over it,
making the chat button invisible (and, worse, un-clickable) for anyone
whose exact hover/expanded state happened to fully cover it.

NOTE: chat has since been refactored out of a standalone
rendering.widgets.ChatPanel class -- it's now built directly on
GameplayScene (self._btn_chat_toggle, self._chat_panel_rect,
self._chat_input_rect, etc; see scenes.py's _build_buttons /
_draw_chat), anchored off the real (scaled) Pause button rect rather
than a hardcoded bottom-left position. That relocation is itself what
fixed the original bug -- the toggle button and panel both now live in
the TOP-left cluster, not the bottom-left corner. This test was
rewritten to build a real GameplayScene (not a removed standalone
widget) and check the current, real invariants:
  - the chat toggle button never collides with Menu/Pause (its actual
    neighbors now)
  - the chat toggle button stays fully on-screen
  - the chat panel (when open) never collides with the bottom-left HUD
    (direction indicator / AI-speed badge) -- the original failure mode,
    now checked against the panel's real current position instead of a
    hand-maintained shadow copy of removed code

Run (from the kadi/ directory):  python -m tests.test_chat_button_layout
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from constants import AIDifficulty
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import SceneManager, GameplayScene, RESOLUTIONS

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def bottom_left_hud_rects(sw: int, sh: int):
    """Reproduces the geometry GameplayScene._draw_hud /
    _draw_game_speed_badge actually compute for the direction
    indicator and the AI-speed badge (collapsed and expanded), without
    needing a full draw() call. Kept in sync by hand; if either of
    those methods' layout constants ever change, update the matching
    numbers here too."""
    ds_h = 18  # approx font_xs glyph height
    direction_rect = pygame.Rect(10, sh - ds_h - 34, 130, ds_h + 6)

    speed_h = 20 + 12  # font_sm text height + padding, collapsed badge
    bottom_offset = 60
    speed_collapsed = pygame.Rect(14, sh - speed_h - bottom_offset, 130, speed_h)

    btn_h, pad_y = 26, 7  # expanded badge's [-] speed [+] control row
    speed_expanded = pygame.Rect(14, sh - (btn_h + pad_y * 2) - bottom_offset,
                                 220, btn_h + pad_y * 2)
    return direction_rect, speed_collapsed, speed_expanded


def screen_contains(sw, sh, rect):
    return pygame.Rect(0, 0, sw, sh).contains(rect)


def make_gameplay_scene(sw, sh, assets, board, anim):
    gm = GameManager()
    gm.resolution = (sw, sh)
    screen = pygame.Surface((sw, sh))
    sm = SceneManager(screen, assets)
    sm.gm = gm
    sm.singleplayer_gm = gm
    sm.board = board
    sm.anim = anim
    sm.make_screen = lambda *a, **kw: screen
    scene = GameplayScene(sm)
    sm.register('gameplay', scene)
    player_configs = [
        {'name': 'Alice', 'is_human': True, 'difficulty': None},
        {'name': 'Bot', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
    ]
    sm._current = scene
    sm._current_name = 'gameplay'
    scene.on_enter(player_configs=player_configs)
    return scene


def run():
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.display.set_mode((1, 1))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    for sw, sh in RESOLUTIONS:
        scene = make_gameplay_scene(sw, sh, assets, board, anim)
        toggle = scene._btn_chat_toggle.rect
        panel = scene._chat_panel_rect
        menu_rect = scene._btn_menu.rect
        pause_rect = scene._btn_pause.rect
        direction_rect, speed_collapsed, speed_expanded = bottom_left_hud_rects(sw, sh)

        check(f"[{sw}x{sh}] chat toggle clear of the Menu button",
              not toggle.colliderect(menu_rect))
        check(f"[{sw}x{sh}] chat toggle clear of the Pause button",
              not toggle.colliderect(pause_rect))
        check(f"[{sw}x{sh}] chat toggle stays fully on-screen",
              screen_contains(sw, sh, toggle))
        check(f"[{sw}x{sh}] chat panel (when open) clear of the direction indicator",
              not panel.colliderect(direction_rect))
        check(f"[{sw}x{sh}] chat panel (when open) clear of the collapsed AI-speed badge",
              not panel.colliderect(speed_collapsed))
        check(f"[{sw}x{sh}] chat panel (when open) clear of the expanded AI-speed badge",
              not panel.colliderect(speed_expanded))

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"CHAT BUTTON LAYOUT: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("CHAT BUTTON LAYOUT: ALL CHECKS PASSED")


if __name__ == '__main__':
    run()
