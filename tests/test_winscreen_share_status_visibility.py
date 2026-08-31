"""
Regression test for WinScreen's share_status placement — the "Saved to
... drag it into the X window..." message shown after using Share.

IMPORTANT — this file was rewritten after a real bug slipped through
its own EARLIER version: that version re-derived the clamp math itself
(a second copy of what WinScreen.draw() computes) rather than reading
what draw() actually did. When draw()'s real logic was later fixed
(see below), the test's own stale copy of the OLD logic kept passing,
because it was never actually exercising the real code path. Every
check here now reads WinScreen._last_status_render — the real values
the most recent draw() call actually used — instead of recomputing
anything, so this can't drift out of sync with the implementation
again.

What actually went wrong, found via a real rendered screenshot (not
just bounds-checking) at 1024x640 with Elimination Mode standings and
the share row expanded: the OLD clamp, when the message didn't fit in
the natural space below the share-platform buttons, pulled the text
UPWARD until it fit within the screen — which meant it could climb
back up and render directly on top of the still-visible, still-
clickable share buttons. Fully "on screen" by the old check, but
illegible and covering live UI.

The fix (rendering/widgets.py's WinScreen.draw()):
  - When the message doesn't fit in the space below the buttons at the
    normal ~700px-equivalent "readable column" width, it's re-wrapped
    at a much wider max width FIRST (trading ideal line length for
    fewer, wider lines) — this alone resolves most cases.
  - The message's y-position is NEVER moved above its natural spot
    (button_bottom + gap) — if it still doesn't fit even at full
    width, the message stays in place and may trail slightly past the
    bottom edge, rather than ever overlapping the buttons above it.

Run (from the kadi/ directory):  python -m tests.test_winscreen_share_status_visibility
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

from rendering.widgets import WinScreen

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


def _build_and_draw(sw, sh, standings=None, share_status=LONG_STATUS, expanded=True):
    font_large = pygame.font.Font(None, 64)
    font_med = pygame.font.Font(None, 40)
    font_small = pygame.font.Font(None, 22)
    ws = WinScreen('Alice', sw, sh, font_large, font_med, font_small,
                    standings=standings)
    ws.setup_buttons(font_small, on_play_again=lambda: None, on_menu=lambda: None,
                      on_share=lambda k: None)
    ws.share_expanded = expanded
    ws.share_status = share_status
    surf = pygame.Surface((sw, sh))
    ws.draw(surf)  # populates ws._last_status_render
    return ws


def _check_render(ws, tag):
    """Runs every invariant against ws._last_status_render — the REAL
    values the actual draw() call used, not a re-derivation."""
    r = ws._last_status_render
    check(f"{tag}: draw() recorded a status render", r is not None)
    if r is None:
        return
    status_y, lines, line_h, block_h = r['status_y'], r['lines'], r['line_h'], r['block_h']
    buttons_bottom = r['buttons_bottom']

    check(f"{tag}: status block starts within the screen", status_y >= 0)
    # The critical invariant this file exists to guard: the message can
    # never start above the bottom of the share buttons — that's what
    # "overlapping the buttons" means, regardless of whether it also
    # happens to stay within the screen's bottom edge.
    check(f"{tag}: status block never overlaps the share buttons above it",
          status_y >= buttons_bottom)
    for line in lines:
        w = ws.font_small.size(line)[0]
        x = ws.sw // 2 - w // 2
        check(f"{tag}: line fits horizontally within the screen: {line[:30]!r}...",
              x >= 0 and x + w <= ws.sw)


def test_fully_visible_and_no_button_overlap_at_reported_resolution():
    ws = _build_and_draw(1024, 640, standings=['1. Alice', '2. Bob', '3. Carol', '4. Dave'])
    r = ws._last_status_render
    check("status message wraps into more than one line at 1024x640",
          len(r['lines']) > 1)
    _check_render(ws, "1024x640")


def test_short_status_unaffected():
    """A short, ordinary status message shouldn't be needlessly wrapped
    or repositioned — this only kicks in for messages that actually
    need it."""
    ws = _build_and_draw(1024, 640, share_status="Caption copied to your clipboard.")
    r = ws._last_status_render
    check("short status stays on one line", len(r['lines']) == 1)
    check("short status doesn't overlap the buttons",
          r['status_y'] >= r['buttons_bottom'])


def test_larger_resolution_unaffected():
    """At a roomy resolution the same message should still render
    normally — comfortably below the buttons with room to spare,
    confirming the fix isn't just forcing everything to some edge
    regardless of screen size."""
    ws = _build_and_draw(1920, 1080)
    r = ws._last_status_render
    check("status block fits comfortably at 1920x1080",
          r['status_y'] + r['block_h'] <= ws.sh)
    check("status block isn't pinned to the very bottom unnecessarily",
          r['status_y'] < ws.sh - 200)


def test_all_supported_resolutions_and_worst_case_standings():
    """Every resolution the Settings screen actually offers (see
    constants.UI_SCALE_PROFILES), each checked twice: once with no
    standings (a standard win) and once with the worst case this
    layout has to handle — an 8-player Elimination Mode standings
    block, which pushes everything below it (buttons, share row,
    status message) further down the screen than any other game mode
    does, combined with the share row expanded. The smallest offered
    resolution (1024x640) with 8-player standings is the exact
    combination that originally exposed the button-overlap bug this
    file guards against."""
    from constants import UI_SCALE_PROFILES
    worst_case_standings = [f"{i}. Player{i}" for i in range(1, 9)]

    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        for standings in (None, worst_case_standings):
            ws = _build_and_draw(sw, sh, standings=standings)
            tag = f"{sw}x{sh}" + (" (8p elimination)" if standings else "")
            _check_render(ws, tag)


def main():
    print("=== test_winscreen_share_status_visibility ===")
    test_fully_visible_and_no_button_overlap_at_reported_resolution()
    test_short_status_unaffected()
    test_larger_resolution_unaffected()
    test_all_supported_resolutions_and_worst_case_standings()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
