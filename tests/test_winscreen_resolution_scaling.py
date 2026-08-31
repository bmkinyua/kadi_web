"""
Regression test for a real (quantified, not hypothetical) readability
gap: WinScreen's fonts and button/layout geometry were ALL fixed
pixel values regardless of resolution — completely unlike the rest of
this app's UI (BoardRenderer's gameplay table, the Settings/Rules
panel), which already scales up via constants.UI_SCALE_PROFILES'
font_scale/button_scale/card_scale for exactly this reason.

Measured before this fix: WinScreen's 22px text was 2.75% of screen
height at the 1280x800 baseline, but only 0.51% of screen height at
7680x4320 (8K) — 5.4x proportionally smaller, well below what the
game's own scaling already uses at that resolution (font_scale=3.0
there). Practically illegible on a large physical 8K display.

The fix:
  - rendering/widgets.py's WinScreen now takes a `scale` parameter
    (matching UI_SCALE_PROFILES' button_scale) and multiplies EVERY
    fixed-pixel gap/button-size constant in setup_buttons()/draw() by
    it via a small self._s(px) helper, instead of leaving them frozen
    at their 1280x800-baseline pixel values.
  - scenes.py's _show_win_screen now builds WinScreen's fonts via
    AssetLoader.font_scaled(name, font_scale) instead of the fixed
    AssetLoader.font(name) — same convention already used elsewhere —
    and passes button_scale through to WinScreen's new scale param.

Both pieces have to move together: scaling only the fonts (without
the button/layout geometry) would just trade the old "too small to
read" bug for a new "scaled-up text overflows its own still-fixed-
size button" bug. This test checks both.

Run (from the kadi/ directory):  python -m tests.test_winscreen_resolution_scaling
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

from rendering.widgets import WinScreen, wrap_text
from rendering.asset_loader import AssetLoader
from constants import UI_SCALE_PROFILES, get_ui_scale

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


LONG_STATUS = (
    'Saved to /home/someuser/.local/share/KADI/KADI Shares/'
    'win_card_alice_20260819_161533.png (its folder just opened) '
    '\u2014 drag it into the WhatsApp window that opened alongside it.'
)

_assets = AssetLoader()
_assets.init()


def _build_scaled_winscreen(sw, sh, standings=None):
    prof = get_ui_scale(sw, sh)
    f_large = _assets.font_scaled('kadi_banner', prof['font_scale'])
    f_med = _assets.font_scaled('ui_large', prof['font_scale'])
    f_small = _assets.font_scaled('ui_medium', prof['font_scale'])
    ws = WinScreen('Alice', sw, sh, f_large, f_med, f_small,
                    standings=standings, scale=prof['button_scale'])
    ws.setup_buttons(f_small, on_play_again=lambda: None, on_menu=lambda: None,
                      on_share=lambda k: None)
    ws.share_expanded = True
    ws.share_status = LONG_STATUS
    return ws, prof


def test_text_size_scales_up_with_resolution():
    """The core readability claim: font_small's actual rendered height
    should track font_scale — bigger at 4K/8K than at the 1280x800
    baseline, not frozen at 22px everywhere."""
    baseline_h = _assets.font_scaled('ui_medium', 1.0).get_height()
    h_4k = _assets.font_scaled('ui_medium', get_ui_scale(3840, 2160)['font_scale']).get_height()
    h_8k = _assets.font_scaled('ui_medium', get_ui_scale(7680, 4320)['font_scale']).get_height()
    check("4K text is meaningfully larger in pixels than baseline",
          h_4k > baseline_h * 1.5)
    check("8K text is meaningfully larger in pixels than 4K",
          h_8k > h_4k)

    # The proportional (% of screen height) gap that motivated this
    # fix should now be much narrower across the resolution range,
    # not the old ~5.4x swing between baseline and 8K.
    pct_baseline = baseline_h / 800 * 100
    pct_8k = h_8k / 4320 * 100
    ratio = pct_baseline / pct_8k
    check(f"proportional size swing baseline-vs-8K is well under the old ~5.4x (actual: {ratio:.2f}x)",
          ratio < 2.5)


def test_no_overflow_at_any_supported_resolution():
    """Text must never outgrow its own (also-scaled) button — this is
    the specific new failure mode a font-only fix would introduce."""
    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        ws, prof = _build_scaled_winscreen(sw, sh, standings=[f"{i}. Player{i}" for i in range(1, 9)])
        surf = pygame.Surface((sw, sh))
        ws.draw(surf)  # must not raise at any supported resolution

        f_small = ws.font_small
        for label, btn in (("Play Again", ws.play_again_btn), ("Main Menu", ws.menu_btn),
                            ("Share", ws.share_btn)):
            label_w = f_small.size(btn.label if hasattr(btn, "label") else label)[0]
            check(f"{sw}x{sh}: '{label}' button text fits its own scaled box",
                  label_w <= btn.rect.width)

        margin = ws._s(10)
        max_text_w = min(ws.sw - ws._s(80), ws._s(700))
        lines = wrap_text(f_small, LONG_STATUS, max_text_w)
        line_h = f_small.get_height() + 2
        block_h = line_h * len(lines)
        status_y = (max(b.rect.bottom for _k, b in ws._share_platform_buttons) + ws._s(8)
                    if ws._share_platform_buttons else ws.share_btn.rect.bottom + ws._s(8))
        if status_y + block_h > ws.sh - margin:
            status_y = max(margin, ws.sh - margin - block_h)
        check(f"{sw}x{sh}: scaled share_status still stays fully on-screen",
              status_y >= 0 and status_y + block_h <= ws.sh)


def test_default_scale_matches_old_fixed_behavior():
    """scale defaults to 1.0 for any caller that doesn't pass one —
    the 1280x800 baseline should render pixel-identical to how the
    unscaled version always worked, so nothing regresses for the one
    resolution every other resolution's profile is defined relative
    to."""
    prof = get_ui_scale(1280, 800)
    check("1280x800's button_scale is exactly 1.0 (the baseline)",
          prof['button_scale'] == 1.0)
    ws_default = WinScreen('Alice', 1280, 800,
                            _assets.font('kadi_banner'), _assets.font('ui_large'),
                            _assets.font('ui_medium'))
    check("WinScreen with no scale arg defaults to scale=1.0",
          ws_default.scale == 1.0)
    check("_s(200) with default scale returns exactly 200 (unchanged)",
          ws_default._s(200) == 200)


def main():
    print("=== test_winscreen_resolution_scaling ===")
    test_text_size_scales_up_with_resolution()
    test_no_overflow_at_any_supported_resolution()
    test_default_scale_matches_old_fixed_behavior()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
