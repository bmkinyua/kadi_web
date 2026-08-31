"""
KADI - Asset Loader
Procedurally generates all card surfaces and caches them.
No external image files needed.
"""
from __future__ import annotations
import pygame
import math
import os
import random
from typing import Dict, Optional, Tuple
from constants import (
    CARD_W, CARD_H, CARD_RAD, CARD_BG, CARD_BORDER,
    CARD_BACK_A, CARD_BACK_B, SUIT_SYMBOL, SUIT_ICON, SUIT_COLOR, SUIT_ACCENT,
    BLACK, WHITE, RED_SUIT, DARK_GRAY, MID_GRAY,
    Suit, RANKS, RANK_DISPLAY, CARD_BACK_STYLES, resource_base_dir
)
from models.card import Card
from rendering.widgets import draw_icon
from rendering.music_manager import MusicManager

# Music track credits — filled in with the specific CC0/CC BY tracks
# recommended alongside this feature. If a track file isn't present at
# its path (e.g. not yet downloaded), the game runs fine with that loop
# silently absent — see _load_music_track(). Update this list to match
# whatever files actually end up in assets/music/.
MUSIC_CREDITS = [
    {
        'slot':    'Menu Theme',
        'title':   'Jazzy blues',
        'author':  'LushoGames',
        'license': 'CC0',
        'url':     'https://opengameart.org/content/jazzy-blues',
    },
    {
        'slot':    'Gameplay Ambient',
        'title':   'Heavenly Loop',
        'author':  'isaiah658',
        'license': 'CC0',
        'url':     'https://opengameart.org/content/heavenly-loop',
    },
    {
        'slot':    'Chuo Drums',
        'title':   'Djembe Loop 08 - 120 BPM',
        'author':  'Ancient.Sounds',
        'license': 'CC0',
        'url':     'https://freesound.org/people/Ancient.Sounds/sounds/485474/',
    },
]

MUSIC_FILES = {
    'menu':     'menu_theme.ogg',
    'gameplay': 'gameplay_ambient.ogg',
    'chuo':     'chuo_drums.ogg',
}


