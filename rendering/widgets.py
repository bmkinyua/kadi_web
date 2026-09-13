"""
KADI - UI Widgets
Reusable UI components: buttons, panels, banners, suit picker.
"""
from __future__ import annotations
import pygame
import math
from typing import Optional, Callable, List, Tuple
from core.social_share import SHARE_UI_OPTIONS
from constants import (
    BTN_NORMAL, BTN_HOVER, BTN_PRESSED, BTN_DISABLED, BTN_TEXT,
    WHITE, BLACK, DARK_GRAY, MID_GRAY, LIGHT_GRAY,
    GOLD, GOLD_LIGHT, KADI_COLOR, TABLE_GREEN, UI_PANEL, UI_PANEL_B,
    Suit, SUIT_SYMBOL, SUIT_ICON, SUIT_ACCENT, SUIT_COLOR,
    RADIUS_PANEL, RADIUS_BUTTON, SHADOW_COLOR, SHADOW_ALPHA, SHADOW_OFFSET,
    BORDER_LIGHT, BORDER_ACCENT, PANEL_BG_ALPHA, OVERLAY_ALPHA,
)


def wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list:
    """Greedy word-wrap. Returns a list of lines that each fit max_width
    when rendered with the given font.

    A single "word" (split on spaces) that's STILL wider than
    max_width on its own — e.g. an unbroken filesystem path like
    "/home/someone/.local/share/KADI/win_card_20260819_161533.png",
    which has no spaces to break on — used to just get emitted as its
    own overflowing line with no wrapping at all. That's exactly what
    let WinScreen's share_status message run off both the left/right
    edges (see that class's own comment on this): a full save path
    plus the surrounding sentence is routinely wider than a 1024px
    screen. Any such word now gets broken at a character boundary
    (binary search for the longest slice that still fits) so it wraps
    like everything else instead of silently overflowing.
    """
    words = text.split(' ')
    lines = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if font.size(trial)[0] <= max_width:
            cur = trial
            continue
        if not cur:
            # The word itself doesn't fit even alone on a fresh line —
            # break IT at a character boundary rather than emitting an
            # overflowing line.
            remaining = word
            while font.size(remaining)[0] > max_width and len(remaining) > 1:
                lo, hi = 1, len(remaining)
                fit = 1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if font.size(remaining[:mid])[0] <= max_width:
                        fit = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                lines.append(remaining[:fit])
                remaining = remaining[fit:]
            cur = remaining
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_icon(surf: pygame.Surface, rect: pygame.Rect, kind: str,
              color=WHITE, width: int = 2):
    """Draws small UI glyphs (close/minimize/maximize/mute/etc.) as plain
    vector shapes instead of relying on Unicode symbol/emoji glyphs, which
    are frequently missing from system fonts (esp. plain Arial on Windows)
    and render as tofu boxes. Keeps icon buttons crisp on every platform."""
    cx, cy = rect.center
    w, h = rect.width, rect.height

    if kind == 'close':
        pad_x, pad_y = w * 0.28, h * 0.28
        pygame.draw.line(surf, color, (rect.left + pad_x, rect.top + pad_y),
                         (rect.right - pad_x, rect.bottom - pad_y), width)
        pygame.draw.line(surf, color, (rect.right - pad_x, rect.top + pad_y),
                         (rect.left + pad_x, rect.bottom - pad_y), width)

    elif kind == 'minimize':
        pygame.draw.line(surf, color, (cx - w * 0.22, cy), (cx + w * 0.22, cy), width)

    elif kind == 'maximize':
        r = pygame.Rect(0, 0, max(8, int(w * 0.42)), max(8, int(h * 0.42)))
        r.center = (cx, cy)
        pygame.draw.rect(surf, color, r, width=width)

    elif kind == 'restore':
        sz = max(7, int(w * 0.34))
        r1 = pygame.Rect(0, 0, sz, sz); r1.center = (cx - 3, cy + 3)
        r2 = pygame.Rect(0, 0, sz, sz); r2.center = (cx + 3, cy - 3)
        pygame.draw.rect(surf, color, r1, width=width)
        pygame.draw.rect(surf, color, r2, width=width)

    elif kind in ('mute', 'unmute'):
        body_w, body_h = w * 0.16, h * 0.32
        body = pygame.Rect(0, 0, body_w, body_h)
        body.center = (cx - w * 0.16, cy)
        pygame.draw.rect(surf, color, body, border_radius=1)
        cone = [(body.right, body.top), (cx - w * 0.02, cy - h * 0.24),
                (cx - w * 0.02, cy + h * 0.24), (body.right, body.bottom)]
        pygame.draw.polygon(surf, color, cone)
        if kind == 'unmute':
            for r_mult in (0.30, 0.40):
                rect_arc = pygame.Rect(0, 0, w * r_mult * 2, h * r_mult * 2)
                rect_arc.center = (cx - w * 0.02, cy)
                pygame.draw.arc(surf, color, rect_arc, -0.6, 0.6, width)
        else:
            x1, y1 = cx + w * 0.10, cy - h * 0.18
            x2, y2 = cx + w * 0.30, cy + h * 0.18
            pygame.draw.line(surf, color, (x1, y1), (x2, y2), width)
            pygame.draw.line(surf, color, (x1, y2), (x2, y1), width)

    elif kind in ('music_on', 'music_off'):
        # A simple single eighth-note: a stem + a filled notehead, drawn
        # as plain shapes for the same cross-platform-glyph reasons as
        # 'mute'/'unmute' above.
        note_r = max(3, int(min(w, h) * 0.14))
        stem_x = cx + w * 0.12
        stem_top = cy - h * 0.30
        stem_bottom = cy + h * 0.14
        pygame.draw.line(surf, color, (stem_x, stem_top), (stem_x, stem_bottom), width)
        # Flag
        pygame.draw.line(surf, color, (stem_x, stem_top),
                         (stem_x + w * 0.16, stem_top + h * 0.14), width)
        # Notehead (tilted ellipse via small filled circle)
        head_center = (stem_x - note_r * 0.9, stem_bottom)
        pygame.draw.circle(surf, color, head_center, note_r)
        if kind == 'music_off':
            x1, y1 = cx - w * 0.30, cy - h * 0.28
            x2, y2 = cx + w * 0.30, cy + h * 0.28
            pygame.draw.line(surf, color, (x1, y1), (x2, y2), width + 1)

    elif kind == 'pause':
        bar_w = max(3, int(w * 0.16))
        bar_h = h * 0.5
        gap = w * 0.14
        for dx in (-gap, gap):
            r = pygame.Rect(0, 0, bar_w, bar_h)
            r.center = (cx + dx, cy)
            pygame.draw.rect(surf, color, r, border_radius=1)

    elif kind == 'play':
        s = min(w, h) * 0.32
        pts = [(cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s), (cx + s, cy)]
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'left_arrow':
        s = min(w, h) * 0.28
        pts = [(cx + s * 0.6, cy - s), (cx - s, cy), (cx + s * 0.6, cy + s)]
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'right_arrow':
        s = min(w, h) * 0.28
        pts = [(cx - s * 0.6, cy - s), (cx + s, cy), (cx - s * 0.6, cy + s)]
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'chevron_up':
        s = min(w, h) * 0.28
        pts = [(cx - s, cy + s * 0.6), (cx, cy - s), (cx + s, cy + s * 0.6)]
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'chevron_down':
        s = min(w, h) * 0.28
        pts = [(cx - s, cy - s * 0.6), (cx, cy + s), (cx + s, cy - s * 0.6)]
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'check':
        pts = [(cx - w * 0.26, cy), (cx - w * 0.06, cy + h * 0.22), (cx + w * 0.28, cy - h * 0.24)]
        pygame.draw.lines(surf, color, False, pts, width + 1)

    elif kind == 'cross':
        pad_x, pad_y = w * 0.30, h * 0.30
        pygame.draw.line(surf, color, (cx - pad_x, cy - pad_y), (cx + pad_x, cy + pad_y), width)
        pygame.draw.line(surf, color, (cx + pad_x, cy - pad_y), (cx - pad_x, cy + pad_y), width)

    elif kind == 'kickback':
        # Circular "reverse" arrow — used in place of the U+21BA glyph,
        # which is frequently missing from system/bundled fonts and shows
        # as a tofu box.
        r = min(w, h) * 0.34
        arc_rect = pygame.Rect(0, 0, r * 2, r * 2)
        arc_rect.center = (cx, cy)
        pygame.draw.arc(surf, color, arc_rect, 0.9, 5.6, max(2, width))
        # Arrowhead at the open end of the arc
        head_x = cx + r * math.cos(0.9)
        head_y = cy - r * math.sin(0.9)
        ang = 0.9
        tip = (head_x, head_y)
        a1 = (tip[0] + r * 0.45 * math.cos(ang + 2.4), tip[1] - r * 0.45 * math.sin(ang + 2.4))
        a2 = (tip[0] + r * 0.45 * math.cos(ang - 0.3), tip[1] - r * 0.45 * math.sin(ang - 0.3))
        pygame.draw.polygon(surf, color, [tip, a1, a2])

    elif kind == 'jump':
        # Skip-forward chevrons — used in place of the U+2933 glyph.
        s = min(w, h) * 0.26
        for dx in (-s * 0.7, s * 0.7):
            pts = [(cx + dx - s * 0.5, cy - s), (cx + dx + s * 0.5, cy), (cx + dx - s * 0.5, cy + s)]
            pygame.draw.polygon(surf, color, pts)

    elif kind == 'sparkle':
        # 4-point sparkle — used in place of the U+2726 glyph.
        s = min(w, h) * 0.42
        pygame.draw.polygon(surf, color, [
            (cx, cy - s), (cx + s * 0.22, cy - s * 0.22),
            (cx + s, cy), (cx + s * 0.22, cy + s * 0.22),
            (cx, cy + s), (cx - s * 0.22, cy + s * 0.22),
            (cx - s, cy), (cx - s * 0.22, cy - s * 0.22),
        ])

    elif kind == 'double_arrow':
        # Horizontal double-headed arrow — used to flag AI hands that
        # have been turned face-up for spectating (Elimination Mode,
        # AI Spectator stretch): a shaft with a triangular head at
        # both ends, built the same way as left_arrow/right_arrow
        # above rather than relying on a Unicode ↔ glyph.
        half = w * 0.34
        pygame.draw.line(surf, color, (cx - half, cy), (cx + half, cy), width)
        s = min(w, h) * 0.22
        pygame.draw.polygon(surf, color, [
            (cx - half + s * 1.1, cy - s), (cx - half, cy), (cx - half + s * 1.1, cy + s)])
        pygame.draw.polygon(surf, color, [
            (cx + half - s * 1.1, cy - s), (cx + half, cy), (cx + half - s * 1.1, cy + s)])

    elif kind == 'plus':
        pygame.draw.line(surf, color, (cx - w * 0.24, cy), (cx + w * 0.24, cy), width + 1)
        pygame.draw.line(surf, color, (cx, cy - h * 0.24), (cx, cy + h * 0.24), width + 1)

    elif kind == 'minus':
        pygame.draw.line(surf, color, (cx - w * 0.24, cy), (cx + w * 0.24, cy), width + 1)

    elif kind == 'star':
        # 5-point star — used in place of the U+2605 glyph, which renders
        # as a tofu box on some bundled/system fonts.
        pts = []
        outer = min(w, h) * 0.5
        inner = outer * 0.42
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            r = outer if i % 2 == 0 else inner
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        pygame.draw.polygon(surf, color, pts)

    elif kind == 'spade':
        # Card suit — used in place of the U+2660 glyph, which several
        # bundled UI fonts (incl. this project's Poppins body font) don't
        # include at all, rendering as a tofu box instead of a spade.
        _draw_suit_shape(surf, 'spade', cx, cy, min(w, h) * 0.5, color)

    elif kind == 'heart':
        # Card suit — used in place of the U+2665 glyph (same coverage
        # problem as 'spade' above).
        _draw_suit_shape(surf, 'heart', cx, cy, min(w, h) * 0.48, color)

    elif kind == 'diamond':
        # Card suit — used in place of the U+2666 glyph (same coverage
        # problem as 'spade'/'heart' above).
        _draw_suit_shape(surf, 'diamond', cx, cy, min(w, h) * 0.5, color)

    elif kind == 'club':
        # Card suit — used in place of the U+2663 glyph (same coverage
        # problem as the other three suits above).
        _draw_suit_shape(surf, 'club', cx, cy, min(w, h) * 0.46, color)

    elif kind == 'jester_hat':
        # Joker card decoration — a jester cap instead of a plain star.
        _draw_suit_shape(surf, 'jester_hat', cx, cy, min(w, h) * 0.5, color)

    elif kind == 'thumbs_up':
        # Chat quick-reaction — a simple thumbs-up, drawn as shapes
        # rather than the U+1F44D emoji, which this project's bundled
        # Poppins font has NO glyph for at all (unlike the arrows/stars
        # above, this isn't a "some fonts miss it" case — pygame loads
        # this exact ttf file directly with no system emoji-font
        # fallback, so an actual emoji character is guaranteed tofu on
        # every platform, not just some).
        s = min(w, h)
        fist = pygame.Rect(0, 0, s * 0.42, s * 0.40)
        fist.midbottom = (cx + s * 0.06, cy + s * 0.32)
        pygame.draw.rect(surf, color, fist, border_radius=int(s * 0.08))
        thumb_pts = [
            (cx - s * 0.06, cy + s * 0.02),
            (cx - s * 0.06, cy - s * 0.30),
            (cx + s * 0.08, cy - s * 0.42),
            (cx + s * 0.20, cy - s * 0.30),
            (cx + s * 0.20, cy + s * 0.02),
        ]
        pygame.draw.polygon(surf, color, thumb_pts)

    elif kind == 'face_laugh':
        # Chat quick-reaction — round face, closed curved-up eyes, wide
        # open laughing mouth. Same "guaranteed tofu, so draw it"
        # reasoning as 'thumbs_up' above.
        r = min(w, h) * 0.46
        pygame.draw.circle(surf, color, (cx, cy), r, width)
        for dx in (-r * 0.42, r * 0.42):
            arc_rect = pygame.Rect(0, 0, r * 0.5, r * 0.4)
            arc_rect.center = (cx + dx, cy - r * 0.18)
            pygame.draw.arc(surf, color, arc_rect, 3.3, 6.1, width)
        mouth_rect = pygame.Rect(0, 0, r * 1.1, r * 0.9)
        mouth_rect.center = (cx, cy + r * 0.12)
        pygame.draw.arc(surf, color, mouth_rect, 3.6, 5.85, width + 1)

    elif kind == 'face_wow':
        # Chat quick-reaction — round face, round eyes, round open
        # "O" mouth. Same reasoning as 'thumbs_up' above.
        r = min(w, h) * 0.46
        pygame.draw.circle(surf, color, (cx, cy), r, width)
        eye_r = max(1, r * 0.09)
        for dx in (-r * 0.36, r * 0.36):
            pygame.draw.circle(surf, color, (cx + dx, cy - r * 0.20), eye_r)
        pygame.draw.circle(surf, color, (cx, cy + r * 0.28), r * 0.24, width)

    elif kind == 'face_angry':
        # Chat quick-reaction — round face, angled "V" eyebrows, flat
        # mouth. Same reasoning as 'thumbs_up' above.
        r = min(w, h) * 0.46
        pygame.draw.circle(surf, color, (cx, cy), r, width)
        for dx, tilt in ((-1, 1), (1, -1)):
            bx = cx + dx * r * 0.40
            pygame.draw.line(surf, color,
                             (bx - r * 0.20, cy - r * 0.14 + tilt * r * 0.06),
                             (bx + r * 0.20, cy - r * 0.14 - tilt * r * 0.06), width + 1)
        pygame.draw.line(surf, color, (cx - r * 0.28, cy + r * 0.30),
                         (cx + r * 0.28, cy + r * 0.30), width + 1)

    elif kind == 'twitter':
        # X/Twitter's current wordmark logo is just a bold X — drawn as
        # two thick crossing bars (not two thin lines like the generic
        # 'close'/'cross' glyphs above) since the real logo reads as
        # solid strokes even at small icon sizes. Same "plain vector
        # instead of a missing/blurry glyph" reasoning as the rest of
        # this function; also sidesteps bundling a trademarked logo
        # image asset.
        pad_x, pad_y = w * 0.22, h * 0.22
        bar_w = max(2, int(min(w, h) * 0.16))
        pygame.draw.line(surf, color, (rect.left + pad_x, rect.top + pad_y),
                         (rect.right - pad_x, rect.bottom - pad_y), bar_w)
        pygame.draw.line(surf, color, (rect.right - pad_x, rect.top + pad_y),
                         (rect.left + pad_x, rect.bottom - pad_y), bar_w)

    elif kind == 'email':
        # Simple envelope: outer rect + a "V" flap line — the universal
        # cross-platform email glyph, drawn as shapes for the same
        # missing-glyph reasons as everything else here.
        env = pygame.Rect(0, 0, w * 0.72, h * 0.52)
        env.center = (cx, cy)
        pygame.draw.rect(surf, color, env, width=width, border_radius=1)
        pygame.draw.line(surf, color, env.topleft,
                         (env.centerx, env.centery + env.height * 0.08), width)
        pygame.draw.line(surf, color, env.topright,
                         (env.centerx, env.centery + env.height * 0.08), width)

    elif kind == 'linkedin':
        # LinkedIn's mark is a lowercase "in" — approximated with plain
        # shapes (a dot + stem for the "i", a stem + loop for the "n")
        # rather than relying on the bundled font actually having a
        # bold-enough "in" at icon size, and rather than bundling the
        # trademarked square-logo image asset.
        stem_w = max(2, int(min(w, h) * 0.14))
        i_x = cx - w * 0.16
        i_top = cy - h * 0.14
        i_bottom = cy + h * 0.26
        pygame.draw.line(surf, color, (i_x, i_top), (i_x, i_bottom), stem_w)
        pygame.draw.circle(surf, color, (i_x, cy - h * 0.28), max(2, stem_w * 0.7))
        n_x = cx + w * 0.10
        n_top = cy - h * 0.14
        n_bottom = cy + h * 0.26
        pygame.draw.line(surf, color, (n_x, n_top), (n_x, n_bottom), stem_w)
        arc_rect = pygame.Rect(0, 0, w * 0.30, h * 0.42)
        arc_rect.midtop = (n_x, n_top)
        pygame.draw.arc(surf, color, arc_rect, -1.57, 1.57, stem_w)
        pygame.draw.line(surf, color, (n_x + w * 0.15, cy),
                         (n_x + w * 0.15, i_bottom), stem_w)


