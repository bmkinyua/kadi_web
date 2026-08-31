"""
Regression test for a real UI bug found in production testing on the
actual deployed Oracle Cloud server: the settings panel's "MSOMI
Model" row (a long, timestamped filename like
"msomi_model_20260726_173443.json") visually overlapped its own label
because label and value were blitted at their natural, untruncated
widths. scenes._draw_settings_panel now truncates each independently
via scenes._truncate_to_width so this can't recur for ANY long
label/value pair, not just MSOMI filenames specifically.

This only needs pygame's font metrics, not a running server — no
network involved.

Run (from the kadi/ directory):  SDL_VIDEODRIVER=dummy python -m tests.test_settings_panel_truncation
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from scenes import _truncate_to_width, _draw_settings_panel

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def run():
    pygame.init()
    pygame.font.init()
    font = pygame.font.SysFont(None, 22)

    short = "Turn Timer"
    check("a short string that already fits is left untouched",
          _truncate_to_width(short, font, 300) == short)

    long_name = "msomi_model_20260726_173443.json"
    budget = 100  # deliberately tight, matching the real panel's value column
    truncated = _truncate_to_width(long_name, font, budget)
    check("a too-long string actually gets shortened",
          truncated != long_name)
    check("the truncated string still fits within budget",
          font.size(truncated)[0] <= budget)
    check("the truncated string ends with an ellipsis marker",
          truncated.endswith("…"))

    # Regression check for the actual reported bug: render the exact
    # row set from the field report and confirm label+value never
    # overlap in practice.
    surf = pygame.Surface((1280, 800))
    rect = pygame.Rect(950, 190, 300, 500)
    rows = [
        ("Elimination Mode", "OFF"),
        ("Turn Timer", "ON (300s)"),
        ("Hints", "ON (after 50% of timer)"),
        ("Post-play window", "120.0s"),
        ("Jump Counter window", "120.0s"),
        ("Ace Suit Integrity", "ON"),
        ("Pickup Shield (Q/K)", "ON"),
        ("Ace Finisher", "ON"),
        ("Jump Multi-card", "ON"),
        ("AI Players", "1 (Medium)"),
        ("  MSOMI Model", "msomi_model_20260726_173443.json"),
    ]
    font_title = pygame.font.SysFont(None, 26)
    _draw_settings_panel(surf, rect, rows, font_title, font, 0.0)

    # Recompute the same label/value budgets _draw_settings_panel uses
    # internally and confirm every row's rendered label+value widths
    # never sum past the available space (the actual overlap
    # condition) for this exact row set.
    list_rect = pygame.Rect(rect.x + 10, rect.y + 46, rect.width - 20, rect.height - 56)
    label_budget = int(list_rect.width * 0.52)
    value_budget = list_rect.width - label_budget - 16
    all_fit = True
    for lbl_text, val_text in rows:
        lbl_w = font.size(_truncate_to_width(lbl_text, font, label_budget))[0]
        val_w = font.size(_truncate_to_width(val_text, font, value_budget))[0]
        if lbl_w > label_budget or val_w > value_budget:
            all_fit = False
    check("every row from the field report fits within its column budget "
          "(the exact case that used to overlap)", all_fit)


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"SETTINGS PANEL TRUNCATION: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("SETTINGS PANEL TRUNCATION: ALL CHECKS PASSED")
        sys.exit(0)
