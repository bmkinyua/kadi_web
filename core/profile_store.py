"""
KADI - Player profile persistence.

Saves/loads PERSISTENT PLAYER PROGRESS (stats, cosmetics, undo tokens,
badges, the ads_removed purchase flag) to its own JSON file
(profile.json) in KADI's per-user application data directory — same
directory game_logger/settings_store already use, via
core.game_logger.base_dir().

Deliberately NOT settings_store: progress and preferences have
different reset semantics. A "Reset to Defaults" in Settings must never
wipe someone's badges/stats, so this is a genuinely separate file with
its own load/save/reset, following settings_store.py's DEFAULTS-dict
pattern but for a nested progress structure rather than a flat
attribute list.
"""
from __future__ import annotations
import copy
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.game_logger import base_dir, game_log

PROFILE_FILENAME = "profile.json"

# Undo-token economy (see Part 3 of the profile spec) — kept here as the
# single source of truth so game_manager.py and the UI never disagree
# about the starting balance or the refill cap.
UNDO_TOKENS_DEFAULT = 3
UNDO_TOKENS_MAX = 5

# ── Bonus-on-return (undo tokens) ───────────────────────────────────
# Deliberately NOT a regen timer that blocks play — see the Part B
# discussion on undo-token timers: gating a mid-match error-recovery
# tool behind a countdown risks turning a misclick into a wall the
# player hits while already invested in a game, which is a much
# harsher trigger than the classic "energy system" pattern it's
# borrowed from (those gate STARTING a session, not something spent
# mid-session). It's also worse for LAN/Internet specifically, since
# only the host has a token balance at all — a shared timer would make
# the host visibly wait in front of the very players they're hosting.
#
# Instead: every BONUS_INTERVAL_HOURS a profile has been away, its
# NEXT new game starts with one extra token on top of the guaranteed
# UNDO_TOKENS_DEFAULT reset, capped at UNDO_TOKENS_MAX. This only ever
# ADDS — nobody is ever blocked from starting a game or short of the
# normal 3, it just rewards coming back after a while away. See
# compute_game_start_undo_tokens() / mark_played_now() below, and
# GameManager.new_game()'s call site.
BONUS_INTERVAL_HOURS = 4.0
BONUS_MAX = UNDO_TOKENS_MAX - UNDO_TOKENS_DEFAULT  # currently 2 (3 -> 5 ceiling)

# Single-player difficulty buckets + multiplayer mode buckets tracked
# separately, per spec Part 1.
DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
MODES = ("lan", "internet", "hot_seat")


def _mode_bucket_defaults() -> Dict[str, Any]:
    return {
        "single_player": {d: 0 for d in DIFFICULTIES},
        "single_player_elimination": {d: 0 for d in DIFFICULTIES},
        "lan": 0,
        "internet": 0,
        "hot_seat": 0,
    }