def _heart_curve_points(n: int = 48) -> List[Tuple[float, float]]:
    """A single smooth closed curve (the standard heart parametric
    equation), point-down/lobes-up, normalized to roughly a unit circle
    of radius 1. Used as the basis for both 'heart' and (flipped)
    'spade' — one continuous curve anti-aliases and scales cleanly,
    unlike two circles + a triangle glued together which showed visible
    seams and asymmetry ('crooked', 'grainy') at small card sizes."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        hx = 16 * (math.sin(t) ** 3)
        hy = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((hx / 17.0, -hy / 17.0))
    return pts


def _draw_suit_shape(surf: pygame.Surface, kind: str, cx: float, cy: float,
                     s: float, color):
    """Draws one playing-card suit as smooth anti-aliased vector art.
    Rendered at 4x scale onto a scratch surface with pygame.gfxdraw
    (which anti-aliases) and then downscaled — supersampling like this
    keeps the edges clean even at the small sizes cards need, instead of
    the jagged/grainy look plain pygame.draw shapes had there."""
    import pygame.gfxdraw as gfx
    SS = 4
    size = max(4, int(s * 2.6))
    ss_size = size * SS
    ss = pygame.Surface((ss_size, ss_size), pygame.SRCALPHA)
    scx, scy = ss_size / 2, ss_size / 2
    scale = s * SS
    col = (*color[:3], 255) if len(color) == 3 else color

    def poly(pts):
        gfx.filled_polygon(ss, pts, col)
        gfx.aapolygon(ss, pts, col)

    def circle(x, y, r):
        x, y, r = int(x), int(y), max(1, int(r))
        gfx.filled_circle(ss, x, y, r, col)
        gfx.aacircle(ss, x, y, r, col)

    if kind == 'heart':
        pts = [(scx + hx * scale, scy + hy * scale) for hx, hy in _heart_curve_points()]
        poly(pts)

    elif kind == 'spade':
        pts = [(scx + hx * scale * 0.95, scy - hy * scale * 0.95) for hx, hy in _heart_curve_points()]
        poly(pts)
        stem = [(scx - 0.10*scale, scy + 0.55*scale), (scx + 0.10*scale, scy + 0.55*scale),
                (scx, scy + 0.95*scale)]
        poly(stem)

    elif kind == 'diamond':
        pts = [(scx, scy - scale), (scx + scale*0.62, scy), (scx, scy + scale),
              (scx - scale*0.62, scy)]
        poly(pts)

    elif kind == 'club':
        r = scale * 0.40
        for ang_deg, dist in [(270, 0.42), (30, 0.42), (150, 0.42)]:
            ang = math.radians(ang_deg)
            circle(scx + dist*scale*math.cos(ang), scy + dist*scale*math.sin(ang), r)
        stem = [(scx - 0.10*scale, scy + 0.30*scale), (scx + 0.10*scale, scy + 0.30*scale),
                (scx, scy + 0.85*scale)]
        poly(stem)

    elif kind == 'jester_hat':
        # A classic 3-point jester/joker cap silhouette — used in place of
        # the plain star on the Joker card face, pure vector so there's no
        # downloaded-image licensing question.
        brim = [(scx - scale, scy + 0.50*scale), (scx + scale, scy + 0.50*scale),
               (scx + 0.82*scale, scy + 0.68*scale), (scx - 0.82*scale, scy + 0.68*scale)]
        poly(brim)
        centre_pt = [(scx - 0.20*scale, scy + 0.52*scale), (scx + 0.20*scale, scy + 0.52*scale),
                    (scx, scy - 0.92*scale)]
        poly(centre_pt)
        left_pt = [(scx - 0.85*scale, scy + 0.55*scale), (scx - 0.18*scale, scy + 0.55*scale),
                  (scx - 0.68*scale, scy - 0.55*scale)]
        poly(left_pt)
        right_pt = [(scx + 0.85*scale, scy + 0.55*scale), (scx + 0.18*scale, scy + 0.55*scale),
                   (scx + 0.68*scale, scy - 0.55*scale)]
        poly(right_pt)
        for bx, by in [(scx, scy - 0.92*scale), (scx - 0.68*scale, scy - 0.55*scale),
                       (scx + 0.68*scale, scy - 0.55*scale)]:
            circle(bx, by, scale * 0.15)

    small = pygame.transform.smoothscale(ss, (size, size))
    surf.blit(small, (cx - size/2, cy - size/2))


def render_cards_inline(font: pygame.font.Font, cards, color,
                        sep: str = " + ") -> pygame.Surface:
    """Renders a list of Card objects as one inline strip — e.g. the
    'Selected: 9 + 9' HUD line — with each suit drawn as the real vector
    icon instead of embedding the card's Unicode SUIT_SYMBOL glyph in a
    single font.render() string. This project's body font (Poppins)
    doesn't include the card-suit Unicode block at all, so that glyph
    rendered as a tofu box; this composites rank-text + icon + rank-text
    surfaces side by side instead, the same fix already applied to card
    faces, the suit picker, and the current-suit indicator."""
    icon_size = max(10, font.get_height() - 4)
    sep_surf = font.render(sep, True, color) if sep else None

    parts: List[pygame.Surface] = []
    for i, c in enumerate(cards):
        if i > 0 and sep_surf is not None:
            parts.append(sep_surf)
        parts.append(font.render(c.display_rank, True, color))
        if c.suit is not None:
            icon = pygame.Surface((icon_size, icon_size), pygame.SRCALPHA)
            draw_icon(icon, icon.get_rect(), SUIT_ICON[c.suit], color, width=2)
            parts.append(icon)

    if not parts:
        return pygame.Surface((1, font.get_height()), pygame.SRCALPHA)

    total_w = sum(p.get_width() for p in parts) + len(parts)
    total_h = max(p.get_height() for p in parts)
    out = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
    x = 0
    for p in parts:
        out.blit(p, (x, (total_h - p.get_height()) // 2))
        x += p.get_width() + 1
    return out


def draw_shadow(surf: pygame.Surface, rect: pygame.Rect, radius: int,
                color=SHADOW_COLOR, alpha: int = SHADOW_ALPHA,
                offset: Tuple[int, int] = SHADOW_OFFSET):
    """One shared soft drop-shadow, used by both Panel and Button so every
    raised UI element in the game reads with the same depth/opacity instead
    of each widget hand-tuning its own shadow."""
    shadow_rect = rect.move(*offset)
    s = pygame.Surface((shadow_rect.width, shadow_rect.height), pygame.SRCALPHA)
    pygame.draw.rect(s, (*color, alpha), s.get_rect(), border_radius=radius)
    surf.blit(s, shadow_rect.topleft)


def _shade(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def draw_gradient_rounded_rect(surf: pygame.Surface, rect: pygame.Rect,
                               top_color, bottom_color, radius: int,
                               alpha: int = 255):
    """A soft vertical gradient fill clipped to a rounded rect — used by
    Button and Panel (Phase 5) instead of a single flat color, for a bit of
    depth without needing any external asset."""
    import numpy as np
    w, h = max(1, rect.width), max(1, rect.height)
    t = np.linspace(0.0, 1.0, h).reshape(h, 1)
    grad = np.zeros((h, w, 3), dtype=np.uint8)
    for ch in range(3):
        top_c, bot_c = top_color[ch], bottom_color[ch]
        grad[:, :, ch] = np.clip(top_c + (bot_c - top_c) * t, 0, 255).astype(np.uint8)
    grad_surf = pygame.surfarray.make_surface(grad.swapaxes(0, 1))
    grad_surf = grad_surf.convert_alpha()
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    grad_surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    if alpha < 255:
        grad_surf.set_alpha(alpha)
    surf.blit(grad_surf, rect.topleft)


def draw_rounded_rect(surf: pygame.Surface, color, rect, radius: int,
                      border_color=None, border_width: int = 0, alpha: int = 255):
    """Draw a rounded rectangle with optional border."""
    if isinstance(color, (list, tuple)) and len(color) == 4:
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
        surf.blit(s, rect.topleft)
    else:
        pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border_color and border_width:
        pygame.draw.rect(surf, border_color, rect, width=border_width, border_radius=radius)


class Button:
    def __init__(self, rect: pygame.Rect, text: str, font: pygame.font.Font,
                 color=BTN_NORMAL, hover_color=BTN_HOVER, press_color=BTN_PRESSED,
                 text_color=BTN_TEXT, radius: int = RADIUS_BUTTON,
                 on_click: Optional[Callable] = None,
                 icon: Optional[str] = None, tooltip: str = ""):
        self.rect        = rect
        self.text        = text
        self.font        = font
        self.color       = color
        self.hover_color = hover_color
        self.press_color = press_color
        self.text_color  = text_color
        self.radius      = radius
        self.on_click    = on_click
        self.icon        = icon
        self.tooltip     = tooltip
        self.enabled     = True
        self.visible     = True
        self._hovered    = False
        self._pressed    = False
        self._anim_t     = 0.0  # hover animation progress

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled or not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = True
                return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._pressed and self.rect.collidepoint(event.pos):
                self._pressed = False
                if self.on_click:
                    self.on_click()
                return True
            self._pressed = False
        return False

    def update(self, dt: float, mouse_pos: Tuple[int, int]):
        if not self.visible:
            return
        self._hovered = self.rect.collidepoint(mouse_pos) and self.enabled
        target = 1.0 if self._hovered else 0.0
        self._anim_t += (target - self._anim_t) * min(dt * 10, 1.0)

    def draw(self, surf: pygame.Surface):
        if not self.visible:
            return
        # Color blend
        if not self.enabled:
            col = BTN_DISABLED
        elif self._pressed:
            col = self.press_color
        else:
            t = self._anim_t
            col = tuple(int(self.color[i] + (self.hover_color[i] - self.color[i]) * t)
                        for i in range(3))

        # Shadow
        draw_shadow(surf, self.rect, self.radius)

        # Body — soft top-lighter/bottom-darker gradient instead of a flat fill
        draw_gradient_rounded_rect(surf, self.rect, _shade(col, 1.18), _shade(col, 0.82),
                                   self.radius)

        # Highlight top edge
        h_rect = pygame.Rect(self.rect.x + 2, self.rect.y + 2,
                             self.rect.width - 4, 3)
        pygame.draw.rect(surf, BORDER_LIGHT, h_rect, border_radius=2)

        # Border
        pygame.draw.rect(surf, BORDER_LIGHT, self.rect, width=1, border_radius=self.radius)

        # Text — shrunk to fit the button width if needed, so a longer
        # label (e.g. "Local Multiplayer") never overflows past the edges
        # regardless of which font/size the button was given.
        label = f"{self.icon} {self.text}" if self.icon else self.text
        text_surf = self.font.render(label, True, self.text_color)
        max_w = self.rect.width - 16
        if text_surf.get_width() > max_w > 0:
            scale = max_w / text_surf.get_width()
            new_size = (max_w, max(1, int(text_surf.get_height() * scale)))
            text_surf = pygame.transform.smoothscale(text_surf, new_size)
        tx = self.rect.centerx - text_surf.get_width() // 2
        ty = self.rect.centery - text_surf.get_height() // 2
        if self._pressed:
            ty += 1
        surf.blit(text_surf, (tx, ty))


class Panel:
    def __init__(self, rect: pygame.Rect, color=UI_PANEL,
                 border_color=None, radius: int = RADIUS_PANEL,
                 alpha: int = PANEL_BG_ALPHA):
        self.rect  = rect
        self.color = color
        self.border_color = border_color or BORDER_ACCENT
        self.radius = radius
        self.alpha  = alpha

    def draw(self, surf: pygame.Surface):
        draw_shadow(surf, self.rect, self.radius)
        s = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        draw_gradient_rounded_rect(s, s.get_rect(), _shade(self.color, 1.12),
                                   _shade(self.color, 0.90), self.radius, alpha=self.alpha)
        pygame.draw.rect(s, self.border_color, s.get_rect(), width=1, border_radius=self.radius)
        surf.blit(s, self.rect.topleft)


class SuitPicker:
    """Overlay to pick a suit when A card is played."""
    def __init__(self, screen_w: int, screen_h: int, font: pygame.font.Font,
                 on_pick: Callable[[Suit], None], scale: float = 1.0):
        self.on_pick  = on_pick
        self.visible  = False
        self.font     = font
        self.scale    = scale
        self._buttons: List[Tuple[pygame.Rect, Suit]] = []
        self._hovered: Optional[Suit] = None

        s = self._s
        bw, bh = s(140), s(100)
        gap     = s(20)
        total_w = 4 * bw + 3 * gap
        sx      = (screen_w - total_w) // 2
        sy      = (screen_h - bh) // 2

        for i, suit in enumerate(Suit):
            rx = sx + i * (bw + gap)
            self._buttons.append((pygame.Rect(rx, sy, bw, bh), suit))

        # Overlay panel
        pad = s(40)
        panel_rect = pygame.Rect(sx - pad, sy - s(60), total_w + 2 * pad, bh + s(120))
        self._panel = Panel(panel_rect, color=(20, 40, 60))
        self._title_font = font

    def _s(self, px: float) -> int:
        return round(px * self.scale)

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.visible:
            return False
        if event.type == pygame.MOUSEMOTION:
            self._hovered = None
            for rect, suit in self._buttons:
                if rect.collidepoint(event.pos):
                    self._hovered = suit
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, suit in self._buttons:
                if rect.collidepoint(event.pos):
                    self.hide()
                    self.on_pick(suit)
                    return True
        return False

    def draw(self, surf: pygame.Surface):
        if not self.visible:
            return
        # Dim overlay
        dim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(dim, (0, 0))

        self._panel.draw(surf)

        # Title
        title = self._title_font.render("Choose a suit", True, GOLD_LIGHT)
        tx = self._panel.rect.centerx - title.get_width() // 2
        surf.blit(title, (tx, self._panel.rect.y + self._s(10)))

        for rect, suit in self._buttons:
            hovered = (suit == self._hovered)
            accent = SUIT_ACCENT[suit]
            bg_col = (*accent, 200) if hovered else (*accent, 130)

            s2 = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(s2, bg_col, s2.get_rect(), border_radius=self._s(14))
            if hovered:
                pygame.draw.rect(s2, (*GOLD_LIGHT, 200), s2.get_rect(), width=2, border_radius=self._s(14))
            else:
                pygame.draw.rect(s2, (*WHITE, 60), s2.get_rect(), width=1, border_radius=self._s(14))
            surf.blit(s2, rect.topleft)

            sym_size = self._s(36)
            sym = pygame.Surface((sym_size, sym_size), pygame.SRCALPHA)
            draw_icon(sym, sym.get_rect(), SUIT_ICON[suit], WHITE, width=3)
            sx2 = rect.centerx - sym.get_width() // 2
            surf.blit(sym, (sx2, rect.y + self._s(14)))

            name_surf = self.font.render(suit.value, True, WHITE)
            nx = rect.centerx - name_surf.get_width() // 2
            surf.blit(name_surf, (nx, rect.y + self._s(60)))


GOLD_LIGHT = (255, 215, 0)


class MessageBanner:
    """Floating animated message displayed on screen."""
    def __init__(self, text: str, color=GOLD_LIGHT, duration: float = 2.0,
                 font: Optional[pygame.font.Font] = None, y: int = 80):
        self.text     = text
        self.color    = color
        self.duration = duration
        self.elapsed  = 0.0
        self.done     = False
        self.font     = font
        self.y        = y

    def update(self, dt: float):
        self.elapsed += dt
        if self.elapsed >= self.duration:
            self.done = True

    def draw(self, surf: pygame.Surface):
        if self.done or not self.font:
            return
        t = self.elapsed / self.duration
        # Fade in 0-0.15, hold, fade out 0.75-1.0
        if t < 0.15:
            alpha = int((t / 0.15) * 255)
        elif t > 0.75:
            alpha = int(((1.0 - t) / 0.25) * 255)
        else:
            alpha = 255

        # Rise effect
        rise = int((1.0 - t) * 20) if t > 0.5 else 0

        text_surf = self.font.render(self.text, True, self.color)
        text_surf.set_alpha(alpha)
        x = surf.get_width() // 2 - text_surf.get_width() // 2
        y = self.y - rise
        surf.blit(text_surf, (x, y))


class KADIBanner:
    """The big KADI! declaration screen effect."""
    def __init__(self, player_name: str, screen_w: int, screen_h: int,
                 font_large: pygame.font.Font, font_small: pygame.font.Font):
        self.player_name = player_name
        self.sw = screen_w
        self.sh = screen_h
        self.font_large = font_large
        self.font_small = font_small
        self.elapsed = 0.0
        self.duration = 2.0
        self.done = False

    def update(self, dt: float):
        self.elapsed += dt
        if self.elapsed >= self.duration:
            self.done = True

    def draw(self, surf: pygame.Surface):
        if self.done:
            return
        t = self.elapsed / self.duration
        if t < 0.1:
            alpha = int((t / 0.1) * 255)
        elif t > 0.7:
            alpha = int(((1.0 - t) / 0.3) * 255)
        else:
            alpha = 255

        scale = 1.0 + 0.3 * math.sin(t * math.pi)
        s = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)

        kadi_surf = self.font_large.render("KADI!", True, KADI_COLOR)
        kw = int(kadi_surf.get_width() * scale)
        kh = int(kadi_surf.get_height() * scale)
        kadi_scaled = pygame.transform.smoothscale(kadi_surf, (kw, kh))
        kadi_scaled.set_alpha(alpha)
        s.blit(kadi_scaled, (self.sw // 2 - kw // 2, self.sh // 2 - kh // 2 - 20))

        sub_surf = self.font_small.render(f"{self.player_name} declares KADI!", True, WHITE)
        sub_surf.set_alpha(alpha)
        s.blit(sub_surf, (self.sw // 2 - sub_surf.get_width() // 2,
                          self.sh // 2 + kh // 2 - 10))
        surf.blit(s, (0, 0))


KADI_COLOR = (220, 50, 50)


def draw_trophy_icon(surf: pygame.Surface, cx: float, cy: float, scale: float = 1.0,
                     color: Tuple[int, int, int] = GOLD_LIGHT):
    """Small vector-drawn trophy (cup + handles + stem + base), centered
    at (cx, cy). Deliberately NOT a Unicode emoji glyph — this project's
    fonts can't reliably render color emoji, so every UI symbol here is
    hand-drawn with pygame.draw calls instead, same as the rest of the
    game's iconography."""
    def pt(x, y):
        return (cx + x * scale, cy + y * scale)

    bowl = [pt(-14, -18), pt(14, -18), pt(10, -3), pt(4, 7), pt(-4, 7), pt(-10, -3)]
    pygame.draw.polygon(surf, color, bowl)
    pygame.draw.polygon(surf, (255, 255, 255), bowl, width=max(1, int(1 * scale)))

    stem = pygame.Rect(0, 0, int(6 * scale), int(9 * scale))
    stem.center = pt(0, 11)
    pygame.draw.rect(surf, color, stem)

    base = pygame.Rect(0, 0, int(22 * scale), int(6 * scale))
    base.center = pt(0, 18)
    pygame.draw.rect(surf, color, base, border_radius=max(1, int(2 * scale)))

    handle_w = max(2, int(3 * scale))
    left_rect = pygame.Rect(0, 0, int(16 * scale), int(20 * scale))
    left_rect.center = pt(-19, -8)
    pygame.draw.arc(surf, color, left_rect, math.radians(-100), math.radians(100), handle_w)
    right_rect = pygame.Rect(0, 0, int(16 * scale), int(20 * scale))
    right_rect.center = pt(19, -8)
    pygame.draw.arc(surf, color, right_rect, math.radians(80), math.radians(280), handle_w)


