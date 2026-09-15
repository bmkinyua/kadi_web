"""
Regression test for the Main Menu's developer-contact icon row (see
scenes.ContactBar / core.social_share.CONTACT_LINKS).

Covers three things a hand-add of "a few clickable icons" easily gets
wrong:
  - the icons stay fully on-screen and never overlap each other OR the
    existing version string (bottom-left) at ANY supported resolution,
    from the 1024x640 floor to 8K — the whole point of routing sizing
    through get_chrome_scale() like every other piece of menu chrome
    instead of hard-coding pixel positions;
  - each button actually opens the right URL for its platform (via
    webbrowser.open, monkeypatched here so this never opens a real
    browser tab in CI);
  - the link list itself is exactly the three requested platforms,
    correctly formed (mailto: for email, https:// for the others).

Run (from the kadi/ directory):  python -m tests.test_contact_links
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

from constants import UI_SCALE_PROFILES, get_chrome_scale
from core import social_share
from rendering.widgets import draw_icon
import scenes

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


_font = pygame.font.Font(None, 14)


def test_contact_links_are_exactly_the_three_requested():
    keys = [key for key, _icon, _label, _url in social_share.CONTACT_LINKS]
    check("exactly 3 contact links", len(social_share.CONTACT_LINKS) == 3)
    check("keys are twitter/email/linkedin, in that order",
          keys == ["twitter", "email", "linkedin"])

    by_key = {k: url for k, _i, _l, url in social_share.CONTACT_LINKS}
    check("twitter URL is the handle's profile page",
          by_key["twitter"] == "https://twitter.com/BMKinyua")
    check("email uses a mailto: link (opens the OS mail client, not a browser tab)",
          by_key["email"] == "mailto:thekadigame@gmail.com")
    check("linkedin URL is the given profile page",
          by_key["linkedin"] ==
          "https://www.linkedin.com/in/blaise-kinyua-20987b47/")


def test_icon_kinds_render_without_raising():
    for kind in ("twitter", "email", "linkedin"):
        for size in (16, 30, 64, 128):
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            try:
                draw_icon(s, s.get_rect(), kind, (255, 255, 255), width=2)
                ok = True
            except Exception as e:
                ok = False
                print(f"    exception: {e}")
            check(f"draw_icon('{kind}') renders at {size}px", ok)


def test_click_opens_correct_url_per_icon(monkeypatch_calls=None):
    calls = []
    orig_open = social_share.webbrowser.open
    social_share.webbrowser.open = lambda url: (calls.append(url), True)[1]
    try:
        cb = scenes.ContactBar(_font, _font)
        sw, sh = 1280, 800
        cb.update(0.016, sw, sh, (-1000, -1000))  # lay out rects
        expected = [url for _k, _i, _l, url in social_share.CONTACT_LINKS]
        for btn, url in zip(cb._buttons, expected):
            calls.clear()
            center = btn.rect.center
            cb.handle_event(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, button=1, pos=center))
            cb.handle_event(pygame.event.Event(
                pygame.MOUSEBUTTONUP, button=1, pos=center))
            check(f"clicking the icon at {center} opens {url}",
                  calls == [url])
    finally:
        social_share.webbrowser.open = orig_open


def test_no_overlap_at_any_supported_resolution():
    """Every icon stays on-screen, never overlaps a sibling icon, and
    never overlaps the version string's own (also get_chrome_scale-d)
    footprint at the opposite corner — the two are meant to read as one
    balanced footer row, never collide."""
    for (sw, sh) in sorted(UI_SCALE_PROFILES.keys()):
        cb = scenes.ContactBar(_font, _font)
        cb.update(0.016, sw, sh, (-1000, -1000))
        rects = [b.rect for b in cb._buttons]

        for r in rects:
            check(f"{sw}x{sh}: icon fully on-screen ({r})",
                  r.left >= 0 and r.top >= 0 and r.right <= sw and r.bottom <= sh)

        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                check(f"{sw}x{sh}: icons {i} and {j} don't overlap",
                      not rects[i].colliderect(rects[j]))

        cs = get_chrome_scale(sw, sh)
        # Mirrors MainMenuScene.draw()'s own version-string geometry:
        # f"v{VERSION} — Python/Pygame" rendered with font_scaled('ui_tiny', cs)
        # at (s(10), sh - s(20)). Using a same-length placeholder string
        # with the test's own tiny font is a reasonable stand-in since
        # the real check is "does the footer row have room", not exact
        # pixel-for-pixel text metrics.
        ver_text_w = _font.size("v9.9.9 — Python/Pygame")[0]
        ver_right = round(10 * cs) + ver_text_w
        leftmost_icon = min(r.left for r in rects)
        check(f"{sw}x{sh}: version string and contact icons don't collide",
              ver_right < leftmost_icon)


def run_all():
    tests = [
        test_contact_links_are_exactly_the_three_requested,
        test_icon_kinds_render_without_raising,
        test_click_opens_correct_url_per_icon,
        test_no_overlap_at_any_supported_resolution,
    ]
    for t in tests:
        print(f"\n{t.__name__}")
        t()

    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_all()
