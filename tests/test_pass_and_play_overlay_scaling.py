"""
Regression test for the SAME class of bug WinScreen had (see
test_winscreen_share_status_visibility.py and
test_winscreen_resolution_scaling.py), found by auditing the rest of
rendering/widgets.py for the same pattern once WinScreen's fix landed:
rendering.widgets.PassAndPlayOverlay (the "Pass the device to <name> —
Make sure no one else can see the screen" interstitial, shown on
EVERY turn transition in local hot-seat multiplayer — far more
frequently than WinScreen, which shows once per game) had a fixed
560x360 panel, a fixed 360x60 button, fixed (non-resolution-scaled)
fonts, and rendered the player's name as a single unwrapped line with
no length limit enforced anywhere in the codebase.

Measured before this fix:
  - A plausible long name ("Nebuchadnezzar Wanjiru Abernathy-Kimathi")
    rendered 756px wide against a fixed 560px-wide panel at ANY
    resolution — overflowing the panel itself (though not always the
    screen, depending on resolution).
  - At 7680x4320 (8K) the fixed panel occupied only ~7.3% x ~8.3% of
    the screen (vs. ~43.8% x ~45.0% at the 1280x800 baseline) — a
    proportionally tiny box in the middle of a huge dark screen, on a
    screen shown constantly during play.

The fix (rendering/widgets.py):
  - PassAndPlayOverlay takes a `scale` param (same convention as
    WinScreen) and a `_s(px)` helper scaling every fixed-pixel
    constant.
  - setup() now wraps the player name via wrap_text() and sizes the
    panel to fit its ACTUAL content (lead text / wrapped name / hint /
    button), clamped so the panel can never exceed the screen bounds
    — instead of a fixed 560x360 regardless of content or resolution.
  - scenes.py's GameplayScene.__init__ builds this overlay's fonts via
    AssetLoader.font_scaled(name, get_chrome_scale(sw, sh)) instead of
    the fixed AssetLoader.font(name), and passes that same scale
    through.

Run (from the kadi/ directory):  python -m tests.test_pass_and_play_overlay_scaling
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from rendering.widgets import PassAndPlayOverlay
from rendering.asset_loader import AssetLoader
from constants import UI_SCALE_PROFILES, get_chrome_scale

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


LONG_NAME = "Nebuchadnezzar Wanjiru Abernathy-Kimathi"

_assets = AssetLoader()
_assets.init()


def _build_overlay(sw, sh, name):
    scale = get_chrome_scale(sw, sh)
    ov = PassAndPlayOverlay(sw, sh,
                             _assets.font_scaled('ui_large', scale),
                             _assets.font_scaled('ui_medium', scale),
                             _assets.font_scaled('ui_small', scale), scale=scale)
    ov.setup(name, on_reveal=lambda: None)
    return ov


def test_long_name_no_overflow_at_any_resolution():
    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        ov = _build_overlay(sw, sh, LONG_NAME)
        surf = pygame.Surface((sw, sh))
        ov.draw(surf)  # must not raise at any supported resolution

        pr = ov._panel.rect
        panel_within = pr.left >= 0 and pr.top >= 0 and pr.right <= sw and pr.bottom <= sh
        check(f"{sw}x{sh}: panel stays fully within the screen", panel_within)

        name_widths = [s.get_width() for s in ov._name_surfs]
        check(f"{sw}x{sh}: every name line fits inside the panel",
              all(w <= pr.width for w in name_widths))
        check(f"{sw}x{sh}: every name line stays within the screen horizontally",
              all(0 <= x and x + w <= sw for (x, y), w in zip(ov._name_positions, name_widths)))


def test_short_name_stays_baseline_sized():
    """A normal short name at the 1280x800 baseline should render
    essentially identically to the original fixed 560x360 panel — this
    fix shouldn't change the common case, only fix the edge cases."""
    ov = _build_overlay(1280, 800, "Alice")
    pr = ov._panel.rect
    check("baseline panel width stays close to the original fixed 560px",
          555 <= pr.width <= 570)
    check("baseline panel height stays close to the original fixed 360px",
          355 <= pr.height <= 370)


def test_panel_far_less_tiny_at_8k():
    """The proportional-tininess half of the bug — confirms the panel
    actually grows meaningfully at high resolutions instead of staying
    frozen at its baseline pixel size."""
    sw, sh = 7680, 4320
    ov = _build_overlay(sw, sh, "Bob")
    pr = ov._panel.rect
    old_fixed_pct_w = 560 / sw * 100
    new_pct_w = pr.width / sw * 100
    check(f"8K panel width is now at least 2.5x its old proportional size "
          f"(was {old_fixed_pct_w:.1f}%, now {new_pct_w:.1f}%)",
          new_pct_w > old_fixed_pct_w * 2.5)


def test_reveal_button_stays_clickable_and_matches_drawn_position():
    """handle_event() and draw() must agree on where the button is —
    setup() computes the button's rect once, draw() only blits it, so
    there's no per-frame recompute that could desync the two."""
    ov = _build_overlay(1280, 800, "Alice")
    surf = pygame.Surface((1280, 800))
    ov.draw(surf)
    rect_before = pygame.Rect(ov.reveal_btn.rect)
    ov.draw(surf)  # a second draw() call must not move anything
    check("reveal button rect is stable across repeated draw() calls",
          ov.reveal_btn.rect == rect_before)
    check("reveal button stays within the screen",
          ov.reveal_btn.rect.left >= 0 and ov.reveal_btn.rect.right <= 1280
          and ov.reveal_btn.rect.top >= 0 and ov.reveal_btn.rect.bottom <= 800)


def main():
    print("=== test_pass_and_play_overlay_scaling ===")
    test_long_name_no_overflow_at_any_resolution()
    test_short_name_stays_baseline_sized()
    test_panel_far_less_tiny_at_8k()
    test_reveal_button_stays_clickable_and_matches_drawn_position()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
