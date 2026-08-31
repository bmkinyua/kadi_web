"""
Regression test for SettingsScene's resolution picker.

This used to test the old Prev/Next stepper's separate "Not Recommended"
warning modal (_draw_res_warning) — a pre-existing bug where its
"Continue (Not Recommended)" button was sized to a flat, guessed 240px
but the label renders at 277px even at the 1280x800 baseline, with zero
scaling involved.

That whole Prev/Next + after-the-fact warning modal flow has since been
replaced by a click-to-expand list (_draw_res_dropdown), styled after
startup_picker.py's own resolution picker: every resolution is shown
with its own Recommended/Not Recommended label up front, so there's
nothing left to warn about after the fact — see the comment on
SettingsScene._select_resolution. This file now covers that replacement
instead: every row's label must fit inside its own row, and every row
must stay fully on screen, at every supported resolution.

Run (from the kadi/ directory):  python -m tests.test_settings_res_warning_dialog
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
pygame.display.set_mode((1, 1))

from constants import UI_SCALE_PROFILES
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from scenes import SceneManager, SettingsScene, RESOLUTIONS, RES_LABELS, get_chrome_scale

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def _build_scene(sw, sh):
    screen = pygame.display.set_mode((sw, sh))
    gm = GameManager()
    gm.resolution = (sw, sh)
    assets = AssetLoader()
    assets.init()
    sm = SceneManager(screen, assets)
    sm.gm = gm
    scene = SettingsScene(sm)
    scene.on_enter()
    surf = pygame.Surface((sw, sh))
    scene.draw(surf)  # lays out self._res_dropdown_rect via _flow()
    scene._res_dropdown_open = True
    scene._draw_res_dropdown(surf)  # populates self._res_row_rects
    return scene


def test_dropdown_rows_fit_their_labels_and_screen():
    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        scene = _build_scene(sw, sh)
        check(f"{sw}x{sh}: one row per resolution",
              len(scene._res_row_rects) == len(RESOLUTIONS))
        font_sm = scene.assets.font_scaled('ui_normal', get_chrome_scale(sw, sh))
        for i, r in enumerate(scene._res_row_rects):
            within = (r.left >= 0 and r.right <= sw and r.top >= 0 and r.bottom <= sh)
            check(f"{sw}x{sh}: row {RES_LABELS[i]!r} stays within the screen", within)
            label_w = font_sm.size(RES_LABELS[i] + "  (Not Recommended)")[0]
            check(f"{sw}x{sh}: row {RES_LABELS[i]!r} wide enough for its longest label",
                  r.width >= label_w + 14)


def test_closed_box_reflects_current_selection():
    scene = _build_scene(1280, 800)
    gm = scene.gm
    idx = RESOLUTIONS.index(gm.resolution)
    check("closed box's _res_idx matches gm.resolution", scene._res_idx == idx)


def test_selecting_a_row_applies_immediately_no_separate_confirm_step():
    """Unlike the old modal, there is no 'Continue (Not Recommended)' /
    'Switch to Optimum' step — clicking any row in the list applies that
    resolution right away."""
    scene = _build_scene(1280, 800)
    target_idx = 0 if RESOLUTIONS[0] != scene.gm.resolution else 1
    scene._select_resolution(target_idx)
    check("selecting a row updates _res_idx", scene._res_idx == target_idx)
    check("selecting a row queues the resolution change",
          scene.manager._pending_resolution == RESOLUTIONS[target_idx])


def main():
    print("=== test_settings_res_warning_dialog ===")
    test_dropdown_rows_fit_their_labels_and_screen()
    test_closed_box_reflects_current_selection()
    test_selecting_a_row_applies_immediately_no_separate_confirm_step()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
