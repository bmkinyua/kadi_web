"""
KADI Card Game - Constants, Colors, and Enums
"""
import os
import sys
import pygame
from enum import Enum, auto
from typing import Tuple


def resource_base_dir() -> str:
    """Base directory for READ-ONLY bundled resources shipped with the
    app (fonts, music, icon, help illustrations) — NOT the per-user
    data directory (logs/profile/settings/msomi_models; see
    core.game_logger.base_dir() for that, a completely different,
    OS-conventional per-user location that already handles this
    correctly and doesn't need anything from this function).

    Resolves differently depending on how the app is actually running:
    - From source (`python main.py`): this file's (constants.py's) own
      directory — the project root, same level as main.py and assets/.
    - Frozen by PyInstaller into a real .exe/.app/binary: PyInstaller
      unpacks bundled data files into sys._MEIPASS at startup (true for
      BOTH --onefile and --onedir builds, despite their very different
      on-disk shape) — a temp/bundle location that has nothing to do
      with __file__ anymore once frozen.

    Every call site that loads a bundled asset should build its path
    from THIS function, not from `os.path.dirname(os.path.abspath(
    __file__))` directly — that pattern quietly breaks the moment the
    app is packaged, since __file__-relative paths only make sense
    when running from the actual source tree. See KADI.spec's `datas=`
    list for what actually ships alongside the frozen binary."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


# ─── Version ────────────────────────────────────────────────────────────────
# Single source of truth for the game's version string — used for the main
# menu footer AND the LAN/Internet Multiplayer version-check handshake (see
# network/client.py's 'hello' message and network/host_game.py's /
# server/kadi_server.py's 'welcome' reply). Bump this on release; nothing
# else needs to change to pick it up.
VERSION = "1.1"

# ─── Screen ───────────────────────────────────────────────────────────────────
SCREEN_W = 1280
SCREEN_H = 800
FPS      = 60
TITLE    = "KADI"

# ─── Card Dimensions ──────────────────────────────────────────────────────────
CARD_W   = 90
CARD_H   = 130
CARD_RAD = 10

# ─── Ad Banner Slot ───────────────────────────────────────────────────────────
# Static placeholder banner strip — see rendering approach in scenes.py's
# AdBanner class. Sits in the same header row as WindowControls/AudioControls
# (top-right) and the Menu/Pause buttons (top-left, GameplayScene only), in
# the horizontal gap between them, so on every OTHER included screen it needs
# no extra vertical space at all (those screens' titles all start at y>=50,
# comfortably below the banner's bottom edge).
#
# GameplayScene is the one exception: the human's own hand and the turn
# indicator both already occupy that same horizontal-center strip (see
# BoardRenderer's oval seat layout), so on that scene alone the whole table
# is shifted down by get_ad_reserved_top() to clear the banner — see
# GameplayScene._ad_top_pad() and BoardRenderer's top_margin plumbing.
#
# Banner WIDTH and HEIGHT are now computed dynamically per resolution
# (get_banner_size below) instead of a flat 34px-then-50px sliver — anchored
# to real IAB standard banner sizes (Mobile Leaderboard -> Full Banner ->
# Leaderboard -> Large Leaderboard -> Billboard) and scaled up from there, so
# the reserved vertical space actually grows at 1080p+ instead of staying a
# fixed height while everything else on screen gets bigger around it.
AD_BANNER_Y        = 6    # top inset — small and fixed; not worth scaling
AD_BANNER_GAP_BASE = 10   # minimum clearance below the banner before content

def get_banner_size(sw: int, sh: int) -> Tuple[int, int]:
    """Dynamic ad-banner (width, height), anchored to standard IAB banner
    sizes and scaled by resolution:
        scale <1.0  -> 320x50  Mobile Leaderboard
        scale <1.6  -> 468x60  Full Banner
        scale <2.2  -> 728x90  Leaderboard
        scale <3.2  -> 970x90  Large Leaderboard
        else        -> 970x250 Billboard
    then scaled by `scale` and clamped so it can never dominate the header
    (width <= 45% of sw, height <= 12% of sh, aspect preserved when clamped).
    """
    scale = max(0.8, min(4.0, sw / 1280))
    if scale < 1.0:
        base_w, base_h = 320, 50
    elif scale < 1.6:
        base_w, base_h = 468, 60
    elif scale < 2.2:
        base_w, base_h = 728, 90
    elif scale < 3.2:
        base_w, base_h = 970, 90
    else:
        base_w, base_h = 970, 250
    w, h = base_w * scale, base_h * scale
    max_w, max_h = sw * 0.45, sh * 0.12
    if w > max_w:
        h *= max_w / w
        w = max_w
    if h > max_h:
        w *= max_h / h
        h = max_h
    return round(w), round(h)

def get_ad_reserved_top(sw: int, sh: int) -> int:
    """Replaces the old flat AD_RESERVED_TOP constant — pixels the whole
    table needs to shift down to clear the (now dynamically-sized) banner
    strip, at the given resolution."""
    _, bh = get_banner_size(sw, sh)
    gap = max(AD_BANNER_GAP_BASE, round(sh * 0.012))
    return AD_BANNER_Y + bh + gap

# ─── Resolution-based UI scaling ───────────────────────────────────────────────
# Per-resolution profile — each entry tuned independently rather than off one
# shared curve, so a change at 4K/8K doesn't shift 1080p or below. Card size
# intentionally trends a bit ABOVE a purely linear (sw/1280) scale-up from 2K
# onward: linear alone keeps cards the same %-of-screen as the 1280x800
# baseline, which read as "too small" next to a much bigger table at 4K/8K
# even though nothing was technically broken about it.
UI_SCALE_PROFILES = {
    # button_scale mirrors font_scale exactly (not a coincidence — see
    # get_chrome_scale() below): fixed-pixel UI chrome (corner controls,
    # Menu/Pause, per-scene menu buttons) needs its box and its label font
    # to grow together, or a button either overflows its own text or has
    # a bunch of dead padding around it. Kept as its own named key rather
    # than callers reaching for 'font_scale' directly, so chrome can be
    # retuned independently of gameplay-table text later without a
    # find/replace across every call site.
    (1024, 640):  {'card_scale': 0.80, 'oval_rx_pct': 0.34, 'oval_ry_pct': 0.30, 'font_scale': 0.80, 'menu_w': 420,  'button_scale': 0.80},
    (1280, 800):  {'card_scale': 1.00, 'oval_rx_pct': 0.34, 'oval_ry_pct': 0.30, 'font_scale': 1.00, 'menu_w': 460,  'button_scale': 1.00},
    (1440, 900):  {'card_scale': 1.10, 'oval_rx_pct': 0.34, 'oval_ry_pct': 0.30, 'font_scale': 1.08, 'menu_w': 500,  'button_scale': 1.08},
    (1600, 1000): {'card_scale': 1.20, 'oval_rx_pct': 0.34, 'oval_ry_pct': 0.30, 'font_scale': 1.16, 'menu_w': 540,  'button_scale': 1.16},
    (1920, 1080): {'card_scale': 1.50, 'oval_rx_pct': 0.35, 'oval_ry_pct': 0.31, 'font_scale': 1.35, 'menu_w': 620,  'button_scale': 1.35},
    (2560, 1440): {'card_scale': 2.20, 'oval_rx_pct': 0.37, 'oval_ry_pct': 0.33, 'font_scale': 1.70, 'menu_w': 780,  'button_scale': 1.70},
    (3840, 2160): {'card_scale': 3.40, 'oval_rx_pct': 0.39, 'oval_ry_pct': 0.35, 'font_scale': 2.20, 'menu_w': 960,  'button_scale': 2.20},
    (7680, 4320): {'card_scale': 6.50, 'oval_rx_pct': 0.41, 'oval_ry_pct': 0.37, 'font_scale': 3.00, 'menu_w': 1180, 'button_scale': 3.00},
}

def get_ui_scale(sw: int, sh: int) -> dict:
    """Per-resolution scaling profile (card size, seat-oval radius %, font
    scale, settings-menu width, chrome/button scale). Falls back to a linear
    approximation off the 1280x800 baseline for any resolution not in the
    table above — the Settings screen only ever offers the 8 listed there,
    so this is just a defensive fallback, not the normal path."""
    profile = UI_SCALE_PROFILES.get((sw, sh))
    if profile is not None:
        return profile
    s = max(0.8, min(4.0, sw / 1280))
    font_scale = max(0.85, min(2.5, s))
    return {
        'card_scale': s, 'oval_rx_pct': 0.34, 'oval_ry_pct': 0.30,
        'font_scale': font_scale, 'menu_w': max(420, min(900, sw * 0.34)),
        'button_scale': font_scale,
    }

def get_chrome_scale(sw: int, sh: int) -> float:
    """Scale factor for fixed-pixel UI chrome — WindowControls,
    AudioControls, the Menu/Pause buttons, and the per-scene menu
    buttons (Main Menu, Mode Select, Settings, Rules, Chuo, Multiplayer/
    LAN/Internet menus and lobbies) — so a button's box (width/height)
    and its label (via font_scaled(), never a blanket change to font())
    scale together. Single named accessor rather than every call site
    reaching into get_ui_scale()['button_scale'] directly, so this can
    be retuned in one place later without touching every call site."""
    return get_ui_scale(sw, sh)['button_scale']

# ─── Colors ───────────────────────────────────────────────────────────────────
WHITE        = (255, 255, 255)
OFF_WHITE    = (245, 242, 235)
BLACK        = (20,  20,  20)
DARK_GRAY    = (50,  50,  50)
MID_GRAY     = (110, 110, 110)
LIGHT_GRAY   = (190, 190, 190)
VERY_LIGHT   = (230, 228, 220)

TABLE_GREEN  = ( 34,  85,  45)
TABLE_FELT   = ( 27,  69,  37)
TABLE_EDGE   = ( 18,  50,  25)

# ─── Cosmetics: table felt themes (Profile Part 2) ─────────────────────────
# Alternate (felt, edge) color pairs fed into BoardRenderer's EXISTING
# procedural felt-texture generator (_build_felt_texture) — no new art,
# just different colors/gradient endpoints through the same code path.
# 'default' always maps to the classic green above. Unlocked via badges
# only in this pass (see core/profile_store.py's BADGE_DEFS) — no store/
# currency yet.
# 'pattern' key: a subtle geometric overlay drawn on top of the base
# radial-gradient + weave (see BoardRenderer._apply_felt_pattern) —
# "plain" means no overlay, same rendering as the original 5 themes.
FELT_THEMES = {
    "default":     {"felt": TABLE_GREEN,      "edge": TABLE_EDGE,      "bg": TABLE_FELT,      "label": "Classic Green",      "pattern": "plain"},
    "crimson":     {"felt": (110,  35,  35),   "edge": ( 60,  15,  15), "bg": ( 85,  27,  27), "label": "Crimson",            "pattern": "plain"},
    "midnight":    {"felt": ( 28,  35,  70),   "edge": ( 12,  16,  35), "bg": ( 20,  26,  55), "label": "Midnight Blue",       "pattern": "plain"},
    "royal_blue":  {"felt": ( 25,  70, 120),   "edge": ( 12,  35,  60), "bg": ( 18,  55,  95), "label": "Royal Blue",          "pattern": "plain"},
    "amber":       {"felt": (120,  80,  20),   "edge": ( 60,  38,   8), "bg": ( 95,  63,  15), "label": "Amber",               "pattern": "plain"},
    # Badge-unlocked textured themes (Profile Part 5 — numeric/mechanic
    # badge expansion). Colors deliberately distinct from the 5 above.
    "teal_quilt":         {"felt": ( 20,  80,  85), "edge": ( 10,  40,  45), "bg": ( 15,  60,  65), "label": "Diamond Quilt",       "pattern": "diamond_quilt"},
    "plum_herringbone":   {"felt": ( 70,  25,  55), "edge": ( 35,  10,  28), "bg": ( 55,  20,  42), "label": "Plum Herringbone",    "pattern": "herringbone"},
    "graphite_pinstripe": {"felt": ( 45,  45,  50), "edge": ( 20,  20,  24), "bg": ( 35,  35,  40), "label": "Graphite Pinstripe",  "pattern": "pinstripe"},
    "copper_checker":     {"felt": (100,  60,  25), "edge": ( 50,  28,  10), "bg": ( 80,  48,  20), "label": "Copper Checkerboard", "pattern": "checkerboard"},
    "gold_honeycomb":     {"felt": ( 90,  75,  20), "edge": ( 45,  36,   8), "bg": ( 70,  58,  15), "label": "Golden Honeycomb",    "pattern": "honeycomb"},
    "indigo_constellation": {"felt": ( 20,  22,  55), "edge": ( 10,  10,  30), "bg": ( 15,  17,  42), "label": "Constellation Night", "pattern": "constellation"},
}

# ─── Cosmetics: card back designs (Profile Part 2) ─────────────────────────
# Alternate (color A, color B, pattern) triples fed into AssetLoader's
# EXISTING procedural card-back generator — same shapes/borders, just a
# different base palette + line pattern per style key.
CARD_BACK_STYLES = {
    "default":    {"a": (60, 30, 100), "b": (90, 50, 150), "pattern": "diagonal", "label": "Classic Purple"},
    "crosshatch": {"a": (30, 60, 60),  "b": (50, 100, 100), "pattern": "crosshatch", "label": "Teal Crosshatch"},
    "dots":       {"a": (80, 40, 20),  "b": (140, 80, 40), "pattern": "dots",       "label": "Copper Dots"},
    "chevron":    {"a": (20, 55, 25),  "b": (45, 100, 50), "pattern": "chevron",    "label": "Forest Chevron"},
    "starfield":  {"a": (15, 15, 40),  "b": (40, 40, 90),  "pattern": "starfield",  "label": "Starfield"},
    # Badge-unlocked patterns (Profile Part 5). Color pairs cycle through
    # 5 new families (teal, rose, monochrome, sunset, obsidian-gold) not
    # used by the original 5, so every unlock is visually distinct from
    # both the defaults and its neighbors.
    "houndstooth":         {"a": ( 15,  60,  65), "b": ( 40, 130, 140), "pattern": "houndstooth",         "label": "Houndstooth"},
    "hex_lattice":         {"a": ( 70,  20,  55), "b": (150,  45, 100), "pattern": "hex_lattice",         "label": "Hex Lattice"},
    "herringbone_back":    {"a": ( 25,  25,  25), "b": (170, 170, 170), "pattern": "herringbone_back",    "label": "Herringbone"},
    "pinwheel":            {"a": ( 12,  12,  12), "b": (190, 150,  50), "pattern": "pinwheel",            "label": "Pinwheel"},
    "concentric_diamonds": {"a": ( 15,  60,  65), "b": ( 40, 130, 140), "pattern": "concentric_diamonds", "label": "Concentric Diamonds"},
    "basket_weave":        {"a": ( 70,  20,  55), "b": (150,  45, 100), "pattern": "basket_weave",        "label": "Basket Weave"},
    "checkerboard_back":   {"a": (110,  40,  30), "b": (230, 120,  60), "pattern": "checkerboard_back",   "label": "Checkerboard"},
    "honeycomb_back":      {"a": ( 12,  12,  12), "b": (190, 150,  50), "pattern": "honeycomb_back",      "label": "Honeycomb"},
    "sunburst":            {"a": ( 15,  60,  65), "b": ( 40, 130, 140), "pattern": "sunburst",            "label": "Sunburst"},
    "bullseye":            {"a": ( 70,  20,  55), "b": (150,  45, 100), "pattern": "bullseye",            "label": "Bullseye"},
    "zigzag":              {"a": ( 25,  25,  25), "b": (170, 170, 170), "pattern": "zigzag",              "label": "Zigzag"},
}

RED_SUIT     = (200,  30,  30)
BLACK_SUIT   = ( 20,  20,  20)
BLUE_SUIT    = ( 30,  80, 180)   # Spades accent
GREEN_SUIT   = ( 20, 130,  60)   # Flowers accent
ORANGE_SUIT  = (210, 100,  20)   # Dice accent

CARD_BG      = (252, 250, 245)
CARD_BORDER  = (180, 175, 165)
CARD_BACK_A  = ( 60,  30, 100)
CARD_BACK_B  = ( 90,  50, 150)
CARD_SELECTED= (255, 215,   0)   # Gold highlight
CARD_PLAYABLE= ( 80, 200,  80)   # Green glow
CARD_HOVER   = (220, 240, 255)

BTN_NORMAL   = ( 55,  90, 155)
BTN_HOVER    = ( 75, 115, 185)
BTN_PRESSED  = ( 35,  65, 120)
BTN_DISABLED = ( 90,  90,  90)
BTN_TEXT     = WHITE

OVERLAY_BG   = (  0,   0,   0, 180)

UI_PANEL     = ( 25,  60,  35)
UI_PANEL_B   = ( 35,  75,  45)

GOLD         = (200, 160,  20)
GOLD_LIGHT   = (255, 215,   0)

KADI_COLOR   = (220,  50,  50)
WIN_COLOR    = (255, 200,   0)

INFO_BG      = ( 20,  50,  25, 210)

# ─── Design tokens (Phase 1 — visual polish pass) ─────────────────────────────
# A small, explicit set of shared values so every screen/widget pulls from the
# same palette/spacing instead of each picking its own one-off number, as had
# happened ad hoc across scenes.py/widgets.py/board_renderer.py (panel radius
# ranging 6-14, shadow alpha 60-160, overlay dim 140-200, etc). Existing named
# colors above are unchanged and still work; these are the tokens the shared
# widgets (Panel, Button) and any new/updated screen code should reach for.
ACCENT_PRIMARY = BTN_NORMAL     # (55, 90, 155)  blue   - primary interactive accent
ACCENT_GOLD    = GOLD_LIGHT     # (255, 215, 0)  gold   - emphasis/highlight accent
ACCENT_DANGER  = KADI_COLOR     # (220, 50, 50)  red    - alert/danger/KADI accent

RADIUS_PANEL   = 14   # every Panel / modal / overlay card uses this corner radius
RADIUS_BUTTON  = 10   # every Button uses this corner radius
RADIUS_CHIP    = 8    # small inline badges/chips (score tag, suit indicator, etc.)

SHADOW_COLOR   = (0, 0, 0)
SHADOW_ALPHA   = 90     # one consistent drop-shadow opacity
SHADOW_OFFSET  = (0, 4)  # one consistent drop-shadow depth (x, y)

BORDER_LIGHT   = (255, 255, 255, 36)   # subtle hairline border on dark panels/buttons
BORDER_ACCENT  = (*GOLD, 90)           # gold accent border for emphasized panels

PANEL_BG_ALPHA = 225   # standard panel/card background opacity
OVERLAY_ALPHA  = 170   # standard full-screen dim overlay opacity

# ─── Suits ────────────────────────────────────────────────────────────────────
class Suit(Enum):
    SPADES  = "Spades"
    LOVE    = "Love"
    DICE    = "Dice"
    FLOWERS = "Flowers"

SUIT_SYMBOL = {
    Suit.SPADES:  "♠",
    Suit.LOVE:    "♥",
    Suit.DICE:    "♦",
    Suit.FLOWERS: "♣",
}

# Suit -> vector icon kind (rendering.widgets.draw_icon). The card-suit
# Unicode glyphs above (U+2660/2665/2666/2663) aren't included in every
# font — notably not in this project's own bundled Poppins body font — so
# anywhere a suit needs to actually be drawn on screen (card faces, the
# current-suit indicator, the suit picker) uses this vector version
# instead, the same way KICKBACK/JUMP/etc already avoid Unicode glyphs.
SUIT_ICON = {
    Suit.SPADES:  "spade",
    Suit.LOVE:    "heart",
    Suit.DICE:    "diamond",
    Suit.FLOWERS: "club",
}

# ASCII-only suit abbreviation — for the handful of places a card gets
# folded into a plain single-string message (toast banners, etc.) where
# compositing a vector suit icon isn't practical. Guaranteed to render on
# any font, unlike SUIT_SYMBOL's Unicode glyphs.
SUIT_LETTER = {
    Suit.SPADES:  "S",
    Suit.LOVE:    "H",
    Suit.DICE:    "D",
    Suit.FLOWERS: "C",
}

SUIT_COLOR = {
    Suit.SPADES:  BLACK_SUIT,
    Suit.LOVE:    RED_SUIT,
    Suit.DICE:    ORANGE_SUIT,
    Suit.FLOWERS: GREEN_SUIT,
}

SUIT_ACCENT = {
    Suit.SPADES:  (100, 120, 200),
    Suit.LOVE:    (220,  80,  80),
    Suit.DICE:    (210, 130,  30),
    Suit.FLOWERS: ( 40, 160,  80),
}

# ─── Ranks ────────────────────────────────────────────────────────────────────
# Ranks: 2-9, 10, J, Q, K, ACE
# ACE = the suit-change / shield card (displayed as 'A')
# 10  = finishing card (displayed as '10')
RANKS = ['2','3','4','5','6','7','8','9','10','J','Q','K','ACE']

RANK_DISPLAY = {
    '2':'2','3':'3','4':'4','5':'5','6':'6','7':'7',
    '8':'8','9':'9','10':'10','J':'J','Q':'Q','K':'K','ACE':'A',
}

# ─── Card Types ───────────────────────────────────────────────────────────────
class CardType(Enum):
    STANDARD    = auto()
    QUESTION    = auto()   # 8, Q
    KICKBACK    = auto()   # K
    JUMP        = auto()   # J
    SUIT_CHANGE = auto()   # ACE (displayed as A)
    PICKUP_2    = auto()   # 2
    PICKUP_3    = auto()   # 3
    JOKER       = auto()   # Joker
    FINISHING   = auto()   # 4,5,6,7,9,10

def get_card_type(rank: str) -> CardType:
    mapping = {
        '8':   CardType.QUESTION,
        'Q':   CardType.QUESTION,
        'K':   CardType.KICKBACK,
        'J':   CardType.JUMP,
        'ACE': CardType.SUIT_CHANGE,
        '2':   CardType.PICKUP_2,
        '3':   CardType.PICKUP_3,
    }
    finishing = {'4','5','6','7','9','10'}
    if rank == 'JOKER':
        return CardType.JOKER
    if rank in mapping:
        return mapping[rank]
    if rank in finishing:
        return CardType.FINISHING
    return CardType.STANDARD

PICKUP_VALUES = {
    CardType.PICKUP_2: 2,
    CardType.PICKUP_3: 3,
    CardType.JOKER:    5,
}

# ─── Game States ──────────────────────────────────────────────────────────────
class GameState(Enum):
    MAIN_MENU      = auto()
    MODE_SELECT    = auto()
    LOBBY          = auto()
    SETTINGS       = auto()
    PLAYING        = auto()
    SUIT_PICK      = auto()
    KADI_DECLARED  = auto()
    KADI_WINDOW    = auto()
    POST_PLAY      = auto()   # brief timed delay after human play for KADI check
    JUMP_COUNTER_WINDOW = auto()   # window to counter a pending J (Jump) play with another J
    PAUSED         = auto()
    GAME_OVER      = auto()

class PlayDirection(Enum):
    CLOCKWISE        = 1
    COUNTER_CLOCKWISE = -1

# ─── Number of players ────────────────────────────────────────────────────────
MIN_PLAYERS = 2
MAX_PLAYERS = 6
STARTING_HAND = 4

# ─── Counter finish window ────────────────────────────────────────────────────
COUNTER_WINDOW_SECS = 3.0

# ─── AI Difficulty ────────────────────────────────────────────────────────────
class AIDifficulty(Enum):
    EASY   = auto()
    MEDIUM = auto()
    HARD   = auto()

# ─── AI Difficulty Profiles ────────────────────────────────────────────────────
# Tunable knobs that drive AI *playstyle* only — never the cards it is
# dealt or draws. Higher difficulty AI sees exactly the same hands a
# human would; it just reads the board better and plays more
# purposefully, both offensively and defensively.
#
# Every difficulty runs the SAME exhaustive search over every legal play
# reachable from the current hand this turn (AIPlayer._enumerate_legal_plays)
# and scores every option with the SAME function (_evaluate_play) — there
# is no separate "smarter" search for higher difficulties. The dials below
# only shape that one shared pipeline.
#
#   optimal_play_chance  — the core difficulty dial: probability this
#                          player actually takes the top-scoring option
#                          its search found, versus a random legal
#                          alternative. HARD sits close to 1.0 (plays
#                          objectively best almost every time, with just
#                          enough randomness to avoid being a perfectly
#                          deterministic, memorizable bot). Lower values
#                          (EASY, MEDIUM) make it visibly fallible,
#                          including occasionally the self-defeating
#                          mistakes (going cardless without KADI, missing
#                          an open KADI) a genuine beginner would make.
#   block_awareness      — probability the AI, when picking a new suit
#                          (ACE/shield), will deliberately steer AWAY
#                          from the suit a threatening opponent (KADI
#                          declared, or very low on cards) looks likely
#                          to need, based on that opponent's own public
#                          play history — instead of just picking
#                          whatever suit the AI itself holds most of.
#   threat_hand_count    — an opponent at or below this many cards is
#                          treated as "close to winning" for blocking
#                          and disruption purposes.
#   disrupt_bonus        — extra score weight given to plays that force a
#                          pickup, skip, or reverse onto the next player
#                          when they're a threat (see threat_hand_count),
#                          i.e. deliberately making their turn harder
#                          rather than just playing the "best" option in
#                          isolation.
#   counter_aggression   — probability of countering a pending Jump (J)
#                          with a J of its own, when one is held.
#   cluster_preservation — when a play would spend only part of a
#                          same-rank finishing cluster (e.g. one 9 out of
#                          three), how strongly to penalize that instead
#                          of a play that clears the cluster whole or
#                          leaves it fully intact — so a cluster stays
#                          available later as one big KADI-finishing set
#                          instead of getting picked apart across several
#                          turns. 0 = no preference.
#   hoard_pickup          — "Kuficha Joker" (Swahili: "hide the Joker").
#                          Heads-up (exactly 1 opponent) only: chance,
#                          on a given turn, of holding back a pickup
#                          card/Joker instead of spending it immediately,
#                          saving it for a two-card endgame trap — play
#                          the pickup card and declare KADI in the same
#                          move once the hand is down to just [pickup,
#                          finishing], hoping the opponent can't counter
#                          and is forced to draw while the AI walks in
#                          with its last card next turn. A real strategy
#                          human players use. 0 = never hoards (always
#                          spends a pickup card the moment it's best).
#   bluff_suit_request    — "bluff calling" on a lone-ACE KADI declare.
#                          When playing a lone ACE leaves exactly one
#                          finishing card behind (a KADI declare), the
#                          honest move is requesting that card's own
#                          suit — but that telegraphs exactly what's
#                          needed, and everyone else at the table will
#                          reasonably try to steer the suit AWAY from it
#                          on their own turns. This is the chance of
#                          instead requesting a decoy suit, gambling that
#                          opponents trying to block the "obvious" suit
#                          end up switching to the real one by mistake.
#                          Genuinely risky — the AI can talk itself out of
#                          its own win if nobody takes the bait — so it's
#                          not an every-time move even at HARD.
#                          0 = always honest.
DIFFICULTY_PROFILES = {
    AIDifficulty.EASY: {
        'block_awareness':    0.0,
        'threat_hand_count':  2,
        'disrupt_bonus':      0,
        'counter_aggression': 0.3,
        'cluster_preservation': 0,
        'hoard_pickup':       0.0,
        'bluff_suit_request': 0.0,
        # Every difficulty runs the SAME exhaustive search over every
        # legal play this turn (AIPlayer._enumerate_legal_plays) and the
        # SAME scorer (_evaluate_play) — this is the one dial that makes
        # EASY, MEDIUM, and HARD actually play differently: the chance
        # this difficulty takes the top-scoring option it found versus a
        # random legal one. Low here means EASY visibly makes real
        # mistakes, including occasionally the self-defeating ones (going
        # cardless without KADI, missing an open KADI) a genuine beginner
        # would make — not a separate, deliberately-dumbed-down search.
        'optimal_play_chance': 0.05,
    },
    AIDifficulty.MEDIUM: {
        'block_awareness':    0.35,
        'threat_hand_count':  2,
        'disrupt_bonus':      5,
        'counter_aggression': 0.6,
        'cluster_preservation': 2,
        'hoard_pickup':       0.3,
        'bluff_suit_request': 0.2,
        'optimal_play_chance': 0.5,
    },
    AIDifficulty.HARD: {
        'block_awareness':    0.85,
        'threat_hand_count':  3,
        'disrupt_bonus':      9,
        'counter_aggression': 1.0,
        'cluster_preservation': 4,
        'hoard_pickup':       0.7,
        'bluff_suit_request': 0.4,
        # Not a hard 1.0 — HARD still overwhelmingly takes the
        # objectively best move it finds, but a small sliver of
        # randomness keeps it from being perfectly, robotically
        # deterministic (same hand + same board always producing the
        # exact same play), and stops it from being fully solvable by a
        # human just memorizing "HARD always does X here".
        'optimal_play_chance': 0.97,
    },
}
