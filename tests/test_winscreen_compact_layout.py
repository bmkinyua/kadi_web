"""
Regression test for WinScreen's "compact" layout shrink
(self._compact / self._cs(), rendering/widgets.py).

Found from a real screenshot: a 4-player Elimination Mode win, viewed
windowed at 1024x640, with the Share row expanded. The last
share-platform button already ended only ~40px above the bottom edge
of the screen — before the "Saved <file> — its folder just opened —
..." status message was even added below it. WinScreen.draw()'s
existing wrap-wider-then-accept-trailing-off-bottom fallback (see
test_winscreen_share_status_visibility.py) could keep the message from
overlapping the buttons above it, but there simply wasn't room left on
screen for the message at all — shortening the message text alone
(see scenes.py's _save_and_share_card, which now shows just the
filename instead of the full absolute path) didn't fully close the
gap either; the stack of buttons/rows above the message was itself too
tall for the space actually available on a short screen.

The fix: WinScreen.setup_buttons() now estimates, up front, whether
the full stack (standings block, Play Again/Main Menu row, Share
button, every platform row, plus room for a status message) fits in
the screen height available below the name/trophy block. If not, it
computes self._compact (a shrink factor, floored at 0.45) and applies
it — via self._cs(), a compact-aware version of self._s() — ONLY to
the fixed vertical GAPS between those blocks, never to button sizes or
fonts, so touch targets and text stay legible while reclaiming the
extra room. draw()'s standings loop uses the same self._cs() so it
can't drift out of sync with what setup_buttons() actually laid out.

This only ever engages when there ARE standings AND Share is offered
— an ordinary single-winner game (no standings) is unaffected, and so
is a short status message that already fits.

Run (from the kadi/ directory):  python -m tests.test_winscreen_compact_layout
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

from constants import UI_SCALE_PROFILES, get_ui_scale, MAX_PLAYERS
from rendering.asset_loader import AssetLoader
from rendering.widgets import WinScreen

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def _build_and_draw(sw, sh, winner_name, standings, status, assets=None):
    assets = assets or AssetLoader()
    us = get_ui_scale(sw, sh)
    ws = WinScreen(winner_name, sw, sh,
                    assets.font_scaled('kadi_banner', us['font_scale']),
                    assets.font_scaled('ui_large', us['font_scale']),
                    assets.font_scaled('ui_medium', us['font_scale']),
                    standings=standings,
                    scale=us['button_scale'])
    ws.setup_buttons(assets.font_scaled('ui_medium', us['font_scale']),
                      on_play_again=lambda: None, on_menu=lambda: None,
                      on_share=lambda k: None)
    ws.share_expanded = True
    ws.share_status = status
    surf = pygame.Surface((sw, sh))
    ws.draw(surf)
    return ws


def test_real_reported_scenario_fits_at_every_resolution():
    """The exact combination from the real screenshot: 4-player
    Elimination Mode standings, winner 'Trickster', Share expanded
    with a WhatsApp status message, at every resolution the Settings
    screen actually offers — not just the one it was first spotted
    at."""
    assets = AssetLoader()
    assets.init()
    status = ("Saved kadi_win_Trickster_20260829_104010.png \u2014 its folder "
              "just opened \u2014 drag it into the WhatsApp window that "
              "opened alongside it.")
    standings = ['1. Trickster', '2. Kadi-Bot', '3. Player 1 (You)', '4. Smart AI (last)']

    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        ws = _build_and_draw(sw, sh, "Trickster", standings, status, assets)
        r = ws._last_status_render
        tag = f"{sw}x{sh}"
        check(f"{tag}: status render recorded", r is not None)
        if r is None:
            continue
        check(f"{tag}: status message fully on screen",
              r['status_y'] + r['block_h'] <= sh)
        check(f"{tag}: status message doesn't overlap the buttons above it",
              r['status_y'] >= r['buttons_bottom'])


def test_no_standings_never_compacts():
    """A standard single-winner game (no Elimination Mode standings)
    should never trigger the shrink — there's no reason to, and it
    would just make an already-comfortable layout unnecessarily
    smaller."""
    assets = AssetLoader()
    assets.init()
    ws = _build_and_draw(1024, 640, "Trickster", [], "Short status.", assets)
    check("no standings -> self._compact stays at 1.0", ws._compact == 1.0)


def test_short_status_stays_close_to_full_size():
    """Even WITH standings, a short status message at a roomy
    resolution shouldn't be meaningfully shrunk — self._compact's
    up-front estimate is necessarily a little conservative (it can't
    know the real message length before setup_buttons() runs), so a
    small amount of slack is expected, but it should stay close to
    1.0, not drop toward the shrink this is meant for."""
    assets = AssetLoader()
    assets.init()
    standings = ['1. Trickster', '2. Kadi-Bot']
    ws = _build_and_draw(1920, 1080, "Trickster", standings,
                          "Caption copied to your clipboard.", assets)
    check("short status at a roomy resolution -> self._compact stays close to 1.0",
          ws._compact >= 0.9)


def test_compact_never_shrinks_past_its_floor():
    """self._compact is floored at 0.45 regardless of how extreme the
    combination gets (max-length name, max player count) — buttons
    must stay a sane, tappable size even when the layout can't fully
    resolve the overflow through gap-shrinking alone."""
    assets = AssetLoader()
    assets.init()
    long_name = "A" * 40
    standings = [f"{i}. Player{i}" for i in range(1, MAX_PLAYERS + 1)]
    status = (f"Saved kadi_win_{long_name}_20260829_104010.png \u2014 its folder "
              "just opened \u2014 drag it into the WhatsApp window that "
              "opened alongside it.")
    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        ws = _build_and_draw(sw, sh, long_name, standings, status, assets)
        check(f"{sw}x{sh}: compact factor never drops below its 0.45 floor",
              ws._compact >= 0.45)
        check(f"{sw}x{sh}: Play Again button keeps a sane, tappable size",
              ws.play_again_btn.rect.width > 0 and ws.play_again_btn.rect.height > 10)


def main():
    print("=== test_winscreen_compact_layout ===")
    test_real_reported_scenario_fits_at_every_resolution()
    test_no_standings_never_compacts()
    test_short_status_stays_close_to_full_size()
    test_compact_never_shrinks_past_its_floor()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