class WinScreen:
    """Full win screen overlay."""
    def __init__(self, winner_name: str, screen_w: int, screen_h: int,
                 font_large: pygame.font.Font, font_med: pygame.font.Font,
                 font_small: pygame.font.Font, standings: Optional[list] = None,
                 scale: float = 1.0):
        self.winner_name = winner_name
        self.sw, self.sh = screen_w, screen_h
        self.font_large = font_large
        self.font_med   = font_med
        self.font_small = font_small
        # Chrome scale for every FIXED-pixel dimension in this screen
        # (button sizes, gaps, padding) — matches constants.py's
        # UI_SCALE_PROFILES button_scale exactly (same value as
        # font_scale there, by that table's own design). The caller
        # (scenes.py's _show_win_screen) is expected to pass in fonts
        # ALREADY built at the matching scale via
        # AssetLoader.font_scaled(), same convention BoardRenderer and
        # the Settings/Rules panel already use — this class only needs
        # the number itself to scale its OWN geometry (button boxes,
        # gaps) to match, so scaled-up text never ends up overflowing
        # a still-fixed-size button. Defaults to 1.0 (today's fixed
        # sizing, unchanged) for any caller that doesn't pass one.
        self.scale = scale
        self.elapsed    = 0.0
        self._particles = self._make_particles()
        self.play_again_btn: Optional[Button] = None
        self.menu_btn: Optional[Button] = None
        self.share_btn: Optional[Button] = None
        # Set by the caller after a Share-platform click resolves (see
        # scenes.py's _on_share_win) — a short status line ("Saved to
        # .../KADI Shares — opening share window...") drawn just below
        # the platform row so the person gets feedback right here
        # rather than needing to go look for a toast elsewhere.
        self.share_status: str = ""
        # Set by draw() each time it renders share_status — see that
        # code's own comment for why tests should read this rather
        # than re-deriving the same values themselves.
        self._last_status_render: Optional[dict] = None
        # Clicking the main "Share" button toggles a small row of
        # per-platform buttons (X/Twitter, WhatsApp, Telegram, Reddit,
        # Email — see core/social_share.py's SHARE_PLATFORMS for why
        # this specific list and not literally every network) rather
        # than immediately opening one hardcoded platform.
        self.share_expanded: bool = False
        self._share_platform_buttons: List[Tuple[str, Button]] = []
        # Elimination Mode: ordered list of "N. Name" strings for the
        # full round standings, shown under the winner's name. None (or
        # empty) for a standard single-winner game — no standings block.
        self.standings = standings or []
        # Extra shrink applied ONLY to the fixed vertical gaps between
        # blocks (name/standings -> buttons -> Share -> platform rows),
        # never to button sizes or fonts — computed by setup_buttons()
        # for short screens where standings + an expanded Share row
        # would otherwise leave no room below the last platform button
        # for the status message draw() renders itself. See
        # setup_buttons()'s own comment for the real screenshot this
        # was found from. 1.0 (no extra shrink) whenever there's
        # enough room without it.
        self._compact: float = 1.0

    def _s(self, px: float) -> int:
        """Scale a fixed-pixel design constant by self.scale, same
        rounding convention used throughout — every hardcoded gap/size
        in this class is expressed as its ORIGINAL 1280x800-baseline
        pixel value passed through this, so the whole screen grows or
        shrinks together instead of fonts scaling while gaps/buttons
        stay frozen at baseline size."""
        return round(px * self.scale)

    def _cs(self, px: float) -> int:
        """Same as self._s(), plus self._compact — use this (not _s())
        for the vertical GAPS between the name/standings block, the
        Play Again/Main Menu row, the Share button, and the
        share-platform rows, so setup_buttons()'s short-screen shrink
        and draw()'s standings loop can never drift out of sync about
        how much room those gaps actually take up this frame."""
        return round(px * self.scale * self._compact)

    def _make_particles(self):
        import random
        particles = []
        for _ in range(60):
            particles.append({
                'x': random.randint(0, self.sw),
                'y': random.randint(-50, self.sh),
                'vx': random.uniform(-30, 30),
                'vy': random.uniform(40, 120),
                'color': random.choice([GOLD_LIGHT, (255, 100, 100), (100, 200, 100),
                                        (100, 150, 255), (255, 180, 50)]),
                'size': random.randint(4, 10),
                'rot': random.uniform(0, 360),
                'rot_speed': random.uniform(-120, 120),
            })
        return particles

    def setup_buttons(self, font: pygame.font.Font,
                      on_play_again: Callable, on_menu: Callable,
                      on_share: Optional[Callable[[str], None]] = None):
        bw, bh = self._s(200), self._s(50)
        name_h = self.font_med.render(self.winner_name, True, GOLD_LIGHT).get_height()

        # Precompute the share-platform row layout (needed either way,
        # to know how many rows it wraps into) before deciding
        # self._compact — see that attribute's own docstring for why.
        share_bw, share_bh = self._s(180), self._s(42)
        plat_bw, plat_bh = self._s(118), self._s(34)
        margin = self._s(30)
        max_row_w = self.sw - 2 * margin
        gap = self._s(10)
        per_row = max(1, (max_row_w + gap) // (plat_bw + gap))
        n_share_rows = -(-len(SHARE_UI_OPTIONS) // per_row) if on_share is not None else 0

        # How much room the WHOLE stack below the name/trophy needs at
        # full (uncompressed) size: standings block, the +20/+20 gaps
        # around it, the Play Again/Main Menu row, and — if Share is
        # offered — the Share button plus every platform row. Compared
        # against what's actually left on a short screen so the fixed
        # gaps (never the button sizes or fonts) can be shrunk together
        # when it doesn't fit, rather than silently handing draw() a
        # status-message position with no room left at all. Found from
        # a real screenshot at 1024x640 with 4-player standings + Share
        # expanded: the last platform button already ended only ~40px
        # above the bottom edge, before any status text was even added.
        standings_block_h = (self._s(24) * min(len(self.standings), 6) + self._s(30)) if self.standings else 0
        pre_button_gap = self._s(20) + standings_block_h + self._s(20)
        stack_h = bh
        if on_share is not None:
            stack_h += self._s(14) + share_bh + self._s(10)
            stack_h += n_share_rows * plat_bh + max(0, n_share_rows - 1) * gap
        # Room for the "Saved ... " status message draw() renders below
        # the stack: ~2 lines at font_small's height plus a comfortable
        # margin — not exact (draw() re-wraps for the real message,
        # which can still run to 3 lines in extreme cases), just a
        # reasonable middle ground: generous enough to fix the real
        # reported overflow (4-player standings + Share expanded at
        # 1024x640), without over-triggering the shrink for shorter,
        # more common messages that would already have fit fine.
        status_room = self._s(24) + 2 * (self.font_small.get_height() + 2)

        name_top = self.sh // 2 - self._s(10) + name_h  # where the pre-button gap starts from
        needed = pre_button_gap + stack_h + status_room
        available = self.sh - name_top - self._s(20)
        self._compact = 1.0
        if self.standings and on_share is not None and needed > max(1, available):
            self._compact = max(0.45, available / needed)

        standings_block_h = (self._cs(24) * min(len(self.standings), 6) + self._cs(30)) if self.standings else 0
        cy = (self.sh // 2 - self._s(10) + name_h // 2 + name_h // 2 + self._cs(20) + standings_block_h + self._cs(20))
        self.play_again_btn = Button(
            pygame.Rect(self.sw // 2 - bw - self._s(20), cy, bw, bh),
            "Play Again", font, on_click=on_play_again
        )
        self.menu_btn = Button(
            pygame.Rect(self.sw // 2 + self._s(20), cy, bw, bh),
            "Main Menu", font,
            color=(80, 60, 140), hover_color=(110, 85, 180),
            on_click=on_menu
        )
        if on_share is not None:
            # Its own row below Play Again/Main Menu — a third
            # side-by-side button would crowd this pair on narrower
            # resolutions, and Share is a lower-priority action than
            # either of them.
            self.share_btn = Button(
                pygame.Rect(self.sw // 2 - share_bw // 2, cy + bh + self._cs(14), share_bw, share_bh),
                "Share", font,
                color=(30, 110, 160), hover_color=(45, 140, 195),
                on_click=self._toggle_share_expanded
            )
            self._on_share_platform = on_share
            self._share_platform_buttons = []
            row_y = cy + bh + self._cs(14) + share_bh + self._cs(10)
            # Wraps into as many rows as needed rather than assuming
            # everything fits on one line — SHARE_UI_OPTIONS has grown
            # past what always fits in a single row at every supported
            # resolution (see core/social_share.py for the full list).
            row_gap = self._cs(10)
            for row_i in range(n_share_rows):
                row_opts = SHARE_UI_OPTIONS[row_i * per_row:(row_i + 1) * per_row]
                row_w = len(row_opts) * plat_bw + (len(row_opts) - 1) * gap
                row_x = self.sw // 2 - row_w // 2
                ry = row_y + row_i * (plat_bh + row_gap)
                for i, (key, label) in enumerate(row_opts):
                    rect = pygame.Rect(row_x + i * (plat_bw + gap), ry, plat_bw, plat_bh)
                    btn = Button(rect, label, self.font_small,
                                color=(45, 45, 65), hover_color=(65, 65, 95),
                                on_click=(lambda k=key: self._on_share_platform(k)))
                    self._share_platform_buttons.append((key, btn))


    def _toggle_share_expanded(self):
        self.share_expanded = not self.share_expanded

    def handle_event(self, event):
        if self.play_again_btn:
            self.play_again_btn.handle_event(event)
        if self.menu_btn:
            self.menu_btn.handle_event(event)
        if self.share_btn:
            self.share_btn.handle_event(event)
        if self.share_expanded:
            for _key, btn in self._share_platform_buttons:
                btn.handle_event(event)

    def update(self, dt: float, mouse_pos):
        self.elapsed += dt
        import random
        for p in self._particles:
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            p['rot'] += p['rot_speed'] * dt
            if p['y'] > self.sh + 20:
                p['y'] = random.randint(-40, 0)
                p['x'] = random.randint(0, self.sw)
        if self.play_again_btn:
            self.play_again_btn.update(dt, mouse_pos)
        if self.menu_btn:
            self.menu_btn.update(dt, mouse_pos)
        if self.share_btn:
            self.share_btn.update(dt, mouse_pos)
        if self.share_expanded:
            for _key, btn in self._share_platform_buttons:
                btn.update(dt, mouse_pos)

    def draw(self, surf: pygame.Surface):
        # Dark overlay
        overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(overlay, (0, 0))

        # Particles
        for p in self._particles:
            s = pygame.Surface((p['size'], p['size']), pygame.SRCALPHA)
            pygame.draw.rect(s, (*p['color'], 200), s.get_rect())
            rs = pygame.transform.rotate(s, p['rot'])
            surf.blit(rs, (int(p['x']), int(p['y'])))

        t = min(self.elapsed / 0.5, 1.0)
        scale = 0.5 + 0.5 * t

        win_surf = self.font_large.render("WINNER!", True, GOLD_LIGHT)
        ws = int(win_surf.get_width() * scale)
        wh = int(win_surf.get_height() * scale)
        win_scaled = pygame.transform.smoothscale(win_surf, (ws, wh))
        surf.blit(win_scaled, (self.sw // 2 - ws // 2, self.sh // 2 - wh - self._s(40)))

        name_scale = 1.0 + 0.04 * math.sin(self.elapsed * 2.2)
        base_name_surf = self.font_med.render(self.winner_name, True, GOLD_LIGHT)
        nw = max(1, int(base_name_surf.get_width() * name_scale))
        nh = max(1, int(base_name_surf.get_height() * name_scale))
        name_scaled = pygame.transform.smoothscale(base_name_surf, (nw, nh))
        name_cx = self.sw // 2
        name_cy = self.sh // 2 - self._s(10) + base_name_surf.get_height() // 2
        trophy_scale = (nh / 40.0) * 1.15

        # Banner behind the name so it reads as a distinct "prize" block
        # rather than blending into the confetti/particles above it.
        banner_w = nw + self._s(170)
        banner_h = nh + self._s(26)
        banner = pygame.Surface((banner_w, banner_h), pygame.SRCALPHA)
        pygame.draw.rect(banner, (40, 30, 0, 150),
                         banner.get_rect(), border_radius=banner_h // 2)
        pygame.draw.rect(banner, (*GOLD_LIGHT, 200),
                         banner.get_rect(), width=2, border_radius=banner_h // 2)
        surf.blit(banner, (name_cx - banner_w // 2, name_cy - banner_h // 2))

        # Soft gold glow behind the name text itself (several offset
        # copies in a dimmer gold, same trick MainMenuScene uses for its
        # "KADI" title), THEN the crisp gold text on top.
        for ox, oy in [(2, 0), (-2, 0), (0, 2), (0, -2)]:
            glow = pygame.transform.smoothscale(
                self.font_med.render(self.winner_name, True, (140, 100, 0)), (nw, nh))
            surf.blit(glow, (name_cx - nw // 2 + ox, name_cy - nh // 2 + oy))
        surf.blit(name_scaled, (name_cx - nw // 2, name_cy - nh // 2))

        draw_trophy_icon(surf, name_cx - nw // 2 - self._s(34), name_cy, scale=trophy_scale)
        draw_trophy_icon(surf, name_cx + nw // 2 + self._s(34), name_cy, scale=trophy_scale)

        if self.standings:
            sy = name_cy + nh // 2 + self._cs(30)
            for line in self.standings:
                ls = self.font_small.render(line, True, (215, 220, 210))
                surf.blit(ls, (self.sw // 2 - ls.get_width() // 2, sy))
                sy += self._cs(24)

        if self.play_again_btn:
            self.play_again_btn.draw(surf)
        if self.menu_btn:
            self.menu_btn.draw(surf)
        if self.share_btn:
            self.share_btn.draw(surf)
            if self.share_expanded:
                for _key, btn in self._share_platform_buttons:
                    btn.draw(surf)
                status_y = max(btn.rect.bottom for _k, btn in self._share_platform_buttons) + self._s(8) \
                    if self._share_platform_buttons else self.share_btn.rect.bottom + self._s(8)
            else:
                status_y = self.share_btn.rect.bottom + self._s(8)
            if self.share_status:
                # Wrapped (not a single unbroken line — a real save
                # path plus the surrounding sentence routinely runs
                # well past 1024px) — max_text_w scales with self.scale
                # too, since font_small itself is bigger at higher
                # resolutions (see scenes.py's _show_win_screen, which
                # passes AssetLoader.font_scaled() fonts here), so a
                # fixed 700px cap would fit fewer characters per line as
                # the font grows, needing MORE lines right when there's
                # proportionally less room for them. Scaling the cap
                # keeps roughly the same character count per line at
                # every resolution.
                margin = self._s(10)
                base_max_w = min(self.sw - self._s(80), self._s(700))

                def _wrap(max_w):
                    ls = wrap_text(self.font_small, self.share_status, max_w)
                    lh = self.font_small.get_height() + 2
                    return ls, lh, lh * len(ls)

                lines, line_h, block_h = _wrap(base_max_w)
                available_below = self.sh - margin - status_y
                # If the message doesn't fit in the natural space below
                # the buttons at the "readable column" width, widen it
                # first — trading the ideal line length for fewer, wider
                # lines — before ever considering moving the text
                # itself. A too-narrow width forcing an extra line was
                # exactly what previously pushed the clamped position
                # up and INTO the button row above it (confirmed via a
                # real screenshot at 1024x640 with Elimination Mode
                # standings + the share row expanded: the 3-line wrap at
                # 700px-equivalent needed more room than was left below
                # the buttons, so the old bottom-anchored clamp
                # relocated it overlapping the still-visible, still-
                # clickable share buttons — worse than the original
                # off-screen bug this was meant to fix).
                if block_h > available_below:
                    wide_max_w = self.sw - self._s(40)
                    wide_lines, wide_line_h, wide_block_h = _wrap(wide_max_w)
                    if wide_block_h < block_h:
                        lines, line_h, block_h = wide_lines, wide_line_h, wide_block_h

                if status_y + block_h > self.sh - margin:
                    # Never move the message ABOVE its natural position
                    # (i.e. never let it climb back up into the share
                    # buttons it's reporting on). Widening the text
                    # above already handles the vast majority of cases;
                    # if it STILL doesn't fit even at full width, there
                    # simply isn't a position that's both fully on
                    # screen AND clear of the buttons — and leaving it
                    # at its natural spot, letting the last line or two
                    # trail past the bottom edge in that rare extreme
                    # case, is far more readable than the alternative
                    # this used to do: pull it upward until it overlaps
                    # the still-visible, still-clickable buttons.
                    pass
                # Exposed for tests (and any future caller) to inspect
                # the REAL values this draw actually used, instead of
                # re-deriving/duplicating this math elsewhere — a stale
                # duplicate of an earlier version of this exact clamp
                # is what let a real overlap regression here pass its
                # own test suite unnoticed; asserting against this
                # attribute instead can't drift out of sync with
                # whatever this method actually does.
                self._last_status_render = {
                    'status_y': status_y, 'lines': lines,
                    'line_h': line_h, 'block_h': block_h,
                    'buttons_bottom': (max(b.rect.bottom for _k, b in self._share_platform_buttons)
                                      if self._share_platform_buttons else self.share_btn.rect.bottom),
                }
                for i, line in enumerate(lines):
                    st = self.font_small.render(line, True, (220, 235, 245))
                    surf.blit(st, (self.sw // 2 - st.get_width() // 2, status_y + i * line_h))


class PassAndPlayOverlay:
    """Local hot-seat 'Pass and Play' interstitial (see scenes.GameplayScene
    for the full gating logic). Shown every time control passes to a
    DIFFERENT human sharing this one device, so nobody sees an opponent's
    hand — including at the very start of the game for the first player.

    Unlike SuitPicker/WinScreen's translucent dim over the table, draw()
    here fills the ENTIRE surface as a fully opaque background first —
    this must completely obscure whatever was on screen a moment ago,
    not merely darken it, since a hand could otherwise still show through
    underneath. GameplayScene additionally never renders any hand data at
    all while this is showing (belt and suspenders, not just this overlay
    being drawn on top).
    """
    def __init__(self, screen_w: int, screen_h: int,
                 font_large: pygame.font.Font, font_med: pygame.font.Font,
                 font_small: pygame.font.Font, scale: float = 1.0):
        self.sw, self.sh = screen_w, screen_h
        self.font_large = font_large
        self.font_med   = font_med
        self.font_small = font_small
        # Same convention as WinScreen's self.scale/self._s(): the
        # caller (scenes.GameplayScene.__init__) is expected to pass
        # fonts already built at this scale via
        # AssetLoader.font_scaled(name, get_chrome_scale(sw, sh)), and
        # this handles scaling its OWN fixed-pixel geometry (panel,
        # button) to match — a fixed 560x360 panel shrank to under 8%
        # of screen width/height at 7680x4320 before this, since this
        # overlay is shown on every single turn in local hot-seat play
        # (far more often than WinScreen), that was a real, frequent
        # readability problem, not a one-time one.
        self.scale = scale
        self.player_name = ""
        self.reveal_btn: Optional[Button] = None
        # All computed once in setup() (called fresh every time control
        # passes to a new player) rather than recomputed every draw()
        # frame — draw() only blits these, so there's no risk of
        # handle_event() ever reading a reveal_btn.rect that draw()
        # hasn't caught up to yet.
        self._panel: Optional[Panel] = None
        self._lead_surf = None
        self._lead_pos = (0, 0)
        self._name_surfs: List[pygame.Surface] = []
        self._name_positions: List[Tuple[int, int]] = []
        self._hint_surf = None
        self._hint_pos = (0, 0)

    def _s(self, px: float) -> int:
        return round(px * self.scale)

    def setup(self, player_name: str, on_reveal: Callable):
        """(Re)configure for the next player to be handed the device.
        Called fresh every time the target player changes, so hover/press
        state never carries over from the previous player's reveal click.

        Player names have no enforced length limit anywhere in this
        codebase, so the name is wrapped (not rendered as one unbroken
        line) and the panel itself grows to fit its actual content,
        clamped so it can never exceed the screen — the same class of
        bug WinScreen's share_status had (see that class's own
        comments), just with a name here instead of a save path.
        """
        self.player_name = player_name

        lead_text = "Pass the device to"
        hint_text = "Make sure no one else can see the screen"
        margin = self._s(40)
        max_content_w = max(self._s(200), self.sw - 2 * margin)

        lead_s = self.font_med.render(lead_text, True, (*WHITE, 210))
        hint_s = self.font_small.render(hint_text, True, (170, 176, 168))
        name_lines = wrap_text(self.font_large, player_name, max_content_w) or [""]
        name_line_h = self.font_large.get_height() + 2
        name_surfs = [self.font_large.render(l, True, GOLD_LIGHT) for l in name_lines]

        content_w = max([lead_s.get_width(), hint_s.get_width()] + [s.get_width() for s in name_surfs])
        name_block_h = name_line_h * len(name_lines)

        bw, bh = self._s(360), self._s(60)
        gap = self._s(35)
        content_h = lead_s.get_height() + gap + name_block_h + gap + hint_s.get_height() + gap + bh

        pad_x, pad_y = self._s(60), self._s(50)
        panel_w = min(max(self._s(560), content_w + 2 * pad_x), self.sw - self._s(40))
        panel_h = min(max(self._s(360), content_h + 2 * pad_y), self.sh - self._s(40))
        panel_rect = pygame.Rect(self.sw // 2 - panel_w // 2, self.sh // 2 - panel_h // 2,
                                 panel_w, panel_h)
        self._panel = Panel(panel_rect, color=(28, 34, 46), alpha=255)

        cy = panel_rect.y + pad_y
        self._lead_surf = lead_s
        self._lead_pos = (self.sw // 2 - lead_s.get_width() // 2, cy)
        cy += lead_s.get_height() + gap

        self._name_surfs = name_surfs
        self._name_positions = [(self.sw // 2 - s.get_width() // 2, cy + i * name_line_h)
                                for i, s in enumerate(name_surfs)]
        cy += name_block_h + gap

        self._hint_surf = hint_s
        self._hint_pos = (self.sw // 2 - hint_s.get_width() // 2, cy)
        cy += hint_s.get_height() + gap

        self.reveal_btn = Button(
            pygame.Rect(self.sw // 2 - bw // 2, cy, bw, bh),
            "Tap / Click to Reveal Your Hand", self.font_small,
            color=(60, 110, 60), hover_color=(80, 145, 80),
            on_click=on_reveal)

    def handle_event(self, event: pygame.event.Event):
        if self.reveal_btn:
            self.reveal_btn.handle_event(event)

    def update(self, dt: float, mouse_pos: Tuple[int, int]):
        if self.reveal_btn:
            self.reveal_btn.update(dt, mouse_pos)

    def draw(self, surf: pygame.Surface):
        # Fully opaque — see class docstring for why this can't be a
        # translucent dim like the rest of the game's overlays.
        surf.fill((14, 19, 27))

        if self._panel is None:
            return  # draw() called before setup() — shouldn't happen in practice

        self._panel.draw(surf)
        surf.blit(self._lead_surf, self._lead_pos)
        for s, pos in zip(self._name_surfs, self._name_positions):
            surf.blit(s, pos)
        surf.blit(self._hint_surf, self._hint_pos)

        if self.reveal_btn:
            self.reveal_btn.draw(surf)


# ─── Contextual "?" help overlay ────────────────────────────────────────────
# Reusable per-screen onboarding help. Each screen that wants one owns its
# own HelpOverlay instance with its own title/sections (a list of
# (heading, [paragraph, ...]) tuples) — this class only handles the generic
# "? button toggles a scrollable modal" mechanics, not any content itself.
# Modeled directly on Panel (the dim/box drawing) and RulesScene's own
# scroll-flow pattern in scenes.py (single-source-of-truth _flow(), called
# identically by draw() and the wheel/drag handlers) — kept here rather
# than in scenes.py since, unlike RulesScene, this needs to be instantiated
# fresh per-screen rather than living as its own top-level Scene.
class HelpOverlay:
    PAD = 26
    HEADING_GAP = 14
    PARA_GAP = 10
    LINE_GAP = 4
    MAX_IMAGE_H = 260

    # ── "Stuck?" idle-glow nudge on the '?' button ──────────────────────
    # If a player sits on a screen that has a HelpOverlay without doing
    # anything for IDLE_GLOW_INTERVAL seconds, the '?' button glows for
    # IDLE_GLOW_DURATION seconds — a gentle nudge in case they're stuck,
    # not an interruption (no popup, no sound, nothing blocks input).
    # Repeats every IDLE_GLOW_INTERVAL seconds of continued inactivity.
    # See update()/notice_activity()/draw_button_glow() below; the owning
    # scene is responsible for calling update() every frame and
    # notice_activity() on any real input event — see e.g.
    # ChuoScene.update()/handle_event() for the wiring pattern.
    IDLE_GLOW_INTERVAL = 30.0
    IDLE_GLOW_DURATION = 3.0

    def __init__(self, title: str, sections: List[Tuple[str, List]],
                 font_title: pygame.font.Font, font_heading: pygame.font.Font,
                 font_body: pygame.font.Font):
        """sections: list of (heading, items) tuples. Each item is either
        a plain string (wrapped as body text) or an
        ('image', pygame.Surface, caption_or_None) tuple — see _flow()."""
        self.title = title
        self.sections = sections
        self.font_title = font_title
        self.font_heading = font_heading
        self.font_body = font_body
        self.visible = False
        self.scroll = 0
        self._panel_rect = pygame.Rect(0, 0, 1, 1)
        self._close_rect = pygame.Rect(0, 0, 1, 1)
        self._content_height = 0
        self._idle_timer = 0.0
        self._glow_timer = 0.0

    def open(self):
        self.visible = True
        self.scroll = 0

    def close(self):
        self.visible = False

    def toggle(self):
        if self.visible:
            self.close()
        else:
            self.open()

    def notice_activity(self):
        """Call on any real input event on the owning screen (mouse
        motion, click, keypress) — resets the idle clock, and cancels
        an in-progress glow immediately (once the player's doing
        something, there's no point finishing the nudge)."""
        self._idle_timer = 0.0
        self._glow_timer = 0.0

    def update_idle_glow(self, dt: float):
        """Call once per frame regardless of whether the overlay is
        open. Suppressed entirely while open — no point nudging someone
        to open something they already have open."""
        if self.visible:
            self._idle_timer = 0.0
            self._glow_timer = 0.0
            return
        if self._glow_timer > 0:
            self._glow_timer = max(0.0, self._glow_timer - dt)
            return
        self._idle_timer += dt
        if self._idle_timer >= self.IDLE_GLOW_INTERVAL:
            self._idle_timer = 0.0
            self._glow_timer = self.IDLE_GLOW_DURATION

    @property
    def is_glowing(self) -> bool:
        return self._glow_timer > 0

    def draw_button_glow(self, surf: pygame.Surface, button_rect: pygame.Rect):
        """Draws a soft pulsing gold halo behind the '?' button while
        is_glowing. Call this BEFORE drawing the button itself, so the
        halo sits behind it, not on top."""
        if not self.is_glowing:
            return
        t = 1.0 - (self._glow_timer / self.IDLE_GLOW_DURATION)
        pulse = 0.5 + 0.5 * math.sin(t * math.pi * 4)  # a couple pulses across the 3s
        radius = button_rect.width // 2 + 4 + int(pulse * 6)
        alpha = int(90 + pulse * 100)
        d = radius * 2 + 4
        glow_surf = pygame.Surface((d, d), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (255, 215, 0, alpha), (d // 2, d // 2), radius, width=3)
        surf.blit(glow_surf, (button_rect.centerx - d // 2, button_rect.centery - d // 2))

    def _layout(self, sw: int, sh: int):
        pw = min(680, sw - 80)
        ph = min(560, sh - 80)
        self._panel_rect = pygame.Rect(0, 0, pw, ph)
        self._panel_rect.center = (sw // 2, sh // 2)
        cs = min(1.4, max(0.7, sw / 1280))
        close_sz = round(32 * cs)
        self._close_rect = pygame.Rect(
            self._panel_rect.right - close_sz - 14, self._panel_rect.top + 14,
            close_sz, close_sz)

    def _flow(self):
        """Computes each section's wrapped lines once per layout pass and
        the total scrollable content height — shared by draw() (to know
        what to blit) and _max_scroll() (to clamp scrolling). Each
        section's paragraph list can mix plain strings (wrapped body
        text) with ('image', pygame.Surface, caption_or_None) tuples —
        the image is scaled to fit the content width (preserving aspect
        ratio, capped at MAX_IMAGE_H tall) and centered."""
        content_w = self._panel_rect.width - self.PAD * 2
        flowed = []
        y = 0
        for heading, paragraphs in self.sections:
            flowed.append(('heading', heading, y))
            y += self.font_heading.get_height() + self.HEADING_GAP
            for para in paragraphs:
                if isinstance(para, tuple) and para[0] == 'image':
                    _, img, caption = para
                    iw, ih = img.get_width(), img.get_height()
                    scale = min(content_w / iw, self.MAX_IMAGE_H / ih, 1.0)
                    dw, dh = round(iw * scale), round(ih * scale)
                    scaled = pygame.transform.smoothscale(img, (dw, dh)) if scale != 1.0 else img
                    flowed.append(('image', scaled, y))
                    y += dh + 6
                    if caption:
                        cap_lines = wrap_text(self.font_body, caption, content_w)
                        flowed.append(('caption', cap_lines, y))
                        y += len(cap_lines) * (self.font_body.get_height() + self.LINE_GAP) + self.PARA_GAP
                    else:
                        y += self.PARA_GAP
                else:
                    lines = wrap_text(self.font_body, para, content_w)
                    flowed.append(('para', lines, y))
                    y += len(lines) * (self.font_body.get_height() + self.LINE_GAP) + self.PARA_GAP
        self._content_height = y
        return flowed

    def _max_scroll(self) -> int:
        viewport_h = self._panel_rect.height - 90  # below title/close, above bottom pad
        return max(0, self._content_height - viewport_h)

    def handle_event(self, event: pygame.event.Event, sw: int, sh: int) -> bool:
        """Returns True if this overlay consumed the event (so the
        underlying screen's own handle_event should skip it)."""
        if not self.visible:
            return False
        self._layout(sw, sh)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self._close_rect.collidepoint(event.pos):
                self.close()
                return True
            if not self._panel_rect.collidepoint(event.pos):
                # Click outside the panel dismisses it, same as most
                # modal conventions elsewhere in the OS.
                self.close()
                return True
            if event.button == 4:
                self.scroll = max(0, self.scroll - 40)
            elif event.button == 5:
                self.scroll = min(self._max_scroll(), self.scroll + 40)
            return True
        if event.type == pygame.MOUSEWHEEL and self._panel_rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll = max(0, min(self._max_scroll(), self.scroll - event.y * 40))
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True
        return True  # swallow everything else while open — modal

    def draw(self, surf: pygame.Surface):
        if not self.visible:
            return
        sw, sh = surf.get_width(), surf.get_height()
        self._layout(sw, sh)

        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 165))
        surf.blit(dim, (0, 0))

        panel = Panel(self._panel_rect, color=(24, 30, 42), alpha=250)
        panel.draw(surf)

        title_s = self.font_title.render(self.title, True, GOLD_LIGHT)
        surf.blit(title_s, (self._panel_rect.left + self.PAD, self._panel_rect.top + 16))

        pygame.draw.rect(surf, (*GOLD_LIGHT, 200), self._close_rect, width=2, border_radius=6)
        draw_icon(surf, self._close_rect, 'close', WHITE)

        # Scrollable content area, clipped so long sections don't paint
        # over the title/close button above or the panel border below.
        viewport = pygame.Rect(self._panel_rect.left, self._panel_rect.top + 64,
                               self._panel_rect.width, self._panel_rect.height - 90)
        prev_clip = surf.get_clip()
        surf.set_clip(viewport)

        flowed = self._flow()
        base_x = self._panel_rect.left + self.PAD
        base_y = viewport.top - self.scroll
        for kind, payload, oy in flowed:
            y = base_y + oy
            if kind == 'heading':
                if -40 < y < sh:
                    hs = self.font_heading.render(payload, True, GOLD_LIGHT)
                    surf.blit(hs, (base_x, y))
            elif kind == 'image':
                if -self.MAX_IMAGE_H < y < sh:
                    img_x = base_x + (self._panel_rect.width - self.PAD * 2 - payload.get_width()) // 2
                    pygame.draw.rect(surf, (*GOLD_LIGHT, 120),
                                     pygame.Rect(img_x - 2, y - 2,
                                                 payload.get_width() + 4, payload.get_height() + 4),
                                     width=1, border_radius=6)
                    surf.blit(payload, (img_x, y))
            elif kind == 'caption':
                for i, line in enumerate(payload):
                    ly = y + i * (self.font_body.get_height() + self.LINE_GAP)
                    if -30 < ly < sh:
                        ls = self.font_body.render(line, True, (*GOLD_LIGHT, 200))
                        surf.blit(ls, (base_x, ly))
            else:  # 'para' -> list of wrapped lines
                for i, line in enumerate(payload):
                    ly = y + i * (self.font_body.get_height() + self.LINE_GAP)
                    if -30 < ly < sh:
                        ls = self.font_body.render(line, True, (*WHITE, 220))
                        surf.blit(ls, (base_x, ly))
        surf.set_clip(prev_clip)

        # Simple scrollbar, same visual language as SettingsScene's.
        max_s = self._max_scroll()
        if max_s > 0:
            track = pygame.Rect(self._panel_rect.right - 12, viewport.top,
                                6, viewport.height)
            pygame.draw.rect(surf, (60, 66, 78), track, border_radius=3)
            thumb_h = max(24, int(viewport.height * viewport.height / self._content_height))
            thumb_y = track.top + int((viewport.height - thumb_h) * (self.scroll / max_s))
            pygame.draw.rect(surf, (*GOLD_LIGHT, 200),
                             pygame.Rect(track.x, thumb_y, track.width, thumb_h), border_radius=3)


def make_help_button(rect: pygame.Rect, font: pygame.font.Font, on_click: Callable) -> 'Button':
    """A small '?' icon button matching AudioControls' sfx/music toggle
    styling (see scenes.AudioControls) — same dark-green idle/hover
    colors, just with a '?' glyph instead of a drawn icon shape, since
    '?' renders reliably across the same fonts already used for button
    labels (unlike the mute/music glyphs, which are hand-drawn via
    draw_icon specifically to avoid missing-glyph "tofu box" issues)."""
    return Button(rect, "?", font, color=(50, 70, 50), hover_color=(70, 100, 70),
                 text_color=GOLD_LIGHT, on_click=on_click)