def default_profile() -> Dict[str, Any]:
    """A fresh DEFAULTS structure (deep-copied each call so callers can't
    accidentally mutate the shared template)."""
    return {
        "games_played": _mode_bucket_defaults(),
        "games_won": _mode_bucket_defaults(),
        # Real distinct finishing mechanics in the rule engine — see
        # core.game_manager.classify_finish_kind().
        "multi_card_finishes": {
            "question_chain": 0,
            "kickback_run": 0,
            "jump_bundle": 0,
            "ace_finisher": 0,
        },
        "msomi": {
            "models_trained": 0,
            "games_played_with_msomi": 0,
            "games_won_with_msomi": 0,
        },
        "total_time_played_secs": 0.0,
        # Lifetime numeric counters feeding the tiered "Meta" badge
        # ladders (see BADGE_DEFS / check_badges_after_game) — each is a
        # running total across every game, updated once per finished
        # game from that game's own tallies (see GameManager's
        # self._g_* attributes, reset each new_game() and folded in here
        # via finalize_profile_stats -> check_badges_after_game).
        "counters": {
            "cards_played": 0,
            "cards_drawn": 0,
            "biggest_pickup_absorbed": 0,       # high-water mark, not cumulative
            "kadi_declarations": 0,
            "aces_played": 0,
            "jump_skips_dealt": 0,
            "kickback_reversals": 0,
            "ace_shield_uses": 0,
            "ace_shield_biggest": 0,             # high-water mark, not cumulative
            "undo_tokens_used_total": 0,
            "flawless_game_count": 0,            # games won with 0 cards drawn
            "undo_free_game_count": 0,           # completed games with no undo used
            "win_streak_current": 0,
            "win_streak_best": 0,
        },
        "cosmetics": {
            "owned_card_backs": ["default"],
            "owned_felt_themes": ["default"],
            "equipped_card_back": "default",
            "equipped_felt_theme": "default",
        },
        # Undo tokens (Part 3). Reset to UNDO_TOKENS_DEFAULT (or a bit
        # higher — see compute_game_start_undo_tokens) at the start of
        # each new game — see game_manager.GameManager.new_game().
        "undo_tokens": UNDO_TOKENS_DEFAULT,
        # ISO-8601 timestamp of the last time this profile started a
        # new game, or None for a brand-new profile that's never played
        # yet. Powers the bonus-on-return calculation above — see
        # compute_game_start_undo_tokens()/mark_played_now(). Not used
        # for anything else (not a "last seen" telemetry field).
        "last_played_at": None,
        # badge_id -> ISO-8601 timestamp string of when it was earned.
        "badges": {},
        # PURCHASE flag — distinct from the ads_enabled dev/testing
        # SETTING in settings.json. See scenes._ads_showing().
        "ads_removed": False,
    }


DEFAULTS: Dict[str, Any] = default_profile()


