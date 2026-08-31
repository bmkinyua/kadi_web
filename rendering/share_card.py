"""
KADI - Social sharing (Profile Part C): renders the shareable PNG
summary card shown/saved from the win screen and the Profile screen's
badge list.

Deliberately reuses the game's EXISTING visual-polish tokens rather
than inventing a new look for these images: TABLE_FELT/TABLE_EDGE/GOLD/
GOLD_LIGHT/WHITE from constants.py, draw_rounded_rect() and
draw_trophy_icon() from rendering/widgets.py, and whichever
AssetLoader fonts the caller passes in (the same 'kadi_banner'/
'ui_large'/'ui_medium'/'ui_normal' fonts WinScreen and ProfileScene
already use) -- so a shared card reads as unmistakably "from KADI"
rather than a one-off graphic bolted on for this feature.
"""
from __future__ import annotations
import pygame

from constants import TABLE_FELT, TABLE_EDGE, WHITE, GOLD_LIGHT
from rendering.widgets import draw_rounded_rect, draw_trophy_icon

CARD_W, CARD_H = 1000, 560


def _background(surf: pygame.Surface):
    surf.fill(TABLE_EDGE)
    inner = pygame.Rect(18, 18, CARD_W - 36, CARD_H - 36)
    draw_rounded_rect(surf, TABLE_FELT, inner, 20, border_color=GOLD_LIGHT, border_width=3)


def _footer(surf: pygame.Surface, font_small: pygame.font.Font):
    tag = font_small.render("Played on KADI", True, (*WHITE, 150))
    surf.blit(tag, (CARD_W - tag.get_width() - 40, CARD_H - 50))


def render_win_share_card(winner_name: str, stat_line: str,
                          font_banner: pygame.font.Font,
                          font_large: pygame.font.Font,
                          font_medium: pygame.font.Font,
                          font_small: pygame.font.Font) -> pygame.Surface:
    """A 'I just won a game of KADI!' summary card: winner name, a
    caller-supplied stat line (e.g. mode + finish kind), and the same
    trophy iconography WinScreen uses in-game."""
    surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
    _background(surf)
    cx = CARD_W // 2

    win_t = font_banner.render("WINNER!", True, GOLD_LIGHT)
    surf.blit(win_t, (cx - win_t.get_width() // 2, 70))

    draw_trophy_icon(surf, cx - 220, 230, scale=2.2)
    draw_trophy_icon(surf, cx + 220, 230, scale=2.2)

    name_t = font_large.render(winner_name, True, GOLD_LIGHT)
    surf.blit(name_t, (cx - name_t.get_width() // 2, 200))

    if stat_line:
        stat_t = font_medium.render(stat_line, True, WHITE)
        surf.blit(stat_t, (cx - stat_t.get_width() // 2, 270))

    tagline = font_small.render("I just won a game of KADI!", True, (*WHITE, 220))
    surf.blit(tagline, (cx - tagline.get_width() // 2, 340))

    _footer(surf, font_small)
    return surf


def render_badge_share_card(player_name: str, badge_name: str, badge_desc: str,
                            font_banner: pygame.font.Font,
                            font_large: pygame.font.Font,
                            font_medium: pygame.font.Font,
                            font_small: pygame.font.Font) -> pygame.Surface:
    """A 'Badge earned' summary card, reusing the same in-game toast
    color (see scenes.py's _record_profile_stats badge-toast) and
    layout language as the win card above so the two feel like one
    family rather than two unrelated designs."""
    surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
    _background(surf)
    cx = CARD_W // 2

    hdr_t = font_banner.render("BADGE EARNED!", True, (255, 215, 60))
    hdr_scaled = pygame.transform.smoothscale(
        hdr_t, (int(hdr_t.get_width() * 0.62), int(hdr_t.get_height() * 0.62)))
    surf.blit(hdr_scaled, (cx - hdr_scaled.get_width() // 2, 60))

    dot_r = 10
    pygame.draw.circle(surf, GOLD_LIGHT, (cx, 190), dot_r)

    name_t = font_large.render(badge_name, True, GOLD_LIGHT)
    surf.blit(name_t, (cx - name_t.get_width() // 2, 220))

    for i, line in enumerate(_wrap_plain(badge_desc, font_medium, CARD_W - 160)):
        t = font_medium.render(line, True, WHITE)
        surf.blit(t, (cx - t.get_width() // 2, 280 + i * (t.get_height() + 4)))

    player_t = font_small.render(f"— {player_name}", True, (*WHITE, 210))
    surf.blit(player_t, (cx - player_t.get_width() // 2, 380))

    _footer(surf, font_small)
    return surf


def _wrap_plain(text: str, font: pygame.font.Font, max_w: int):
    """Minimal word-wrap so this module doesn't need to import
    scenes.py just for wrap_text() (which would be a backwards
    dependency -- scenes.py imports rendering, not the reverse)."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.size(trial)[0] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines
