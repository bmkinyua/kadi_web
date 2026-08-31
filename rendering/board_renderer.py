"""
KADI - Board Renderer
Draws the game table: hands, discard/draw piles, player info panels,
direction indicator, pick-up counter, KADI markers.
"""
from __future__ import annotations
import pygame
import math
import random
from typing import List, Optional, Dict, Tuple, Set
from constants import (
    SCREEN_W, SCREEN_H, CARD_W, CARD_H, CARD_RAD,
    TABLE_GREEN, TABLE_FELT, TABLE_EDGE, FELT_THEMES,
    WHITE, BLACK, DARK_GRAY, MID_GRAY, LIGHT_GRAY, GOLD, GOLD_LIGHT,
    CARD_SELECTED, CARD_PLAYABLE, CARD_HOVER, KADI_COLOR,
    Suit, SUIT_SYMBOL, SUIT_ICON, SUIT_COLOR, SUIT_ACCENT,
    PlayDirection, SHADOW_ALPHA, SHADOW_COLOR, SHADOW_OFFSET,
    get_ui_scale, get_ad_reserved_top,
)
from models.card import Card
from models.player import Player
from rendering.asset_loader import AssetLoader
from rendering.widgets import draw_icon


# Fallback pile center for the handful of call sites that need a value
# before the first real frame has been drawn (SCREEN_W/H match the
# default logical resolution). Everything that actually renders derives
# its position from the CURRENT surface size at draw time instead — see
# BoardRenderer._pile_center()/_discard_pos()/_draw_pos() below. Using
# these fixed SCREEN_W/H constants directly for on-screen positions was
# the bug: at any logical resolution other than the 1280x800 default,
# the whole table (piles, direction arrow, opponent seats) stayed
# anchored to where 1280x800 would put it instead of the actual window,
# which is what produced the skewed/zoomed-in layouts at other
# resolutions.
PILE_CENTER_X = SCREEN_W // 2
PILE_CENTER_Y = SCREEN_H // 2