class AssetLoader:
    def __init__(self):
        self._card_faces: Dict[str, pygame.Surface] = {}
        self._card_back: Optional[pygame.Surface] = None
        # Cosmetics (Profile Part 2): every card-back style is generated
        # up front and cached by style key; get_card_back()/
        # get_card_surface(face_up=False) return whichever is currently
        # "equipped" (see set_equipped_card_back()). Defaults to the
        # classic style so a profile-less/first-run game looks exactly
        # like it always did.
        self._card_backs: Dict[str, pygame.Surface] = {}
        self._equipped_card_back: str = "default"
        self._scaled_card_cache: Dict[Tuple, pygame.Surface] = {}
        self._fonts: Dict[str, pygame.font.Font] = {}
        self._sounds: Dict[str, Optional[pygame.mixer.Sound]] = {}
        self._initialized = False
        self.music = MusicManager()
        self.sfx_enabled: bool = True
        self._sound_volume: float = 0.7

    def init(self):
        if self._initialized:
            return
        pygame.font.init()
        self._load_fonts()
        self._generate_all_cards()
        self._load_sounds()
        self._load_music()
        self._initialized = True
        self._sound_volume = 0.7

    # ─── Fonts ────────────────────────────────────────────────────────────────
    #
    # Phase 2 typography: one display font (Cinzel — real card-table
    # character for the big/dramatic text) and one body font (Poppins —
    # clean and legible for everything else), both fetched from the
    # official google/fonts repo (SIL OFL, no attribution required). Falls
    # back to the old generic-ttf-or-SysFont behaviour if the font files
    # aren't present, so this never hard-fails on a stripped-down checkout.

    def _load_fonts(self):
        font_dir = os.path.join(resource_base_dir(), 'assets', 'fonts')
        display_path      = os.path.join(font_dir, 'Cinzel-Variable.ttf')
        body_regular_path = os.path.join(font_dir, 'Poppins-Regular.ttf')
        body_bold_path    = os.path.join(font_dir, 'Poppins-Bold.ttf')
        legacy_path       = os.path.join(font_dir, 'game_font.ttf')

        have_display = os.path.exists(display_path)
        have_body    = os.path.exists(body_regular_path) and os.path.exists(body_bold_path)
        have_legacy  = os.path.exists(legacy_path)

        # Resolved once — which actual font FILE each "kind" uses, bold or
        # not. 'body-regular'/'body-bold'/'display' cover every named font
        # below; _make_font() looks this up so font_scaled() can rebuild
        # any of them at an arbitrary size without repeating this fallback
        # chain (real font -> legacy bundled font -> OS Arial).
        self._font_kind_path = {
            'body-regular': body_regular_path if have_body else (legacy_path if have_legacy else None),
            'body-bold':    body_bold_path    if have_body else (legacy_path if have_legacy else None),
            'display':      display_path      if have_display else (legacy_path if have_legacy else None),
        }

        # name -> (kind, base_size, bold)
        self._font_specs = {
            'card_rank_lg':  ('body', 28, True),
            'card_rank_sm':  ('body', 14, True),
            'card_symbol':   ('body', 40, False),
            'card_sym_sm':   ('body', 16, False),
            'ui_title':      ('display', 52, False),
            'kadi_banner':   ('display', 60, False),
            'ui_large':      ('body', 32, True),
            'ui_medium':     ('body', 22, True),
            'ui_normal':     ('body', 18, False),
            'ui_small':      ('body', 14, False),
            'ui_tiny':       ('body', 11, False),
            'player_name':   ('body', 16, True),
            'counter_timer': ('body', 48, True),
            'tooltip':       ('body', 13, False),
        }

        self._font_scale_cache: Dict[Tuple[str, int], pygame.font.Font] = {}
        self._fonts = {
            name: self._make_font(kind, size, bold)
            for name, (kind, size, bold) in self._font_specs.items()
        }

    def _make_font(self, kind: str, size: int, bold: bool) -> pygame.font.Font:
        size = max(6, size)
        path_kind = 'display' if kind == 'display' else ('body-bold' if bold else 'body-regular')
        path = self._font_kind_path.get(path_kind)
        if path:
            return pygame.font.Font(path, size)
        return pygame.font.SysFont('Arial', size, bold=bold)

    def font(self, name: str) -> pygame.font.Font:
        return self._fonts.get(name, self._fonts.get('ui_normal'))

    def font_scaled(self, name: str, scale: float) -> pygame.font.Font:
        """Same named font, resized by `scale` — cached. Deliberately
        SEPARATE from font(), which stays exactly as before (fixed base
        size) everywhere: most of the app's buttons/panels are still
        fixed-pixel-sized and were never audited for what happens when
        the text inside them grows, so blanket-scaling font() itself
        would risk overflowing them. This is only used by call sites
        whose surrounding geometry has actually been made resolution-
        aware alongside it (currently: BoardRenderer's gameplay-table
        text, and the Settings/Rules panel width)."""
        spec = self._font_specs.get(name) or self._font_specs.get('ui_normal')
        base_size = spec[1]
        size = max(6, round(base_size * scale))
        key = (name, size)
        cached = self._font_scale_cache.get(key)
        if cached is None:
            cached = self._make_font(spec[0], size, spec[2])
            self._font_scale_cache[key] = cached
        return cached

    # ─── Card surfaces ────────────────────────────────────────────────────────

    def _generate_all_cards(self):
        # Standard cards
        for suit in Suit:
            for rank in RANKS:
                key = f"{rank}_{suit.value}"
                self._card_faces[key] = self._make_card_face(suit, rank)
        # Jokers
        self._card_faces['JOKER_Red']   = self._make_joker_face(red=True)
        self._card_faces['JOKER_Black'] = self._make_joker_face(red=False)
        # Back — one surface per cosmetic style, cached; get_card_back()
        # returns whichever is currently equipped.
        for style_key in CARD_BACK_STYLES:
            self._card_backs[style_key] = self._make_card_back(style_key)
        self._card_back = self._card_backs["default"]
        # Special: hidden/unknown placeholder
        self._card_faces['HIDDEN'] = self._make_hidden_card()

    def get_card_surface(self, card: Card, face_up: bool = True) -> pygame.Surface:
        if not face_up:
            return self._card_back
        if card.rank == 'JOKER':
            key = 'JOKER_Red' if card.is_red_joker else 'JOKER_Black'
        else:
            key = f"{card.rank}_{card.suit.value}"
        return self._card_faces.get(key, self._card_faces.get('HIDDEN'))

    def get_card_back(self) -> pygame.Surface:
        return self._card_back

    def set_equipped_card_back(self, style_key: str):
        """Switch which pre-generated card-back style get_card_back()/
        get_card_surface(face_up=False) return — called once at startup
        from the loaded profile's equipped cosmetic, and again live from
        the Profile screen's equip controls. Falls back to 'default' for
        an unknown/legacy style key rather than raising."""
        self._equipped_card_back = style_key if style_key in self._card_backs else "default"
        self._card_back = self._card_backs[self._equipped_card_back]
        # Any (card, size) pairs cached under the OLD back surface's id()
        # would otherwise keep rendering the previous style at scaled
        # sizes — see get_card_surface_scaled()'s cache key. The cache is
        # small (a handful of entries), so just clear it outright rather
        # than trying to selectively evict only the back-related keys.
        self._scaled_card_cache.clear()

    def get_equipped_card_back(self) -> str:
        return self._equipped_card_back

    def get_card_back_preview(self, style_key: str) -> Optional[pygame.Surface]:
        """The generated surface for a given style, regardless of which
        one is currently equipped — used by the Profile screen to render
        the cosmetics inventory."""
        return self._card_backs.get(style_key)

    def get_card_surface_scaled(self, card: Card, face_up: bool,
                                 w: int, h: int) -> pygame.Surface:
        """Same as get_card_surface(), but resized to (w, h) — cached, so
        resolution-based card scaling (which now requests a size that
        almost never matches the flat base CARD_W/CARD_H) doesn't re-run
        pygame.transform.smoothscale on every single card, every frame.
        The cache is naturally small: at most a handful of distinct
        (card, size) pairs are ever on screen in one session (one size
        per hand type at the current resolution), so it's never cleared."""
        base = self.get_card_surface(card, face_up)
        if base.get_size() == (w, h):
            return base
        key = (id(base), w, h)
        cached = self._scaled_card_cache.get(key)
        if cached is None:
            cached = pygame.transform.smoothscale(base, (w, h))
            self._scaled_card_cache[key] = cached
        return cached

    def get_card_back_scaled(self, w: int, h: int) -> pygame.Surface:
        return self.get_card_surface_scaled(None, False, w, h)  # face_up=False ignores `card`

    def _make_card_face(self, suit: Suit, rank: str) -> pygame.Surface:
        surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        # Card body
        body_rect = pygame.Rect(0, 0, CARD_W, CARD_H)
        pygame.draw.rect(surf, CARD_BG, body_rect, border_radius=CARD_RAD)

        # Subtle top-to-bottom shading — softens the flat fill without
        # changing the card design (a couple of near-transparent bands).
        shade = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        pygame.draw.rect(shade, (255, 255, 255, 14), (0, 0, CARD_W, CARD_H // 2),
                         border_radius=CARD_RAD)
        pygame.draw.rect(shade, (0, 0, 0, 10), (0, CARD_H // 2, CARD_W, CARD_H // 2),
                         border_radius=CARD_RAD)
        surf.blit(shade, (0, 0))

        pygame.draw.rect(surf, CARD_BORDER, body_rect, width=2, border_radius=CARD_RAD)

        color = SUIT_COLOR[suit]
        icon_kind = SUIT_ICON[suit]
        disp_rank = RANK_DISPLAY.get(rank, rank)
        accent = SUIT_ACCENT[suit]

        # Subtle accent stripe at top
        stripe = pygame.Rect(2, 2, CARD_W - 4, 6)
        pygame.draw.rect(surf, (*accent, 80), stripe, border_radius=4)

        # Top-left rank + symbol. The suit symbol is a vector icon (not a
        # SUIT_SYMBOL Unicode glyph) since this project's body font
        # (Poppins) doesn't include the card-suit Unicode block at all —
        # those glyphs rendered as tofu boxes. Same fix already used below
        # for KICKBACK/JUMP/etc.
        rank_font = self._fonts['card_rank_lg']
        rank_surf = rank_font.render(disp_rank, True, color)
        surf.blit(rank_surf, (5, 4))
        sym_size = 16
        sym_surf = pygame.Surface((sym_size, sym_size), pygame.SRCALPHA)
        draw_icon(sym_surf, sym_surf.get_rect(), icon_kind, color, width=2)
        surf.blit(sym_surf, (5, 4 + rank_surf.get_height()))

        # Center large symbol
        big_size = 40
        big_sym = pygame.Surface((big_size, big_size), pygame.SRCALPHA)
        draw_icon(big_sym, big_sym.get_rect(), icon_kind, color, width=3)
        cx = (CARD_W - big_sym.get_width()) // 2
        cy = (CARD_H - big_sym.get_height()) // 2
        surf.blit(big_sym, (cx, cy))

        # Bottom-right rank + symbol (rotated) — real playing cards show
        # this corner upside-down too, so rotating the vector icon matches
        # the traditional look rather than being an artifact.
        rank_surf2 = rank_font.render(disp_rank, True, color)
        sym_surf2  = pygame.Surface((sym_size, sym_size), pygame.SRCALPHA)
        draw_icon(sym_surf2, sym_surf2.get_rect(), icon_kind, color, width=2)
        r2 = pygame.transform.rotate(rank_surf2, 180)
        s2 = pygame.transform.rotate(sym_surf2, 180)
        surf.blit(r2, (CARD_W - r2.get_width() - 5, CARD_H - r2.get_height() - sym_surf2.get_height() - 4))
        surf.blit(s2, (CARD_W - s2.get_width() - 5, CARD_H - s2.get_height() - 4))

        # Special card label at bottom center.
        # NOTE: KICKBACK/JUMP/SUIT_CHANGE/FINISHING are drawn as vector
        # icons (draw_icon) rather than Unicode glyphs (was: ↺ ⤳ ✦ ★),
        # since those symbols are frequently missing from bundled/system
        # fonts and were rendering as black tofu-box placeholders.
        from constants import CardType, get_card_type
        ct = get_card_type(rank)
        text_label_map = {
            CardType.QUESTION:  ("?",  (100, 60, 180)),
            CardType.PICKUP_2:  ("+2", (200, 80, 0)),
            CardType.PICKUP_3:  ("+3", (200, 80, 0)),
        }
        icon_label_map = {
            CardType.KICKBACK:    ('kickback', (180, 60, 60)),
            CardType.JUMP:        ('jump', (60, 120, 180)),
            CardType.SUIT_CHANGE: ('sparkle', (180, 130, 0)),
            CardType.FINISHING:   ('star', (60, 150, 60)),
        }
        if ct in text_label_map:
            lbl_text, lbl_color = text_label_map[ct]
            lbl_font = self._fonts['card_sym_sm']
            lbl_surf = lbl_font.render(lbl_text, True, lbl_color)
            lx = (CARD_W - lbl_surf.get_width()) // 2
            surf.blit(lbl_surf, (lx, CARD_H - lbl_surf.get_height() - 6))
        elif ct in icon_label_map:
            icon_kind, icon_color = icon_label_map[ct]
            badge_rect = pygame.Rect(0, 0, 18, 18)
            badge_rect.centerx = CARD_W // 2
            badge_rect.bottom = CARD_H - 6
            draw_icon(surf, badge_rect, icon_kind, icon_color, width=2)

        return surf

    def _make_joker_face(self, red: bool) -> pygame.Surface:
        surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        body_rect = pygame.Rect(0, 0, CARD_W, CARD_H)
        bg_color = (255, 245, 245) if red else (240, 240, 255)
        pygame.draw.rect(surf, bg_color, body_rect, border_radius=CARD_RAD)

        border_color = (180, 30, 30) if red else (30, 30, 120)
        pygame.draw.rect(surf, border_color, body_rect, width=3, border_radius=CARD_RAD)

        text_color = (200, 20, 20) if red else (20, 20, 150)

        # "JKR" text top-left
        rnk = self._fonts['card_rank_lg'].render('JKR', True, text_color)
        surf.blit(rnk, (5, 5))

        # Big jester-hat symbol center — drawn as a vector icon instead of
        # a plain star, per feedback that a star didn't feel joker-y.
        star_rect = pygame.Rect(0, 0, int(CARD_W * 0.42), int(CARD_W * 0.42))
        star_rect.center = (CARD_W // 2, CARD_H // 2 - 5)
        draw_icon(surf, star_rect, 'jester_hat', text_color, width=2)

        # "+5" label
        plus = self._fonts['card_rank_sm'].render('+5', True, text_color)
        px = (CARD_W - plus.get_width()) // 2
        surf.blit(plus, (px, CARD_H - plus.get_height() - 6))

        # Bottom-right rotated
        rnk2 = pygame.transform.rotate(self._fonts['card_rank_lg'].render('JKR', True, text_color), 180)
        surf.blit(rnk2, (CARD_W - rnk2.get_width() - 5, CARD_H - rnk2.get_height() - 5))

        return surf

    def _make_card_back(self, style_key: str = "default") -> pygame.Surface:
        """Procedurally generates a card back for the given cosmetic
        style (see constants.CARD_BACK_STYLES) — same body/inner-border/
        center-diamond/outer-border structure as the original design,
        just a different base color pair and pattern per style. No new
        art assets; this is the exact same generator the original single
        design used, parameterized (Profile Part 2)."""
        style = CARD_BACK_STYLES.get(style_key, CARD_BACK_STYLES["default"])
        color_a, color_b, pattern = style["a"], style["b"], style["pattern"]

        surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        body_rect = pygame.Rect(0, 0, CARD_W, CARD_H)
        pygame.draw.rect(surf, color_a, body_rect, border_radius=CARD_RAD)

        if pattern == "diagonal":
            for i in range(-CARD_H, CARD_W + CARD_H, 18):
                pygame.draw.line(surf, color_b, (i, 0), (i + CARD_H, CARD_H), 2)
        elif pattern == "crosshatch":
            for i in range(-CARD_H, CARD_W + CARD_H, 20):
                pygame.draw.line(surf, color_b, (i, 0), (i + CARD_H, CARD_H), 2)
                pygame.draw.line(surf, color_b, (i + CARD_H, 0), (i, CARD_H), 2)
        elif pattern == "dots":
            for yy in range(10, CARD_H - 10, 16):
                offset = 8 if (yy // 16) % 2 else 0
                for xx in range(10 + offset, CARD_W - 10, 16):
                    pygame.draw.circle(surf, color_b, (xx, yy), 3)
        elif pattern == "chevron":
            step = 16
            for yy in range(-step, CARD_H + step, step):
                pts = []
                x = 0
                up = True
                while x <= CARD_W:
                    pts.append((x, yy + (6 if up else -6)))
                    x += step
                    up = not up
                if len(pts) >= 2:
                    pygame.draw.lines(surf, color_b, False, pts, 2)
        elif pattern == "starfield":
            rng = random.Random(1234)  # fixed seed: identical every regen, no flicker on re-equip
            for _ in range(40):
                x = rng.randint(6, CARD_W - 6)
                y = rng.randint(6, CARD_H - 6)
                r = rng.choice([1, 1, 1, 2])
                pygame.draw.circle(surf, color_b, (x, y), r)
        elif pattern == "houndstooth":
            step = 14
            for row, yy in enumerate(range(0, CARD_H, step)):
                offset = (step // 2) if row % 2 else 0
                for xx in range(-step + offset, CARD_W, step):
                    pts = [(xx, yy), (xx + step // 2, yy), (xx + step // 2, yy + step // 2),
                           (xx + step, yy + step // 2), (xx + step, yy + step), (xx + step // 2, yy + step)]
                    pygame.draw.polygon(surf, color_b, pts, 0)
        elif pattern == "hex_lattice":
            hex_r = 9
            dx, dy = hex_r * 1.8, hex_r * 1.6
            row = 0
            yy = -hex_r
            while yy < CARD_H + hex_r:
                offset = (dx / 2) if row % 2 else 0
                xx = -hex_r + offset
                while xx < CARD_W + hex_r:
                    pts = [(xx + hex_r * math.cos(math.radians(60 * i)),
                            yy + hex_r * math.sin(math.radians(60 * i))) for i in range(6)]
                    pygame.draw.polygon(surf, color_b, pts, 1)
                    xx += dx
                yy += dy
                row += 1
        elif pattern == "herringbone_back":
            step = 10
            for yy in range(0, CARD_H, step * 2):
                for xx in range(-CARD_H, CARD_W, step * 2):
                    pygame.draw.line(surf, color_b, (xx, yy), (xx + step, yy + step), 2)
                    pygame.draw.line(surf, color_b, (xx + step, yy), (xx + step * 2, yy + step), 2)
                    pygame.draw.line(surf, color_b, (xx, yy + step * 2), (xx + step, yy + step), 2)
                    pygame.draw.line(surf, color_b, (xx + step, yy + step * 2), (xx + step * 2, yy + step), 2)
        elif pattern == "pinwheel":
            cx, cy = CARD_W // 2, CARD_H // 2
            blades = 8
            blade_len = 32
            for i in range(blades):
                a0 = math.radians(i * (360 / blades))
                a1 = a0 + math.radians(360 / blades * 0.4)
                p1 = (cx + blade_len * math.cos(a0), cy + blade_len * math.sin(a0))
                p2 = (cx + blade_len * math.cos(a1), cy + blade_len * math.sin(a1))
                pygame.draw.polygon(surf, color_b, [(cx, cy), p1, p2], 0)
        elif pattern == "concentric_diamonds":
            cx, cy = CARD_W // 2, CARD_H // 2
            for r in range(10, max(CARD_W, CARD_H), 14):
                pts = [(cx, cy - r), (cx + r * 0.7, cy), (cx, cy + r), (cx - r * 0.7, cy)]
                pygame.draw.polygon(surf, color_b, pts, 2)
        elif pattern == "basket_weave":
            cell = 12
            for row, yy in enumerate(range(0, CARD_H, cell)):
                for col, xx in enumerate(range(0, CARD_W, cell)):
                    if (row + col) % 2 == 0:
                        rect = pygame.Rect(xx, yy, cell, cell)
                        pygame.draw.rect(surf, color_b, rect, 0)
        elif pattern == "checkerboard_back":
            cell = 10
            for row, yy in enumerate(range(0, CARD_H, cell)):
                for col, xx in enumerate(range(0, CARD_W, cell)):
                    if (row + col) % 2 == 0:
                        rect = pygame.Rect(xx, yy, cell, cell)
                        pygame.draw.rect(surf, color_b, rect, 0)
        elif pattern == "honeycomb_back":
            hex_r = 11
            dx, dy = hex_r * 1.7, hex_r * 1.5
            row = 0
            yy = -hex_r
            while yy < CARD_H + hex_r:
                offset = (dx / 2) if row % 2 else 0
                xx = -hex_r + offset
                while xx < CARD_W + hex_r:
                    pts = [(xx + hex_r * math.cos(math.radians(60 * i)),
                            yy + hex_r * math.sin(math.radians(60 * i))) for i in range(6)]
                    pygame.draw.polygon(surf, color_b, pts, 0)
                    xx += dx
                yy += dy
                row += 1
        elif pattern == "sunburst":
            cx, cy = CARD_W // 2, CARD_H // 2
            rays = 16
            for i in range(rays):
                a = math.radians(i * (360 / rays))
                end = (cx + CARD_H * math.cos(a), cy + CARD_H * math.sin(a))
                pygame.draw.line(surf, color_b, (cx, cy), end, 1)
        elif pattern == "bullseye":
            cx, cy = CARD_W // 2, CARD_H // 2
            for r in range(8, max(CARD_W, CARD_H), 10):
                pygame.draw.circle(surf, color_b, (cx, cy), r, 2)
        elif pattern == "zigzag":
            step = 14
            for yy in range(6, CARD_H - 6, step):
                pts = []
                x = 0
                up = True
                while x <= CARD_W:
                    pts.append((x, yy + (5 if up else -5)))
                    x += step // 2
                    up = not up
                if len(pts) >= 2:
                    pygame.draw.lines(surf, color_b, False, pts, 2)

        # Inner border
        inner = pygame.Rect(7, 7, CARD_W - 14, CARD_H - 14)
        pygame.draw.rect(surf, (*WHITE, 60), inner, width=2, border_radius=6)

        # Center diamond
        cx, cy = CARD_W // 2, CARD_H // 2
        pts = [(cx, cy - 20), (cx + 14, cy), (cx, cy + 20), (cx - 14, cy)]
        pygame.draw.polygon(surf, (*WHITE, 120), pts)

        # Outer border
        pygame.draw.rect(surf, WHITE, body_rect, width=2, border_radius=CARD_RAD)

        return surf

    def _make_hidden_card(self) -> pygame.Surface:
        surf = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
        pygame.draw.rect(surf, (150, 150, 150), (0, 0, CARD_W, CARD_H), border_radius=CARD_RAD)
        pygame.draw.rect(surf, (100, 100, 100), (0, 0, CARD_W, CARD_H), width=2, border_radius=CARD_RAD)
        q = self._fonts['card_symbol'].render('?', True, (200, 200, 200))
        surf.blit(q, ((CARD_W - q.get_width()) // 2, (CARD_H - q.get_height()) // 2))
        return surf

    # ─── Sounds ───────────────────────────────────────────────────────────────

    def _load_sounds(self):
        """Generate simple beep sounds procedurally if no files present."""
        keys = ['deal', 'play_card', 'draw_card', 'kadi_declare',
                'win', 'error', 'button_click', 'pickup', 'counter']
        for k in keys:
            self._sounds[k] = self._make_beep(k)

    def _make_beep(self, kind: str) -> Optional[pygame.mixer.Sound]:
        """Generate a simple synthesized sound."""
        try:
            import numpy as np
            sr = 44100
            configs = {
                'deal':         (440, 0.05, 0.3),
                'play_card':    (523, 0.08, 0.2),
                'draw_card':    (330, 0.06, 0.25),
                'kadi_declare': (660, 0.12, 0.5),
                'win':          (880, 0.15, 0.8),
                'error':        (220, 0.10, 0.3),
                'button_click': (600, 0.05, 0.1),
                'pickup':       (280, 0.10, 0.4),
                'counter':      (750, 0.12, 0.4),
            }
            freq, vol, dur = configs.get(kind, (440, 0.08, 0.2))
            t = np.linspace(0, dur, int(sr * dur), False)
            wave = np.sin(2 * np.pi * freq * t)
            # Envelope
            env = np.ones_like(t)
            attack = int(0.01 * sr)
            release = int(0.1 * sr)
            env[:attack] = np.linspace(0, 1, attack)
            if release < len(env):
                env[-release:] = np.linspace(1, 0, release)
            wave = (wave * env * vol * 32767).astype(np.int16)
            stereo = np.column_stack([wave, wave])
            sound = pygame.sndarray.make_sound(stereo)
            return sound
        except Exception:
            return None

    # ─── Music ────────────────────────────────────────────────────────────────

    def _load_music(self):
        """Load the three background loops if their files are present.
        A missing file is not an error — that slot just stays silent
        (MusicManager.bind handles None gracefully) so the game runs
        exactly as before if music assets haven't been dropped in yet."""
        music_dir = os.path.join(resource_base_dir(), 'assets', 'music')
        loaded = {}
        for key, filename in MUSIC_FILES.items():
            path = os.path.join(music_dir, filename)
            loaded[key] = self._load_music_track(path)
        self.music.bind(loaded.get('menu'), loaded.get('gameplay'), loaded.get('chuo'))

    def _load_music_track(self, path: str) -> Optional[pygame.mixer.Sound]:
        if not os.path.exists(path):
            return None
        try:
            return pygame.mixer.Sound(path)
        except Exception:
            return None

    def set_music_enabled(self, enabled: bool):
        self.music.set_enabled(enabled)

    def set_music_volume(self, volume: float):
        self.music.set_volume(volume)

    def set_sfx_enabled(self, enabled: bool):
        self.sfx_enabled = enabled

    def set_sfx_volume(self, volume: float):
        self._sound_volume = max(0.0, min(1.0, volume))

    def play_sound(self, name: str, volume: float = -1):
        if not getattr(self, 'sfx_enabled', True):
            return
        if volume < 0:
            volume = getattr(self, '_sound_volume', 0.7)
        if volume <= 0:
            return
        s = self._sounds.get(name)
        if s:
            try:
                s.set_volume(volume)
                s.play()
            except Exception:
                pass

    # ─── Scaled card ──────────────────────────────────────────────────────────

    def get_scaled_card(self, card: Card, face_up: bool, scale: float = 1.0) -> pygame.Surface:
        if scale == 1.0:
            return self.get_card_surface(card, face_up)
        w, h = int(CARD_W * scale), int(CARD_H * scale)
        return self.get_card_surface_scaled(card, face_up, w, h)
