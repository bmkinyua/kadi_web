"""
KADI - Startup resolution picker.

Runs once, right after pygame.init(), BEFORE the real game window is
created with whatever resolution is currently saved. Exists specifically
so a saved/selected resolution the current display can't actually handle
(e.g. 7680x4320 on a 1080p monitor) can never again leave someone stuck
looking at an oversized, unusable window with no visible way back into
Settings — see the "stuck at 8K" support conversation this was built for.

This module is intentionally self-contained: it only depends on pygame,
constants, and rendering.widgets (Button/draw_shadow/wrap_text), NOT on
GameManager internals, SceneManager, or any Scene. That's deliberate —
this needs to be able to run and recover the player's resolution even if
something further downstream were ever broken, since a resolution problem
is exactly the kind of thing that could leave the rest of the app
unreachable.
"""
from __future__ import annotations
import sys
import pygame
from typing import Tuple

from constants import FPS, WHITE, GOLD, GOLD_LIGHT
from rendering.widgets import Button, wrap_text, draw_shadow, draw_icon

# Imported from scenes.py rather than redefined, so there's exactly one
# list of supported resolutions and one display-capability check in the
# whole game.
from scenes import (
    RESOLUTIONS, RES_LABELS,
    _detect_display_caps, _resolution_exceeds_display, _optimum_resolution_idx,
)

BG_TOP    = (10, 22, 16)
BG_BOTTOM = (18, 38, 26)
ROW_BG          = (30, 55, 40)
ROW_BG_HOVER    = (45, 75, 55)
ROW_BG_SELECTED = (55, 95, 65)
NOT_RECOMMENDED_COLOR = (220, 120, 90)
RECOMMENDED_COLOR     = (140, 220, 150)


def _safe_window_size() -> Tuple[int, int]:
    """Size for THIS picker window only — capped well inside whatever was
    detected so the picker itself is guaranteed fully visible regardless
    of the (possibly broken) saved resolution. Falls back to a
    conservative fixed size if detection fails entirely."""
    max_w, max_h = _detect_display_caps()
    if max_w and max_h:
        w = min(880, max_w - 80)
        h = min(640, max_h - 80)
        return max(480, w), max(420, h)
    return 880, 640


def should_show_startup_picker(gm) -> bool:
    """True if the picker needs to run before the real window opens.

    Shown when:
      - the player hasn't opted out yet (skip_startup_resolution_picker
        is False, the default), OR
      - their saved resolution isn't one of the known options, or no
        longer fits the detected display.

    That second condition is what guarantees the picker comes back
    automatically even for someone who ticked "don't ask again" and then,
    say, moved the game to a smaller monitor — an opt-out can never leave
    them stuck the way an oversized resolution did before.
    """
    if not getattr(gm, 'skip_startup_resolution_picker', False):
        return True
    saved = tuple(getattr(gm, 'resolution', (0, 0)))
    return saved not in RESOLUTIONS or _resolution_exceeds_display(saved)


def _fill_gradient(surf: pygame.Surface, top, bottom):
    h = surf.get_height()
    for y in range(h):
        t = y / max(1, h - 1)
        col = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        pygame.draw.line(surf, col, (0, y), (surf.get_width(), y))