DISCARD_POS = (PILE_CENTER_X - CARD_W // 2 - 10, PILE_CENTER_Y - CARD_H // 2)
DRAW_POS    = (PILE_CENTER_X + 10,                PILE_CENTER_Y - CARD_H // 2)

# Number of "stack" cards to show behind discard pile
STACK_DEPTH = 4


def _resolve_layout_metrics(sw: int, sh: int, top_margin: int) -> Dict:
    """Everything resolution/player-count-dependent that _layout_positions
    and the hand-rendering code need, solved together in one place:

      - card_w/card_h        : scaled card size for this resolution
                                (get_ui_scale()['card_scale']), replacing the
                                flat CARD_W/CARD_H used everywhere before.
      - human_max_width /
        opp_max_width /
        opp_reveal_max_width : scaled versions of the real HandRenderer
                                footprint caps (520 / 280 / 360 at the
                                1280x800 baseline) — these self-limit a
                                hand's total fan width no matter how many
                                cards are in it (see HandRenderer.
                                _card_positions), so half of the scaled
                                max_width is the correct worst-case
                                half-width for the clearance solve below,
                                not a per-card-count estimate.
      - font_scale            : resolution-based font scale for board text.

    Returns a dict; oval rx/ry themselves are solved separately per n_players
    in _layout_positions (below) since they depend on player count too.
    """
    ui = get_ui_scale(sw, sh)
    card_scale = ui['card_scale']
    card_w = round(CARD_W * card_scale)
    card_h = round(card_w * CARD_H / CARD_W)
    return {
        'card_scale': card_scale,
        'card_w': card_w,
        'card_h': card_h,
        'human_max_width': 520 * card_scale,
        'opp_max_width':   280 * card_scale,
        'opp_reveal_max_width': 360 * card_scale,
        'font_scale': ui['font_scale'],
        'oval_rx_pct': ui['oval_rx_pct'],
        'oval_ry_pct': ui['oval_ry_pct'],
    }


def _solve_oval_radius(sw: int, sh: int, n_players: int, top_margin: int,
                        metrics: Dict) -> Tuple[float, float]:
    """Solves the seat-oval's (rx, ry) so EVERY seat's hand — at its
    real self-limiting max-width footprint (see _resolve_layout_metrics) —
    stays fully inside the felt boundary, and seat 0's (human, always at
    the top of the oval numerically) hand also clears the ad-banner's
    reserved top_margin. This replaces two separate old bugs:

      1. rx was a flat 380px regardless of resolution or card size, so at
         big resolutions/big cards a side seat's hand could fan out past
         the felt edge even though the seat's own centre point was fine.
      2. ry only ever checked seat 0's hand against top_margin in
         isolation — never against the felt's horizontal edge for the
         OTHER seats, and never for anything beyond 4 players.

    Starts from the profile's target rx/ry (% of screen) and scales both
    down together (uniformly, so the oval keeps its shape) only as far as
    needed — most resolutions/player-counts need no scaling down at all.
    """
    felt_rx, felt_ry = sw * 0.46, sh * 0.46
    margin_frac = 0.08
    felt_rx_m, felt_ry_m = felt_rx * (1 - margin_frac), felt_ry * (1 - margin_frac)

    opp_hw = metrics['opp_max_width'] / 2
    opp_hh = (metrics['card_h'] * 0.82) / 2
    human_hw = metrics['human_max_width'] / 2
    human_hh = metrics['card_h'] / 2

    rx_target = sw * metrics['oval_rx_pct']
    ry_target = sh * metrics['oval_ry_pct']

    def fits(t: float) -> bool:
        for i in range(n_players):
            angle = (360 / n_players) * i - 90
            rad = math.radians(angle)
            hw, hh = (human_hw, human_hh) if i == 0 else (opp_hw, opp_hh)
            px, py = t * rx_target * math.cos(rad), t * ry_target * math.sin(rad)
            for sxs in (-1, 1):
                for sys_ in (-1, 1):
                    cxp, cyp = px + sxs * hw, py + sys_ * hh
                    if (cxp / felt_rx_m) ** 2 + (cyp / felt_ry_m) ** 2 > 1:
                        return False
            if i == 0:
                seat_top_y = sh / 2 + py - hh
                if seat_top_y < top_margin:
                    return False
        return True

    t = 1.0
    if not fits(1.0):
        lo, hi = 0.15, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if fits(mid):
                lo = mid
            else:
                hi = mid
        t = lo
    return t * rx_target, t * ry_target


def _layout_positions(n_players: int, sw: int = SCREEN_W, sh: int = SCREEN_H,
                       top_margin: int = 0) -> List[Dict]:
    """
    Returns a list of layout dicts for each player seat:
    {angle, hand_center, info_rect, face_up}
    Player 0 is the face-up, full-size seat (angle -90, i.e. numerically
    nearest the top of the surface) — despite the name "seat 0", this is
    NOT visually at the bottom; see the note below on how the human's
    hand actually ends up looking bottom-anchored on screen despite this.

    sw/sh are the CURRENT surface's logical size (not the fixed
    SCREEN_W/SCREEN_H design-time constants) so seats stay correctly
    placed at any resolution, not just the 1280x800 default.

    top_margin reserves `top_margin` pixels of vertical space at the very
    top of the surface (used by the ad banner slot on GameplayScene — see
    get_ad_reserved_top() in constants.py and GameplayScene._ad_top_pad())
    that no seat's cards may render into.

    Card size, hand footprint, and oval radius are all resolution- and
    player-count-aware now (see _resolve_layout_metrics/_solve_oval_radius)
    instead of the old flat CARD_W/CARD_H + fixed rx=380 + a ry-only
    banner check.
    """
    metrics = _resolve_layout_metrics(sw, sh, top_margin)
    rx, ry = _solve_oval_radius(sw, sh, n_players, top_margin, metrics)
    avail_h = sh - top_margin

    positions = []
    for i in range(n_players):
        angle = (360 / n_players) * i - 90  # 0 = top, human at bottom
        rad   = math.radians(angle)
        cx = sw / 2 + rx * math.cos(rad)
        cy = top_margin + avail_h / 2 + ry * math.sin(rad)

        face_up = (i == 0)
        positions.append({
            'angle': angle,
            'hand_cx': cx,
            'hand_cy': cy,
            'face_up': face_up,
            'seat_index': i,
            # Carried along so BoardRenderer/HandRenderer don't need to
            # recompute get_ui_scale() themselves every draw call.
            'card_w': metrics['card_w'],
            'card_h': metrics['card_h'],
            'human_max_width': metrics['human_max_width'],
            'opp_max_width': metrics['opp_max_width'],
            'opp_reveal_max_width': metrics['opp_reveal_max_width'],
            'font_scale': metrics['font_scale'],
        })
    return positions


class HandRenderer:
    """Renders a fan of cards for one player. Supports drag-to-reorder."""

    def __init__(self, assets: AssetLoader):
        self.assets = assets

    def _card_positions(self, n: int, cx: float, cy: float,
                        max_width: int = 520, compact: bool = False,
                        base_w: int = CARD_W, base_h: int = CARD_H):
        """Return list of (x, y, cw, ch, overlap) for n cards.

        base_w/base_h is the resolution-scaled card size for this frame
        (BoardRenderer's self._card_w/self._card_h — see
        _resolve_layout_metrics in this module) — defaults to the flat
        design-time CARD_W/CARD_H only for any caller that hasn't been
        updated to pass the scaled size."""
        scale   = 0.82 if compact else 1.0
        cw      = int(base_w * scale)
        ch      = int(base_h * scale)
        overlap = max(10, min(cw - 4, (max_width - cw) // max(n - 1, 1)))
        total_w = cw + overlap * (n - 1)
        start_x = int(cx - total_w // 2)
        positions = []
        for idx in range(n):
            x = start_x + idx * overlap
            y = int(cy - ch // 2)
            positions.append((x, y, cw, ch, overlap))
        return positions

    def get_drop_index(self, mx: int, cards_n: int, cx: float, cy: float,
                       max_width: int = 520,
                       base_w: int = CARD_W, base_h: int = CARD_H) -> int:
        """Return the slot index where a dragged card should be dropped."""
        positions = self._card_positions(cards_n, cx, cy, max_width,
                                          base_w=base_w, base_h=base_h)
        if not positions:
            return 0
        overlap = positions[0][4]
        cw      = positions[0][2]
        # Find nearest slot centre
        best_i   = 0
        best_dist = float('inf')
        for i, (x, y, cw2, ch2, _) in enumerate(positions):
            centre_x = x + cw2 // 2
            d = abs(mx - centre_x)
            if d < best_dist:
                best_dist = d
                best_i = i
        return best_i

    def render(self, surf: pygame.Surface, cards: List[Card],
               cx: float, cy: float, face_up: bool,
               selected: Set[int], playable: Set[int],
               hovered: Optional[int], is_current: bool,
               max_width: int = 520, compact: bool = False,
               drag_idx: Optional[int] = None,
               drag_pos: Optional[Tuple[int, int]] = None,
               drag_target: Optional[int] = None,
               hint_idx: Optional[int] = None,
               base_w: int = CARD_W, base_h: int = CARD_H):
        n = len(cards)
        if n == 0:
            return

        positions = self._card_positions(n, cx, cy, max_width, compact,
                                          base_w=base_w, base_h=base_h)
        cw = positions[0][2]
        ch = positions[0][3]

        for idx, card in enumerate(cards):
            if idx == drag_idx and drag_pos is not None:
                continue  # drawn separately as floating card

            x, y, cw2, ch2, _ = positions[idx]

            # Shift cards to show insertion gap when dragging
            if drag_idx is not None and drag_target is not None and face_up:
                if drag_idx < drag_target:
                    if drag_idx < idx <= drag_target:
                        x -= cw2 // 2
                elif drag_idx > drag_target:
                    if drag_target <= idx < drag_idx:
                        x += cw2 // 2

            is_sel  = idx in selected
            is_play = idx in playable
            is_hov  = idx == hovered
            lift    = 0

            if is_sel:
                lift = -18
            elif is_hov and face_up:
                lift = -12

            if (is_sel or is_play) and face_up:
                glow_col  = CARD_SELECTED if is_sel else CARD_PLAYABLE
                glow_rect = pygame.Rect(x - 4, y + lift - 4, cw2 + 8, ch2 + 8)
                pygame.draw.rect(surf, (*glow_col, 180), glow_rect,
                                 border_radius=CARD_H // 7)

            card_surf = self.assets.get_card_surface_scaled(card, face_up, cw2, ch2)

            # Soft drop shadow (Phase 3) — pure code, same tokens as panels/
            # buttons, so cards read with the same consistent depth.
            shadow = pygame.Surface((cw2 + 6, ch2 + 6), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (*SHADOW_COLOR, SHADOW_ALPHA), shadow.get_rect(),
                             border_radius=CARD_RAD + 2)
            surf.blit(shadow, (x - 3 + SHADOW_OFFSET[0], y + lift - 3 + SHADOW_OFFSET[1]))

            surf.blit(card_surf, (x, y + lift))

            if is_hov and face_up and not is_sel:
                tint = pygame.Surface((cw2, ch2), pygame.SRCALPHA)
                tint.fill((*CARD_HOVER, 60))
                surf.blit(tint, (x, y + lift))

            if idx == hint_idx and face_up and not is_sel:
                # Hint highlight — deliberately more attention-grabbing than
                # the hover/playable tints (this was reported as "not sure
                # if it's even working" when it was just a thin, mostly-
                # translucent ring). Now: a soft multi-layer glow halo
                # behind the card plus a bright pulsing/blinking border,
                # and the card itself bobs slightly — unmistakable at a
                # glance without being a full-strength strategy hint.
                phase = (pygame.time.get_ticks() % 1100) / 1100.0
                pulse = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
                bob = int(4 * math.sin(phase * 2 * math.pi))

                hint_col = (255, 215, 40)
                # Soft outer glow: several oversized, low-alpha rounded
                # rects stacked to fake a blur/bloom effect.
                for i, (pad, base_a) in enumerate(((16, 40), (11, 60), (6, 90))):
                    glow_rect = pygame.Rect(x - pad, y + lift + bob - pad,
                                            cw2 + pad * 2, ch2 + pad * 2)
                    glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
                    a = int(base_a * (0.5 + 0.5 * pulse))
                    pygame.draw.rect(glow_surf, (*hint_col, a),
                                     glow_surf.get_rect(),
                                     border_radius=CARD_H // 7 + pad)
                    surf.blit(glow_surf, glow_rect.topleft)

                # Bright pulsing border, blinking between dim and near-solid.
                alpha = int(90 + 165 * pulse)
                ring_rect = pygame.Rect(x - 5, y + lift + bob - 5, cw2 + 10, ch2 + 10)
                ring_surf = pygame.Surface(ring_rect.size, pygame.SRCALPHA)
                pygame.draw.rect(ring_surf, (*hint_col, alpha),
                                 ring_surf.get_rect(), width=4,
                                 border_radius=CARD_H // 7 + 3)
                surf.blit(ring_surf, ring_rect.topleft)

        # Draw floating dragged card on top
        if drag_idx is not None and drag_pos is not None and drag_idx < len(cards):
            card = cards[drag_idx]
            card_surf = self.assets.get_card_surface_scaled(card, face_up, cw, ch)
            fx = drag_pos[0] - cw // 2
            fy = drag_pos[1] - ch // 2 - 10
            # Slight shadow
            shadow = pygame.Surface((cw + 8, ch + 8), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (0, 0, 0, SHADOW_ALPHA), shadow.get_rect(), border_radius=12)
            surf.blit(shadow, (fx - 4, fy + 6))
            surf.blit(card_surf, (fx, fy))
            # Gold outline on dragged card
            pygame.draw.rect(surf, GOLD_LIGHT, pygame.Rect(fx, fy, cw, ch),
                             width=2, border_radius=CARD_RAD)

    def get_card_at(self, cards: List[Card], mx: int, my: int,
                    cx: float, cy: float, face_up: bool,
                    max_width: int = 520, compact: bool = False,
                    base_w: int = CARD_W, base_h: int = CARD_H) -> Optional[int]:
        if not face_up:
            return None
        n = len(cards)
        if n == 0:
            return None
        positions = self._card_positions(n, cx, cy, max_width, compact,
                                          base_w=base_w, base_h=base_h)
        cw = positions[0][2]
        ch = positions[0][3]
        for idx in range(n - 1, -1, -1):
            x, y, cw2, ch2, _ = positions[idx]
            rect = pygame.Rect(x, y - 18, cw2, ch2 + 18)
            if rect.collidepoint(mx, my):
                return idx
        return None


class BoardRenderer:
    def __init__(self, assets: AssetLoader):
        self.assets       = assets
        self.hand_renderer = HandRenderer(assets)
        self._layout: List[Dict] = []
        self._n_players: int = 0
        # Current logical surface size, kept in sync with the real
        # render target every frame in draw_table() (see below). Starts
        # at the default logical resolution as a sane pre-first-frame
        # fallback; every position derived from it below is recomputed
        # the moment the actual size is known, so nothing stays pinned
        # to this default at other resolutions.
        self._sw, self._sh = SCREEN_W, SCREEN_H
        self._top_margin: int = 0
        self._metrics: Dict = _resolve_layout_metrics(self._sw, self._sh, self._top_margin)
        self._felt_cache: Optional[pygame.Surface] = None
        self._felt_cache_size: Optional[Tuple[int, int]] = None
        # Cosmetics (Profile Part 2): which FELT_THEMES key is currently
        # equipped — set once at startup from the loaded profile, and
        # live from the Profile screen's equip controls. Defaults to the
        # original green so a profile-less/first-run game is unchanged.
        self._felt_theme: str = "default"

    # ─── Resolution-scaled values (see _resolve_layout_metrics) ────────────────
    @property
    def card_w(self) -> int:
        return self._metrics['card_w']

    @property
    def card_h(self) -> int:
        return self._metrics['card_h']

    @property
    def font_scale(self) -> float:
        return self._metrics['font_scale']

    def setup_layout(self, n_players: int, sw: Optional[int] = None, sh: Optional[int] = None,
                      top_margin: int = 0):
        self._n_players = n_players
        self._top_margin = top_margin
        if sw is not None and sh is not None:
            self._sw, self._sh = sw, sh
        self._metrics = _resolve_layout_metrics(self._sw, self._sh, self._top_margin)
        self._layout = _layout_positions(n_players, self._sw, self._sh, self._top_margin)

    def get_layout(self) -> List[Dict]:
        return self._layout

    def _sync_size(self, sw: int, sh: int, top_margin: int = 0):
        """Called once per frame (from draw_table) with the ACTUAL current
        render-surface size. Keeps pile positions and seat layout aligned
        to whatever resolution is really being drawn to, instead of the
        fixed 1280x800 design-time constants — that mismatch (rendering
        against SCREEN_W/SCREEN_H while the real surface was some other
        chosen resolution) is what skewed/zoomed the table at anything
        other than the default resolution.

        top_margin is also checked every frame (not just sw/sh) so that
        toggling the ad banner on/off mid-game (via Settings) reflows the
        seat layout immediately, the same way a live resolution change
        already does."""
        if (sw, sh, top_margin) != (self._sw, self._sh, getattr(self, '_top_margin', 0)):
            self._sw, self._sh = sw, sh
            self._top_margin = top_margin
            self._metrics = _resolve_layout_metrics(sw, sh, top_margin)
            if self._n_players:
                self._layout = _layout_positions(self._n_players, sw, sh, top_margin)

    # ─── Dynamic pile positions (resolution-aware) ─────────────────────────────

    def _pile_center(self) -> Tuple[int, int]:
        return self._sw // 2, self._sh // 2

    def _discard_pos(self) -> Tuple[int, int]:
        cx, cy = self._pile_center()
        gap = round(10 * self._metrics['card_scale'])
        return (cx - self.card_w // 2 - gap, cy - self.card_h // 2)

    def _draw_pos(self) -> Tuple[int, int]:
        cx, cy = self._pile_center()
        gap = round(10 * self._metrics['card_scale'])
        return (cx + gap, cy - self.card_h // 2)

    # ─── Main draw ────────────────────────────────────────────────────────────

    def set_felt_theme(self, theme_key: str):
        """Switch the equipped felt cosmetic (Profile Part 2) — called
        once at startup from the loaded profile, and again live from the
        Profile screen's equip controls. Falls back to 'default' for an
        unknown/legacy key. Invalidates the felt cache so the next
        draw_table() rebuilds the gradient with the new theme's colors."""
        self._felt_theme = theme_key if theme_key in FELT_THEMES else "default"
        self._felt_cache = None
        self._felt_cache_size = None

    def get_felt_theme(self) -> str:
        return self._felt_theme

    def _build_felt_texture(self, sw: int, sh: int) -> pygame.Surface:
        """Procedurally generates the table felt: a radial gradient (lighter
        centre fading to the darker edge colour of the equipped felt
        theme — see FELT_THEMES in constants.py) plus a very subtle woven
        cross-hatch texture. Pure code over a numpy array — no downloaded
        image, no licensing question — built once per theme+size and
        cached since it's the same every frame until either changes."""
        import numpy as np
        theme = FELT_THEMES.get(self._felt_theme, FELT_THEMES["default"])
        centre_color, edge_color = theme["felt"], theme["edge"]
        yy, xx = np.mgrid[0:sh, 0:sw]
        cx, cy = sw / 2.0, sh / 2.0
        # Normalized radial distance from centre (0 at centre, ~1 at rim)
        rx, ry = sw * 0.46, sh * 0.46
        dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        t = np.clip(dist, 0.0, 1.0)

        surf_arr = np.zeros((sw, sh, 3), dtype=np.uint8)
        for ch in range(3):
            centre_c = centre_color[ch]
            edge_c   = edge_color[ch]
            grad = centre_c + (edge_c - centre_c) * t
            # Fine woven weave — two crossed low-amplitude sine ripples,
            # imperceptible individually but reads as felt at a glance.
            weave = (np.sin(xx.T * 0.9) * 1.5 + np.sin((yy.T + xx.T) * 0.7) * 1.5)
            surf_arr[:, :, ch] = np.clip(grad.T + weave, 0, 255).astype(np.uint8)

        surf = pygame.surfarray.make_surface(surf_arr)
        pattern = theme.get("pattern", "plain")
        if pattern and pattern != "plain":
            self._apply_felt_pattern(surf, pattern, sw, sh)
        return surf

    def _apply_felt_pattern(self, surf: pygame.Surface, pattern: str, sw: int, sh: int):
        """Faint (~10-20% opacity) geometric overlay for badge-unlocked
        textured felt themes (see FELT_THEMES' 'pattern' key) — drawn on
        a separate SRCALPHA surface and blitted once so it's a real
        alpha blend on top of the base gradient+weave, subtle enough not
        to hurt card readability at table scale."""
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        faint = (255, 255, 255, 24)
        if pattern == "diamond_quilt":
            step = 46
            for yy in range(-step, sh + step, step):
                for xx in range(-step, sw + step, step):
                    pts = [(xx, yy - step // 2), (xx + step // 2, yy),
                           (xx, yy + step // 2), (xx - step // 2, yy)]
                    pygame.draw.polygon(overlay, faint, pts, 1)
        elif pattern == "herringbone":
            step = 26
            for yy in range(0, sh, step * 2):
                for xx in range(-sh, sw, step * 2):
                    pygame.draw.line(overlay, faint, (xx, yy), (xx + step, yy + step), 2)
                    pygame.draw.line(overlay, faint, (xx + step, yy), (xx + step * 2, yy + step), 2)
        elif pattern == "pinstripe":
            step = 34
            for xx in range(0, sw, step):
                pygame.draw.line(overlay, faint, (xx, 0), (xx, sh), 1)
        elif pattern == "checkerboard":
            cell = 40
            for row, yy in enumerate(range(0, sh, cell)):
                for col, xx in enumerate(range(0, sw, cell)):
                    if (row + col) % 2 == 0:
                        pygame.draw.rect(overlay, faint, pygame.Rect(xx, yy, cell, cell), 0)
        elif pattern == "honeycomb":
            hex_r = 28
            dx, dy = hex_r * 1.7, hex_r * 1.5
            row = 0
            yy = -hex_r
            while yy < sh + hex_r:
                offset = (dx / 2) if row % 2 else 0
                xx = -hex_r + offset
                while xx < sw + hex_r:
                    pts = [(xx + hex_r * math.cos(math.radians(60 * i)),
                            yy + hex_r * math.sin(math.radians(60 * i))) for i in range(6)]
                    pygame.draw.polygon(overlay, faint, pts, 1)
                    xx += dx
                yy += dy
                row += 1
        elif pattern == "constellation":
            rng = random.Random(4321)  # fixed seed: identical every rebuild
            for _ in range(90):
                x = rng.randint(0, sw)
                y = rng.randint(0, sh)
                r = rng.choice([1, 1, 2])
                pygame.draw.circle(overlay, (255, 255, 255, 55), (x, y), r)
        surf.blit(overlay, (0, 0))

    def draw_table(self, surf: pygame.Surface, top_margin: int = 0):
        sw, sh = surf.get_size()
        self._sync_size(sw, sh, top_margin)
        theme = FELT_THEMES.get(self._felt_theme, FELT_THEMES["default"])
        surf.fill(theme["bg"])

        if self._felt_cache is None or self._felt_cache_size != (sw, sh):
            self._felt_cache = self._build_felt_texture(sw, sh)
            self._felt_cache_size = (sw, sh)

        oval_rect = pygame.Rect(40, 40, sw - 80, sh - 80)
        mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
        pygame.draw.ellipse(mask, (255, 255, 255, 255), oval_rect)
        felt = self._felt_cache.copy()
        felt.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(felt, (0, 0))
        pygame.draw.ellipse(surf, theme["edge"], oval_rect, width=4)

        cx, cy = sw // 2, sh // 2
        for r, alpha in [(200, 15), (150, 20), (100, 25)]:
            glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(glow, (255, 255, 255, alpha), glow.get_rect())
            surf.blit(glow, (cx - r, cy - r))

    def draw_piles(self, surf: pygame.Surface, top_card: Optional[Card],
                   draw_count: int, current_suit: Optional[Suit]):
        discard_pos = self._discard_pos()
        draw_pos    = self._draw_pos()
        cw, ch = self.card_w, self.card_h
        fs = self.font_scale

        # Draw pile stack
        back = self.assets.get_card_back_scaled(cw, ch)
        for i in range(min(STACK_DEPTH, draw_count)):
            offset = i * 1
            surf.blit(back, (draw_pos[0] - offset, draw_pos[1] - offset))

        # Draw pile label
        font = self.assets.font_scaled('ui_small', fs)
        cnt = font.render(f"Draw ({draw_count})", True, (*WHITE, 180))
        surf.blit(cnt, (draw_pos[0] + cw // 2 - cnt.get_width() // 2,
                        draw_pos[1] + ch + 6))

        # Discard pile
        if top_card:
            # Stack behind
            for i in range(min(3, 5)):
                offset_x = (i - 1) * 2
                offset_y = (i - 1) * 1
                tinted = back.copy()
                tinted.set_alpha(100 - i * 20)
                surf.blit(tinted, (discard_pos[0] + offset_x, discard_pos[1] + offset_y))

            card_surf = self.assets.get_card_surface_scaled(top_card, True, cw, ch)
            shadow = pygame.Surface((cw + 6, ch + 6), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (*SHADOW_COLOR, SHADOW_ALPHA), shadow.get_rect(),
                             border_radius=CARD_RAD + 2)
            surf.blit(shadow, (discard_pos[0] - 3 + SHADOW_OFFSET[0],
                               discard_pos[1] - 3 + SHADOW_OFFSET[1]))
            surf.blit(card_surf, discard_pos)

            # Glow border on discard
            glow_rect = pygame.Rect(discard_pos[0] - 3, discard_pos[1] - 3,
                                    cw + 6, ch + 6)
            pygame.draw.rect(surf, (*GOLD, 120), glow_rect, width=2, border_radius=12)

        # Current suit indicator
        if current_suit:
            self._draw_suit_indicator(surf, current_suit)

        # Pile labels
        dl = font.render("Discard", True, (*WHITE, 160))
        surf.blit(dl, (discard_pos[0] + cw // 2 - dl.get_width() // 2,
                        discard_pos[1] + ch + 6))

    def _draw_suit_indicator(self, surf: pygame.Surface, suit: Suit):
        # Previously this sat directly above the pile centre, which is
        # exactly where the top seat's info panel (name/card-count box)
        # renders for non-face-up seats — the indicator was permanently
        # obscured behind that panel. Moved into the open felt to the
        # left of the piles instead (vertically centred on the piles,
        # not stacked above them), where nothing else draws.
        discard_pos = self._discard_pos()
        _, pile_cy = self._pile_center()

        accent = SUIT_ACCENT[suit]
        sym_size = round(28 * self.font_scale)
        sym_surf = pygame.Surface((sym_size, sym_size), pygame.SRCALPHA)
        draw_icon(sym_surf, sym_surf.get_rect(), SUIT_ICON[suit], SUIT_COLOR[suit], width=3)

        bg = pygame.Surface((sym_surf.get_width() + 24, sym_surf.get_height() + 12),
                             pygame.SRCALPHA)
        pygame.draw.rect(bg, (*accent, 200), bg.get_rect(), border_radius=10)
        bg.blit(sym_surf, (12, 6))

        label_font = self.assets.font_scaled('ui_tiny', self.font_scale)
        lbl = label_font.render("Current suit", True, (*WHITE, 180))

        box_w = max(bg.get_width(), lbl.get_width())
        gap = round(34 * self.font_scale)
        cx = discard_pos[0] - gap - box_w // 2

        by = pile_cy - bg.get_height() // 2
        surf.blit(lbl, (cx - lbl.get_width() // 2, by - lbl.get_height() - 4))
        surf.blit(bg, (cx - bg.get_width() // 2, by))

    def draw_direction_indicator(self, surf: pygame.Surface,
                                 direction: PlayDirection):
        cx, cy = self._pile_center()
        r = round(55 * self.font_scale)
        arrow_col = (*GOLD, 160)
        s = pygame.Surface((r * 2 + 20, r * 2 + 20), pygame.SRCALPHA)
        sc = r + 10

        angle_range = range(30, 330, 15) if direction == PlayDirection.CLOCKWISE \
                      else range(330, 30, -15)

        pts = []
        for a in angle_range:
            rad = math.radians(a)
            pts.append((sc + r * math.cos(rad), sc + r * math.sin(rad)))

        if len(pts) > 1:
            for i in range(len(pts) - 1):
                pygame.draw.line(s, arrow_col, pts[i], pts[i + 1], 2)

        # Arrowhead
        last_pt = pts[-1]
        dl = math.radians(angle_range[-1] + (10 if direction == PlayDirection.CLOCKWISE else -10))
        arrow_tip = (sc + r * math.cos(dl), sc + r * math.sin(dl))
        pygame.draw.line(s, arrow_col, last_pt, arrow_tip, 3)

        surf.blit(s, (cx - sc, cy - sc))

    def draw_pickup_indicator(self, surf: pygame.Surface, pickup_count: int):
        if pickup_count <= 0:
            return
        # Previously centred at sh//2 + card_h//2 + 20 — directly on top
        # of the "Discard"/"Draw (N)" pile labels and, below those, the
        # bottom seat's info panel. Moved into the open felt to the
        # right of the piles instead (same open space
        # _draw_suit_indicator already uses on the left, and where
        # scenes.py's "X must pick N!" banner now sits — see that
        # method's own comment). Stacked just above pile-centre so the
        # "must pick" banner, directly below pile-centre, never touches it.
        pile_rect = self.draw_pile_rect()
        font = self.assets.font_scaled('ui_large', self.font_scale)
        text = font.render(f"Pick up: +{pickup_count}", True, (220, 80, 80))
        bg = pygame.Surface((text.get_width() + 20, text.get_height() + 10),
                             pygame.SRCALPHA)
        pygame.draw.rect(bg, (80, 20, 20, 200), bg.get_rect(), border_radius=8)
        bg.blit(text, (10, 5))
        gap = round(34 * self.font_scale)
        mid_gap = round(4 * self.font_scale)
        bx = pile_rect.right + gap
        by = pile_rect.centery - mid_gap - bg.get_height()
        surf.blit(bg, (bx, by))

    # ─── Player panels ────────────────────────────────────────────────────────

    def draw_player_info(self, surf: pygame.Surface, player: Player,
                         layout: Dict, is_current: bool, is_kadi: bool,
                         score: int = 0):
        cx   = layout['hand_cx']
        cy   = layout['hand_cy']
        face = layout['face_up']
        card_h = layout.get('card_h', self.card_h)
        fs = layout.get('font_scale', self.font_scale)

        # Fonts measured up front — bw/bh (and the two lines' own y
        # offsets further down) are derived from their REAL rendered
        # heights, not fixed pixel guesses. The old fixed 4px/22px line
        # offsets didn't grow with fs the way these fonts do, so at
        # higher resolutions the name and "Cards: N" line ended up
        # overlapping EACH OTHER inside the badge (confirmed via a
        # real, full-resolution crop at 3840x2160 — not just a
        # downscaled screenshot, where this was subtle enough to miss).
        name_font = self.assets.font_scaled('player_name', fs)
        cnt_font = self.assets.font_scaled('ui_small', fs)
        name_line_h = name_font.get_height()
        cnt_line_h = cnt_font.get_height()
        pad_v = round(4 * fs)
        line_gap = round(2 * fs)

        # Info box
        bw = round(130 * fs)
        bh = pad_v + name_line_h + line_gap + cnt_line_h + pad_v
        bx = int(cx - bw // 2)

        # Position above or below hand
        if face:  # human at bottom
            by = int(cy + card_h // 2 + 16)
        else:
            by = int(cy - card_h // 2 - bh - 10)

        # Push clear of the discard/draw pile's own footprint (cards +
        # "Discard"/"Draw (N)" labels below them) if the two would
        # otherwise collide — a PRE-EXISTING bug, not something this
        # session's resolution-scaling work introduced (confirmed: it
        # reproduces identically at the original 1280x800 baseline,
        # not just at scaled-up resolutions). In a 2-player game
        # specifically, the opponent seat sits close enough to the
        # table's vertical centre that its info panel and the pile
        # labels below the pile land at nearly the same y-coordinate —
        # "Bob"/"Discard" rendering on top of each other, and (less
        # obviously) the human seat's panel touching the pile from the
        # other side too. Pile geometry is available on self (this
        # class also draws the piles), so this checks the real,
        # current pile footprint rather than a guessed constant. Only
        # the pile's own x-span counts (draw pos to discard pos plus
        # card width) — a side seat that's nowhere near the pile
        # horizontally must never get pushed around by a check that
        # only actually matters for seats sitting close to table
        # centre.
        pile_cx, pile_cy = self._pile_center()
        pile_label_h = self.assets.font_scaled('ui_small', fs).get_height()
        pile_top = pile_cy - self.card_h // 2
        pile_bottom = pile_cy + self.card_h // 2 + pile_label_h + 6
        discard_x, draw_x = self._discard_pos()[0], self._draw_pos()[0]
        pile_left = min(discard_x, draw_x) - 6
        pile_right = max(discard_x, draw_x) + self.card_w + 6
        badge_rect = pygame.Rect(bx, by, bw, bh)
        pile_zone = pygame.Rect(pile_left, pile_top, pile_right - pile_left, pile_bottom - pile_top)
        if badge_rect.colliderect(pile_zone):
            # Push further AWAY from the pile's own centre, in
            # whichever vertical direction this seat is already on —
            # not simply "up" or "down" by whether it's the human seat,
            # since seat position on the oval (not face_up/human-ness)
            # is what actually determines which side of the pile a
            # given seat's badge is on.
            if cy < pile_cy:
                by = min(by, pile_top - bh - 6)
            else:
                by = max(by, pile_bottom + 6)

        # KADI glow — a player sitting on exactly one card is one play away
        # from winning, so their info panel gets a pulsing multi-layer glow
        # halo (same bloom technique as the hint-card highlight) instead of
        # just a thin static border, which was easy to miss at a glance.
        if is_kadi:
            phase = (pygame.time.get_ticks() % 1100) / 1100.0
            pulse = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
            for pad, base_a in ((14, 40), (9, 65), (4, 100)):
                glow_rect = pygame.Rect(bx - pad, by - pad, bw + pad * 2, bh + pad * 2)
                glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
                a = int(base_a * (0.5 + 0.5 * pulse))
                pygame.draw.rect(glow_surf, (*KADI_COLOR, a), glow_surf.get_rect(),
                                 border_radius=8 + pad)
                surf.blit(glow_surf, glow_rect.topleft)

        # Background
        bg_col = (200, 160, 0, 180) if is_current else (20, 50, 30, 180)
        if getattr(player, 'finished', False):
            bg_col = (60, 60, 70, 180)  # dimmed — out of the round
        s = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(s, bg_col, s.get_rect(), border_radius=8)
        if is_kadi:
            pygame.draw.rect(s, (220, 50, 50, 220), s.get_rect(), width=2, border_radius=8)
        surf.blit(s, (bx, by))

        # Name
        name_surf = name_font.render(player.name[:12], True, WHITE if not is_current else BLACK)
        surf.blit(name_surf, (bx + 6, by + pad_v))

        # Card count — or elimination placement, if this player is
        # already out for the round (Elimination Mode).
        cnt_y = by + pad_v + name_line_h + line_gap
        if getattr(player, 'finished', False):
            place = getattr(player, 'finish_place', None)
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(place, 'th') if place else ''
            cnt_str = f"OUT — {place}{suffix}" if place else "OUT"
            cnt_surf = cnt_font.render(cnt_str, True, (200, 200, 210))
            surf.blit(cnt_surf, (bx + 6, cnt_y))
        else:
            cnt_str = f"Cards: {player.hand.count}"
            if is_kadi:
                cnt_str += " KADI!"
            cnt_surf = cnt_font.render(cnt_str, True, KADI_COLOR if is_kadi else WHITE)
            surf.blit(cnt_surf, (bx + 6, cnt_y))

        # Score badge
        if score > 0:
            sc_font = self.assets.font_scaled('ui_tiny', fs)
            sc_surf = sc_font.render(f"W:{score}", True, GOLD_LIGHT)
            surf.blit(sc_surf, (bx + bw - sc_surf.get_width() - 6, by + 4))

    def draw_hand(self, surf: pygame.Surface, player: Player,
                  layout: Dict, selected: Set[int], playable: Set[int],
                  hovered: Optional[int], is_current: bool,
                  drag_idx: Optional[int] = None,
                  drag_pos: Optional[Tuple[int, int]] = None,
                  drag_target: Optional[int] = None,
                  hint_idx: Optional[int] = None,
                  reveal_override: Optional[bool] = None):
        # reveal_override lets a caller force every seat's cards face-up
        # regardless of the normal "only seat 0 (human) is face-up" rule
        # — used for AI Spectator Mode, where every remaining player is
        # an AI and there's no hidden-information reason left to keep
        # their hands hidden from whoever's watching.
        is_seat0 = layout['face_up']
        face_up = is_seat0 if reveal_override is None else reveal_override
        cx = layout['hand_cx']
        cy = layout['hand_cy']
        # Reveal-override seats stay in their normal (smaller) compact
        # layout even though they're flipped face-up — the wide spread
        # is tuned for the bottom human seat only and would run off-screen
        # from the side/top seats AI hands sit in. max-widths are
        # resolution-scaled now (layout['human_max_width'] etc, from
        # _resolve_layout_metrics) instead of the old flat 520/360/280.
        compact = not is_seat0
        if is_seat0:
            max_width = layout.get('human_max_width', 520)
        elif face_up:
            max_width = layout.get('opp_reveal_max_width', 360)
        else:
            max_width = layout.get('opp_max_width', 280)

        self.hand_renderer.render(
            surf, player.hand.cards, cx, cy,
            face_up=face_up, selected=selected, playable=playable,
            hovered=hovered, is_current=is_current,
            max_width=max_width,
            compact=compact,
            drag_idx=drag_idx if is_seat0 else None,
            drag_pos=drag_pos if is_seat0 else None,
            drag_target=drag_target if is_seat0 else None,
            hint_idx=hint_idx if is_seat0 else None,
            base_w=layout.get('card_w', self.card_w),
            base_h=layout.get('card_h', self.card_h),
        )

    def get_human_card_at(self, mx: int, my: int, player: Player,
                          layout: Dict) -> Optional[int]:
        return self.hand_renderer.get_card_at(
            player.hand.cards, mx, my,
            layout['hand_cx'], layout['hand_cy'],
            face_up=True, max_width=layout.get('human_max_width', 520),
            base_w=layout.get('card_w', self.card_w),
            base_h=layout.get('card_h', self.card_h),
        )

    def get_human_drop_index(self, mx: int, player: Player,
                             layout: Dict) -> int:
        return self.hand_renderer.get_drop_index(
            mx, player.hand.count,
            layout['hand_cx'], layout['hand_cy'],
            max_width=layout.get('human_max_width', 520),
            base_w=layout.get('card_w', self.card_w),
            base_h=layout.get('card_h', self.card_h),
        )

    # ─── Piles interactive zones ───────────────────────────────────────────────

    def draw_pile_rect(self) -> pygame.Rect:
        draw_pos = self._draw_pos()
        return pygame.Rect(draw_pos[0], draw_pos[1], self.card_w, self.card_h)

    def discard_pile_rect(self) -> pygame.Rect:
        discard_pos = self._discard_pos()
        return pygame.Rect(discard_pos[0], discard_pos[1], self.card_w, self.card_h)


GOLD_LIGHT = (255, 215, 0)