def compute_game_start_undo_tokens(profile: Dict[str, Any]) -> int:
    """How many undo tokens a NEW game should start with, given how
    long it's been since this profile last started one (see
    last_played_at / mark_played_now). Always UNDO_TOKENS_DEFAULT or
    higher, never above UNDO_TOKENS_MAX — this is a bonus layered on
    top of the guaranteed per-game reset, not a replacement for it, so
    a player is never worse off than the flat default regardless of
    how recently they last played."""
    last = profile.get("last_played_at")
    if not last:
        return UNDO_TOKENS_DEFAULT
    try:
        last_dt = datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return UNDO_TOKENS_DEFAULT
    hours_away = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
    bonus = min(BONUS_MAX, int(hours_away // BONUS_INTERVAL_HOURS))
    return min(UNDO_TOKENS_MAX, UNDO_TOKENS_DEFAULT + max(0, bonus))


def mark_played_now(profile: Dict[str, Any]) -> None:
    """Stamp 'right now' as this profile's last-played time. Call this
    at the START of a new game, AFTER computing that game's starting
    balance via compute_game_start_undo_tokens() (not before — marking
    first would make the elapsed time always read as ~0 and the bonus
    would never accrue). Deliberately stamped at game START, not game
    END, so the bonus clock measures real time away BETWEEN sessions
    rather than how long the last session happened to last."""
    profile["last_played_at"] = datetime.now(timezone.utc).isoformat()


def _profile_path() -> str:
    return os.path.join(base_dir(), PROFILE_FILENAME)


def _deep_merge_defaults(defaults: Any, loaded: Any) -> Any:
    """Recursively fills in any keys missing from `loaded` with values
    from `defaults`, so adding a new stat/field in a later version
    doesn't require a migration step or clobber existing progress —
    old profile.json files just pick up the new defaulted fields."""
    if isinstance(defaults, dict):
        if not isinstance(loaded, dict):
            return copy.deepcopy(defaults)
        merged = {}
        for key, dval in defaults.items():
            merged[key] = _deep_merge_defaults(dval, loaded.get(key, dval))
        return merged
    return loaded


def load_profile() -> Dict[str, Any]:
    """Load profile.json, or a fresh default profile if it doesn't exist
    yet / is unreadable. Always returns a complete, schema-filled dict —
    callers never need to getattr/.get() with a fallback."""
    path = _profile_path()
    if not os.path.isfile(path):
        return default_profile()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return _deep_merge_defaults(default_profile(), data)
    except Exception as e:
        game_log.info(f"Failed to load profile ({e}) — using defaults")
        return default_profile()


def save_profile(profile: Dict[str, Any]) -> bool:
    """Write the given profile dict to disk. Returns True on success."""
    try:
        path = _profile_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2)
        return True
    except Exception as e:
        game_log.info(f"Failed to save profile: {e}")
        return False


def record_basic_network_result(profile: Dict[str, Any], mode: str, won: bool) -> None:
    """Records a bare win/loss count for a LAN or Internet Multiplayer
    game played as a network CLIENT (i.e. self.gm was a
    network.client_state.ClientGameManager, not the real GameManager —
    see scenes.py's _record_profile_stats for the caller and the full
    story of why this exists as a separate, much simpler path).

    KNOWN LIMITATION, not an oversight: this deliberately does NOT run
    profile_store.check_badges_after_game or touch multi_card_finishes/
    msomi stats, unlike GameManager.finalize_profile_stats. Those need
    granular per-move telemetry (cards played/drawn, pickup chains
    absorbed, jump counter depth, etc.) that only accumulates on
    whichever machine is actually running the authoritative rule
    engine — the LAN host or the Internet server — and none of that is
    currently mirrored back down to client players. A client's own
    profile.json can still honestly say how many LAN/Internet games
    they've played and won; it just can't award badges that depend on
    in-match details it was never given. Properly fixing that would
    mean the host/server syncing that telemetry back to each client at
    game-end — real future work, not something to fake with zeros
    here (which would either wrongly block badges the player actually
    earned, or wrongly grant ones they didn't)."""
    if mode not in ('lan', 'internet'):
        return
    profile['games_played'][mode] += 1
    if won:
        profile['games_won'][mode] += 1
    save_profile(profile)


def reset_progress(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Wipe stats/badges/cosmetics/tokens back to a fresh profile and
    save immediately. NOT wired to Settings' 'Reset to Defaults' — this
    is deliberately its own, separately-invoked action (there is no UI
    entry point for it in this pass; provided for completeness/testing
    parity with settings_store.reset_to_defaults())."""
    fresh = default_profile()
    profile.clear()
    profile.update(fresh)
    save_profile(profile)
    return profile


# ─── Badges ─────────────────────────────────────────────────────────────────
# Each badge: id -> (display name, description, category, unlocked cosmetic
# id-or-None). Cosmetic ids reference CARD_BACK_STYLES / FELT_THEMES keys
# in rendering/asset_loader.py and constants.py respectively.
BADGE_DEFS: Dict[str, Dict[str, Any]] = {
    # Single-player skill
    "beat_hard": {
        "name": "Hard-Mode Champion",
        "desc": "Beat the AI on HARD difficulty.",
        "category": "Single-Player Skill",
        "cosmetic": ("felt_theme", "crimson"),
    },
    "finish_question_chain": {
        "name": "Interrogator",
        "desc": "Win with a Question-chain finish.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "crosshatch"),
    },
    "finish_kickback_run": {
        "name": "Boomerang",
        "desc": "Win with an even-Kickback-run finish.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "dots"),
    },
    "finish_jump_bundle": {
        "name": "Leapfrog",
        "desc": "Win with a Jump-bundle finish.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "chevron"),
    },
    "finish_ace_finisher": {
        "name": "Ace Up the Sleeve",
        "desc": "Win with an ACE-finisher.",
        "category": "Single-Player Skill",
        "cosmetic": ("felt_theme", "royal_blue"),
    },
    # Multiplayer
    "first_lan_win": {
        "name": "LAN Party Champ",
        "desc": "Win your first LAN multiplayer match.",
        "category": "Multiplayer",
        "cosmetic": ("felt_theme", "midnight"),
    },
    "first_internet_win": {
        "name": "Global Contender",
        "desc": "Win your first Internet multiplayer match.",
        "category": "Multiplayer",
        "cosmetic": ("card_back", "starfield"),
    },
    "first_hotseat_win": {
        "name": "Couch Champion",
        "desc": "Win your first hot-seat match.",
        "category": "Multiplayer",
        "cosmetic": None,
    },
    # MSOMI/Chuo
    "first_model_trained": {
        "name": "Chuo Apprentice",
        "desc": "Train your first model in Chuo.",
        "category": "MSOMI / Chuo",
        "cosmetic": None,
    },
    "beat_msomi": {
        "name": "Machine Slayer",
        "desc": "Win a game with a MSOMI model attached to an opponent.",
        "category": "MSOMI / Chuo",
        "cosmetic": ("felt_theme", "amber"),
    },
    # Meta / engagement
    "games_played_10": {
        "name": "Getting the Hang of It",
        "desc": "Play 10 games.",
        "category": "Meta",
        "cosmetic": None,
    },
    "games_played_50": {
        "name": "Regular",
        "desc": "Play 50 games.",
        "category": "Meta",
        "cosmetic": None,
    },
    "games_played_100": {
        "name": "Century Club",
        "desc": "Play 100 games.",
        "category": "Meta",
        "cosmetic": ("felt_theme", "royal_blue"),
    },
    "all_difficulties": {
        "name": "Well Rounded",
        "desc": "Play on all three difficulties at least once.",
        "category": "Meta",
        "cosmetic": None,
    },

    # ─── Profile Part 5: mechanic + numeric expansion ──────────────────
    # Single-player skill — mechanics not covered by the original 5
    "chain_breaker_10": {
        "name": "Chain Breaker",
        "desc": "Absorb a pickup chain of 10+ cards in one turn and still win the round.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "hex_lattice"),
    },
    "clean_sweep": {
        "name": "Clean Sweep",
        "desc": "Win a game without ever drawing a card.",
        "category": "Single-Player Skill",
        "cosmetic": ("felt_theme", "teal_quilt"),
    },
    "kuficha_joker": {
        "name": "The Trap",
        "desc": "Hoard a pickup card, then play it and declare KADI in the same move.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "houndstooth"),
    },
    "poker_face": {
        "name": "Poker Face",
        "desc": "Win off a decoy suit-request bluff on a lone-ACE KADI declare.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "pinwheel"),
    },
    "jump_master": {
        "name": "Jump Master",
        "desc": "Win a round after countering a Jump with a Jump three or more times deep.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "zigzag"),
    },
    "nine_lives": {
        "name": "Nine Lives",
        "desc": "Win a game after dropping to exactly 1 card three or more separate times.",
        "category": "Single-Player Skill",
        "cosmetic": ("felt_theme", "plum_herringbone"),
    },
    "ace_shield_big": {
        "name": "Shield Wall",
        "desc": "Block a pickup chain of 5+ with an ACE shield.",
        "category": "Single-Player Skill",
        "cosmetic": ("card_back", "bullseye"),
    },
    "ace_shield_50": {
        "name": "Guardian",
        "desc": "Block a pickup chain with an ACE shield 50 times.",
        "category": "Single-Player Skill",
        "cosmetic": ("felt_theme", "copper_checker"),
    },
    # Elimination Mode
    "last_one_standing": {
        "name": "Last One Standing",
        "desc": "Win an Elimination Mode match.",
        "category": "Elimination Mode",
        "cosmetic": ("card_back", "basket_weave"),
    },
    "iron_will": {
        "name": "Iron Will",
        "desc": "Win an Elimination Mode match on HARD.",
        "category": "Elimination Mode",
        "cosmetic": ("felt_theme", "gold_honeycomb"),
    },
    # Multiplayer additions
    "grand_slam": {
        "name": "Grand Slam",
        "desc": "Win at least one LAN, one Internet, and one hot-seat match.",
        "category": "Multiplayer",
        "cosmetic": ("card_back", "honeycomb_back"),
    },
    "streak_5": {
        "name": "On a Roll",
        "desc": "Win 5 games in a row.",
        "category": "Multiplayer",
        "cosmetic": ("card_back", "sunburst"),
    },
    "streak_10": {
        "name": "Unstoppable",
        "desc": "Win 10 games in a row.",
        "category": "Multiplayer",
        "cosmetic": None,
    },
    "streak_20": {
        "name": "Untouchable",
        "desc": "Win 20 games in a row.",
        "category": "Multiplayer",
        "cosmetic": ("felt_theme", "indigo_constellation"),
    },
    # MSOMI / Chuo additions
    "msomi_whisperer": {
        "name": "MSOMI Whisperer",
        "desc": "Beat a MSOMI-attached opponent 10 times.",
        "category": "MSOMI / Chuo",
        "cosmetic": None,
    },
    "iterator": {
        "name": "Iterator",
        "desc": "Train 5 separate models in Chuo.",
        "category": "MSOMI / Chuo",
        "cosmetic": None,
    },
    # Meta — numeric ladders
    "cards_played_250":  {"name": "Dealt In",             "desc": "Play 250 cards, lifetime.",   "category": "Meta", "cosmetic": None},
    "cards_played_1000": {"name": "Card Shark",            "desc": "Play 1,000 cards, lifetime.", "category": "Meta", "cosmetic": None},
    "cards_played_5000": {"name": "Table Regular",         "desc": "Play 5,000 cards, lifetime.", "category": "Meta", "cosmetic": ("card_back", "concentric_diamonds")},
    "cards_played_15000":{"name": "Kadi Institution",      "desc": "Play 15,000 cards, lifetime.","category": "Meta", "cosmetic": None},

    "cards_drawn_100":  {"name": "Deck Diver",             "desc": "Draw 100 cards, lifetime.",   "category": "Meta", "cosmetic": None},
    "cards_drawn_500":  {"name": "Glutton for Punishment", "desc": "Draw 500 cards, lifetime.",   "category": "Meta", "cosmetic": None},
    "cards_drawn_2000": {"name": "Bottomless Hand",        "desc": "Draw 2,000 cards, lifetime.", "category": "Meta", "cosmetic": None},

    "pickup_hit_7":  {"name": "Took the Hit",   "desc": "Absorb a pickup of 7+ cards in one turn.",  "category": "Meta", "cosmetic": None},
    "pickup_hit_12": {"name": "Absorbed",       "desc": "Absorb a pickup of 12+ cards in one turn.", "category": "Meta", "cosmetic": None},
    "pickup_hit_18": {"name": "Human Shield",   "desc": "Absorb a pickup of 18+ cards in one turn.", "category": "Meta", "cosmetic": None},

    "kadi_10":  {"name": "Calling It",           "desc": "Declare KADI 10 times, lifetime.",  "category": "Meta", "cosmetic": None},
    "kadi_50":  {"name": "Confident",            "desc": "Declare KADI 50 times, lifetime.",  "category": "Meta", "cosmetic": None},
    "kadi_200": {"name": "Kadi! Kadi! Kadi!",    "desc": "Declare KADI 200 times, lifetime.", "category": "Meta", "cosmetic": None},

    "aces_25":  {"name": "Shapeshifter",     "desc": "Play 25 ACEs, lifetime.",  "category": "Meta", "cosmetic": None},
    "aces_100": {"name": "Suit Yourself",    "desc": "Play 100 ACEs, lifetime.", "category": "Meta", "cosmetic": None},
    "aces_400": {"name": "Master of Suits",  "desc": "Play 400 ACEs, lifetime.", "category": "Meta", "cosmetic": None},

    "jump_skips_20":  {"name": "Skip Happens", "desc": "Play 20 Jump cards, lifetime.",  "category": "Meta", "cosmetic": None},
    "jump_skips_100": {"name": "Turn Thief",   "desc": "Play 100 Jump cards, lifetime.", "category": "Meta", "cosmetic": None},

    "kickback_20":  {"name": "Reversal of Fortune", "desc": "Play 20 Kickback cards, lifetime.",  "category": "Meta", "cosmetic": None},
    "kickback_100": {"name": "Spin Doctor",         "desc": "Play 100 Kickback cards, lifetime.", "category": "Meta", "cosmetic": None},

    "games_played_250":  {"name": "Card Table Fixture", "desc": "Play 250 games.",   "category": "Meta", "cosmetic": None},
    "games_played_500":  {"name": "Kadi Veteran",        "desc": "Play 500 games.",   "category": "Meta", "cosmetic": None},
    "games_played_1000": {"name": "Kadi Lifer",          "desc": "Play 1,000 games.", "category": "Meta", "cosmetic": None},

    "finish_question_chain_5":   {"name": "Interrogator II",           "desc": "Win with a Question-chain finish 5 times.",   "category": "Meta", "cosmetic": None},
    "finish_question_chain_25":  {"name": "Interrogator III",          "desc": "Win with a Question-chain finish 25 times.",  "category": "Meta", "cosmetic": None},
    "finish_question_chain_100": {"name": "Grand Inquisitor",          "desc": "Win with a Question-chain finish 100 times.", "category": "Meta", "cosmetic": None},
    "finish_kickback_run_5":     {"name": "Boomerang II",              "desc": "Win with a Kickback-run finish 5 times.",     "category": "Meta", "cosmetic": None},
    "finish_kickback_run_25":    {"name": "Boomerang III",             "desc": "Win with a Kickback-run finish 25 times.",    "category": "Meta", "cosmetic": None},
    "finish_kickback_run_100":   {"name": "Perpetual Motion",          "desc": "Win with a Kickback-run finish 100 times.",   "category": "Meta", "cosmetic": None},
    "finish_jump_bundle_5":      {"name": "Leapfrog II",               "desc": "Win with a Jump-bundle finish 5 times.",      "category": "Meta", "cosmetic": None},
    "finish_jump_bundle_25":     {"name": "Leapfrog III",              "desc": "Win with a Jump-bundle finish 25 times.",     "category": "Meta", "cosmetic": None},
    "finish_jump_bundle_100":    {"name": "Long Jump Legend",          "desc": "Win with a Jump-bundle finish 100 times.",    "category": "Meta", "cosmetic": None},
    "finish_ace_finisher_5":     {"name": "Ace Up the Sleeve II",      "desc": "Win with an ACE-finisher 5 times.",           "category": "Meta", "cosmetic": None},
    "finish_ace_finisher_25":    {"name": "Ace Up the Sleeve III",     "desc": "Win with an ACE-finisher 25 times.",          "category": "Meta", "cosmetic": None},
    "finish_ace_finisher_100":   {"name": "Card Counter's Nightmare",  "desc": "Win with an ACE-finisher 100 times.",         "category": "Meta", "cosmetic": None},

    "undo_used_10": {"name": "Do-Over", "desc": "Use an undo token 10 times, lifetime.", "category": "Meta", "cosmetic": None},
    "undo_used_50": {"name": "Ctrl+Z",  "desc": "Use an undo token 50 times, lifetime.", "category": "Meta", "cosmetic": None},
    "second_wind":  {"name": "Second Wind", "desc": "Win a game after using an undo token.", "category": "Meta", "cosmetic": ("card_back", "herringbone_back")},
    "purist_20":    {"name": "Purist", "desc": "Complete 20 games without using an undo token.", "category": "Meta", "cosmetic": ("card_back", "checkerboard_back")},

    "flawless_10": {"name": "Immaculate",    "desc": "Win 10 games without ever drawing a card.", "category": "Meta", "cosmetic": ("felt_theme", "graphite_pinstripe")},
    "flawless_50": {"name": "Perfectionist", "desc": "Win 50 games without ever drawing a card.", "category": "Meta", "cosmetic": None},

    "time_1h":   {"name": "Warming the Seat", "desc": "1 hour total time played.",   "category": "Meta", "cosmetic": None},
    "time_25h":  {"name": "Dedicated",        "desc": "25 hours total time played.", "category": "Meta", "cosmetic": None},
    "time_100h": {"name": "Kadi Addict",      "desc": "100 hours total time played.","category": "Meta", "cosmetic": None},
}


def _apply_cosmetic_unlock(profile: Dict[str, Any], badge_id: str):
    unlock = BADGE_DEFS.get(badge_id, {}).get("cosmetic")
    if not unlock:
        return
    kind, style_id = unlock
    key = "owned_card_backs" if kind == "card_back" else "owned_felt_themes"
    owned = profile["cosmetics"][key]
    if style_id not in owned:
        owned.append(style_id)


def award_badge(profile: Dict[str, Any], badge_id: str) -> bool:
    """Award a badge if not already earned. Returns True if this was a
    NEWLY earned badge (so the caller knows whether to show a
    notification), False if already owned or unknown."""
    if badge_id not in BADGE_DEFS or badge_id in profile["badges"]:
        return False
    profile["badges"][badge_id] = datetime.now(timezone.utc).isoformat()
    _apply_cosmetic_unlock(profile, badge_id)
    return True


def cosmetic_unlock_hint(kind: str, style_id: str) -> Optional[str]:
    """Human-readable description of how to unlock a locked cosmetic —
    the description of whichever badge grants it (see BADGE_DEFS'
    'cosmetic' field) — or None if no badge grants this cosmetic id
    (shouldn't normally happen for a real, locked style). `kind` is
    'card_back' or 'felt_theme'; `style_id` is the CARD_BACK_STYLES /
    FELT_THEMES key. Used by the Profile screen's locked-cosmetic
    tooltip so the requirement text lives in one place, next to the
    badge definitions it comes from, rather than being duplicated in
    scenes.py."""
    for info in BADGE_DEFS.values():
        cosmetic = info.get("cosmetic")
        if cosmetic and cosmetic[0] == kind and cosmetic[1] == style_id:
            return info["desc"]
    return None


def total_games_played(profile: Dict[str, Any]) -> int:
    gp = profile["games_played"]
    total = gp["lan"] + gp["internet"] + gp["hot_seat"]
    total += sum(gp["single_player"].values())
    total += sum(gp["single_player_elimination"].values())
    return total


def difficulties_played(profile: Dict[str, Any]) -> set:
    gp = profile["games_played"]
    played = set()
    for d in DIFFICULTIES:
        if gp["single_player"].get(d, 0) > 0 or gp["single_player_elimination"].get(d, 0) > 0:
            played.add(d)
    return played


# (threshold, badge_id) ladders for check_badges_after_game's tier
# sweep — kept as data next to BADGE_DEFS so the numbers here and the
# "desc" text there can't quietly drift apart.
_FINISH_TIERS = {
    "question_chain": (5, "finish_question_chain_5", 25, "finish_question_chain_25", 100, "finish_question_chain_100"),
    "kickback_run":   (5, "finish_kickback_run_5",   25, "finish_kickback_run_25",   100, "finish_kickback_run_100"),
    "jump_bundle":    (5, "finish_jump_bundle_5",    25, "finish_jump_bundle_25",    100, "finish_jump_bundle_100"),
    "ace_finisher":   (5, "finish_ace_finisher_5",   25, "finish_ace_finisher_25",   100, "finish_ace_finisher_100"),
}


def check_badges_after_game(profile: Dict[str, Any], *, won: bool,
                             mode: str, difficulty: Optional[str],
                             finish_kind: Optional[str],
                             opponent_had_msomi: bool,
                             cards_played: int = 0,
                             cards_drawn: int = 0,
                             biggest_pickup_absorbed: int = 0,
                             kadi_declarations: int = 0,
                             aces_played: int = 0,
                             jump_skips_dealt: int = 0,
                             kickback_reversals: int = 0,
                             ace_shield_uses: int = 0,
                             ace_shield_biggest: int = 0,
                             jump_counter_depth: int = 0,
                             near_kadi_count: int = 0,
                             undo_used_this_game: bool = False,
                             bluff_suit_win: bool = False,
                             kuficha_trap_win: bool = False,
                             elimination_mode: bool = False) -> List[str]:
    """Called once per finished game (see game_manager.finalize_profile_stats).
    Returns the list of badge ids newly earned this call, in a sensible
    display order. Assumes games_played/games_won/multi_card_finishes/msomi
    counters have ALREADY been incremented for this game before this
    runs, since several checks (games-played milestones, all-difficulties)
    read the just-updated totals.

    Everything from `cards_played` on is THIS one game's own tally (see
    GameManager's self._g_* attributes, reset each new_game()) — this
    function folds each into profile['counters'] as a running lifetime
    total (or a high-water-mark max, for the two 'biggest' values) before
    checking any threshold, so the ladders below always compare against
    up-to-date lifetime numbers."""
    newly: List[str] = []

    def award(bid):
        if award_badge(profile, bid):
            newly.append(bid)

    def tier(value, ladder):
        # ladder: alternating (threshold, badge_id) pairs, e.g. (10, "x_10", 50, "x_50")
        for i in range(0, len(ladder), 2):
            if value >= ladder[i]:
                award(ladder[i + 1])

    if won:
        if mode == "single_player" and difficulty == "HARD":
            award("beat_hard")
        if mode in ("single_player", "single_player_elimination") and finish_kind:
            award({
                "question_chain": "finish_question_chain",
                "kickback_run":   "finish_kickback_run",
                "jump_bundle":    "finish_jump_bundle",
                "ace_finisher":   "finish_ace_finisher",
            }[finish_kind])
        if mode == "lan":
            award("first_lan_win")
        if mode == "internet":
            award("first_internet_win")
        if mode == "hot_seat":
            award("first_hotseat_win")
        if opponent_had_msomi:
            award("beat_msomi")
        if elimination_mode:
            award("last_one_standing")
            if difficulty == "HARD":
                award("iron_will")
        if bluff_suit_win:
            award("poker_face")
        if kuficha_trap_win:
            award("kuficha_joker")
        if jump_counter_depth >= 3:
            award("jump_master")
        if near_kadi_count >= 3:
            award("nine_lives")
        if cards_drawn == 0:
            award("clean_sweep")
        if undo_used_this_game:
            award("second_wind")
        gw = profile["games_won"]
        if gw["lan"] >= 1 and gw["internet"] >= 1 and gw["hot_seat"] >= 1:
            award("grand_slam")

    if biggest_pickup_absorbed >= 10 and won:
        award("chain_breaker_10")
    if ace_shield_biggest >= 5:
        award("ace_shield_big")

    total = total_games_played(profile)
    tier(total, (10, "games_played_10", 50, "games_played_50", 100, "games_played_100",
                 250, "games_played_250", 500, "games_played_500", 1000, "games_played_1000"))
    if len(difficulties_played(profile)) >= 3:
        award("all_difficulties")

    # Fold this game's tallies into lifetime counters.
    c = profile["counters"]
    c["cards_played"] += cards_played
    c["cards_drawn"] += cards_drawn
    c["biggest_pickup_absorbed"] = max(c["biggest_pickup_absorbed"], biggest_pickup_absorbed)
    c["kadi_declarations"] += kadi_declarations
    c["aces_played"] += aces_played
    c["jump_skips_dealt"] += jump_skips_dealt
    c["kickback_reversals"] += kickback_reversals
    c["ace_shield_uses"] += ace_shield_uses
    c["ace_shield_biggest"] = max(c["ace_shield_biggest"], ace_shield_biggest)
    if undo_used_this_game:
        c["undo_tokens_used_total"] += 1  # per-token increments happen at spend time too (see game_manager)
    else:
        c["undo_free_game_count"] += 1
    if won and cards_drawn == 0:
        c["flawless_game_count"] += 1
    if won:
        c["win_streak_current"] += 1
        c["win_streak_best"] = max(c["win_streak_best"], c["win_streak_current"])
    else:
        c["win_streak_current"] = 0

    tier(c["cards_played"], (250, "cards_played_250", 1000, "cards_played_1000",
                              5000, "cards_played_5000", 15000, "cards_played_15000"))
    tier(c["cards_drawn"], (100, "cards_drawn_100", 500, "cards_drawn_500", 2000, "cards_drawn_2000"))
    tier(c["biggest_pickup_absorbed"], (7, "pickup_hit_7", 12, "pickup_hit_12", 18, "pickup_hit_18"))
    tier(c["kadi_declarations"], (10, "kadi_10", 50, "kadi_50", 200, "kadi_200"))
    tier(c["aces_played"], (25, "aces_25", 100, "aces_100", 400, "aces_400"))
    tier(c["jump_skips_dealt"], (20, "jump_skips_20", 100, "jump_skips_100"))
    tier(c["kickback_reversals"], (20, "kickback_20", 100, "kickback_100"))
    tier(c["ace_shield_uses"], (50, "ace_shield_50",))
    tier(c["undo_tokens_used_total"], (10, "undo_used_10", 50, "undo_used_50"))
    tier(c["undo_free_game_count"], (20, "purist_20",))
    tier(c["flawless_game_count"], (10, "flawless_10", 50, "flawless_50"))
    tier(c["win_streak_best"], (5, "streak_5", 10, "streak_10", 20, "streak_20"))

    if finish_kind and finish_kind in _FINISH_TIERS:
        tier(profile["multi_card_finishes"][finish_kind], _FINISH_TIERS[finish_kind])

    hours = profile.get("total_time_played_secs", 0.0) / 3600.0
    tier(hours, (1, "time_1h", 25, "time_25h", 100, "time_100h"))

    if profile["msomi"]["games_won_with_msomi"] >= 10:
        award("msomi_whisperer")

    return newly