def run_startup_resolution_picker(gm) -> None:
    """Blocks until the player confirms a resolution, then sets
    gm.resolution (and gm.skip_startup_resolution_picker) directly and
    returns. Does NOT create the real game window — main() does that
    afterward via make_screen(), exactly as it always has."""
    sw, sh = _safe_window_size()
    screen = pygame.display.set_mode((sw, sh))
    pygame.display.set_caption("KADI - Select Display Resolution")
    clock = pygame.time.Clock()

    pygame.font.init()
    font_title  = pygame.font.SysFont('Arial', 26, bold=True)
    font_normal = pygame.font.SysFont('Arial', 17)
    font_small  = pygame.font.SysFont('Arial', 14)
    font_tiny   = pygame.font.SysFont('Arial', 12)

    max_w, max_h = _detect_display_caps()
    optimum_idx = _optimum_resolution_idx()

    saved = tuple(getattr(gm, 'resolution', (0, 0)))
    if saved in RESOLUTIONS and not _resolution_exceeds_display(saved):
        selected_idx = RESOLUTIONS.index(saved)
    else:
        selected_idx = optimum_idx

    state = {'expanded': False, 'checkbox_checked': False, 'confirmed': False}

    margin = 40
    dropdown_rect = pygame.Rect(margin, 150, sw - margin * 2, 52)
    checkbox_rect = pygame.Rect(margin, sh - 130, 22, 22)

    def on_start_clicked():
        state['confirmed'] = True

    start_btn = Button(pygame.Rect(sw - margin - 220, sh - 76, 220, 50),
                        "Start Game", font_normal,
                        color=(40, 110, 60), hover_color=(55, 135, 75),
                        on_click=on_start_clicked)

    row_h = 44
    row_rects = [pygame.Rect(margin, dropdown_rect.bottom + 4 + i * row_h,
                              sw - margin * 2, row_h - 2)
                 for i in range(len(RESOLUTIONS))]

    def label_for(i: int) -> str:
        label = RES_LABELS[i]
        if i == optimum_idx:
            label += "  (Recommended)"
        elif _resolution_exceeds_display(RESOLUTIONS[i]):
            label += "  (Not Recommended)"
        return label

    def color_for(i: int) -> Tuple[int, int, int]:
        if i == optimum_idx:
            return RECOMMENDED_COLOR
        if _resolution_exceeds_display(RESOLUTIONS[i]):
            return NOT_RECOMMENDED_COLOR
        return WHITE

    clock_running = True
    while clock_running and not state['confirmed']:
        dt = clock.tick(FPS) / 1000.0
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE and state['expanded']:
                    state['expanded'] = False
                elif event.key == pygame.K_RETURN and not state['expanded']:
                    state['confirmed'] = True

            if state['expanded']:
                # While the list is open, it's the only clickable thing —
                # matches the modal-gating pattern used for the in-game
                # resolution-warning dialog in scenes.SettingsScene.
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    clicked_row = False
                    for i, r in enumerate(row_rects):
                        if r.collidepoint(event.pos):
                            selected_idx = i
                            state['expanded'] = False
                            clicked_row = True
                            break
                    if not clicked_row and not dropdown_rect.collidepoint(event.pos):
                        state['expanded'] = False
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if dropdown_rect.collidepoint(event.pos):
                    state['expanded'] = True
                    continue
                if checkbox_rect.inflate(300, 10).collidepoint(event.pos):
                    state['checkbox_checked'] = not state['checkbox_checked']
                    continue
            start_btn.handle_event(event)

        if not state['expanded']:
            start_btn.update(dt, mouse_pos)

        # ── Draw ────────────────────────────────────────────────────────
        _fill_gradient(screen, BG_TOP, BG_BOTTOM)

        title = font_title.render("Select Display Resolution", True, GOLD_LIGHT)
        screen.blit(title, (margin, 40))

        if max_w and max_h:
            detected = f"Detected display: {max_w}\u00d7{max_h}"
        else:
            detected = "Detected display: unknown (couldn't query display capabilities)"
        det_surf = font_small.render(detected, True, (200, 205, 195))
        screen.blit(det_surf, (margin, 82))

        sub = ("This only needs to be set once — pick whichever looks right, "
               "or use the recommended option below.")
        for j, line in enumerate(wrap_text(font_tiny, sub, sw - margin * 2)):
            ls = font_tiny.render(line, True, (170, 178, 165))
            screen.blit(ls, (margin, 108 + j * 16))

        # Dropdown (closed) box
        draw_shadow(screen, dropdown_rect, 8)
        pygame.draw.rect(screen, ROW_BG, dropdown_rect, border_radius=8)
        pygame.draw.rect(screen, GOLD if state['expanded'] else (90, 110, 95), dropdown_rect,
                          width=2, border_radius=8)
        cur_label = font_normal.render(label_for(selected_idx), True, color_for(selected_idx))
        screen.blit(cur_label, (dropdown_rect.x + 14, dropdown_rect.centery - cur_label.get_height() // 2))
        # Vector-drawn chevron, not a Unicode triangle glyph (\u25B2/
        # \u25BC) — neither is in this project's bundled fonts, so it
        # rendered as a tofu box. Same fix as SettingsScene's in-game
        # resolution dropdown, which mirrors this picker's UX.
        chevron_kind = 'chevron_up' if state['expanded'] else 'chevron_down'
        chevron_rect = pygame.Rect(0, 0, 20, 20)
        chevron_rect.center = (dropdown_rect.right - 22, dropdown_rect.centery)
        draw_icon(screen, chevron_rect, chevron_kind, WHITE, width=2)

        if not state['expanded']:
            pygame.draw.rect(screen, ROW_BG, checkbox_rect, border_radius=4)
            pygame.draw.rect(screen, (140, 150, 135), checkbox_rect, width=2, border_radius=4)
            if state['checkbox_checked']:
                inner = checkbox_rect.inflate(-8, -8)
                pygame.draw.rect(screen, GOLD_LIGHT, inner, border_radius=2)
            cb_label = font_small.render("Don't ask again (use this resolution automatically)",
                                          True, (210, 214, 205))
            screen.blit(cb_label, (checkbox_rect.right + 10, checkbox_rect.centery - cb_label.get_height() // 2))

            hint = font_tiny.render(
                "If the saved resolution ever stops fitting your display, this screen comes back automatically.",
                True, (150, 158, 145))
            screen.blit(hint, (margin, checkbox_rect.bottom + 8))

            start_btn.draw(screen)
        else:
            # Expanded list — drawn last so it sits on top of everything else.
            for i, r in enumerate(row_rects):
                hovered = r.collidepoint(mouse_pos)
                bg = ROW_BG_SELECTED if i == selected_idx else (ROW_BG_HOVER if hovered else ROW_BG)
                pygame.draw.rect(screen, bg, r, border_radius=6)
                pygame.draw.rect(screen, (70, 90, 75), r, width=1, border_radius=6)
                lbl = font_normal.render(label_for(i), True, color_for(i))
                screen.blit(lbl, (r.x + 14, r.centery - lbl.get_height() // 2))

        pygame.display.flip()

    gm.resolution = RESOLUTIONS[selected_idx]
    gm.skip_startup_resolution_picker = state['checkbox_checked']
