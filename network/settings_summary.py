"""
KADI - shared, pygame-free helpers describing a GameManager's current
rule configuration (turn timer, hints, ace/pickup/jump rule toggles,
etc). Used by BOTH:

  - LAN (scenes.LANHostLobbyScene / LANJoinScene, via
    scenes._build_settings_summary, which now just delegates here)
  - Internet Multiplayer (server/game_room.GameRoom, which has no
    pygame dependency and previously could not import scenes.py at all)

so the two can never show different values for the same setting, and
so a hosting player's own locally-configured rules (turn timer on/off,
Ace Finisher, Jump Multi-card, etc -- whatever their own Settings
screen last saved) travel with them onto an Internet-hosted game the
exact same way they already travel "for free" onto a LAN host's own
live GameManager (LAN's host IS the real GameManager, so there was
never anything to carry over there; Internet's host is a thin client
of a SEPARATE GameManager on the server, so this module is what makes
that carry-over actually happen -- see rule_settings_payload() /
apply_rule_settings() below).

Deliberately NOT included here: Elimination Mode (each caller has its
own live/local source for that -- see build_settings_summary() vs.
server/game_room.py's own settings_summary_rows()) and AI-fill
count/difficulty/MSOMI (also caller-specific -- MSOMI in particular is
NOT supported for Internet-hosted AI seats, since the trained model
file lives on the hosting player's own machine, not the server; see
server/README.md).
"""
from __future__ import annotations
from typing import List, Tuple

# (attribute name, type, min, max) for every rule a GameManager
# exposes that a hosting player can carry over to a game they create.
# min/max are None for bools (no clamping needed).
RULE_SETTING_SPECS = [
    ('timers_enabled',           bool,  None, None),
    ('turn_timer_secs',          float, 0.0,  300.0),
    ('hints_enabled',            bool,  None, None),
    ('hint_threshold_pct',       float, 0.0,  100.0),
    ('post_play_delay_secs',     float, 0.0,  120.0),
    ('counter_window_secs',      float, 0.0,  120.0),
    ('ace_suit_integrity',       bool,  None, None),
    ('pickup_shield_qk_allowed', bool,  None, None),
    ('ace_finisher_enabled',     bool,  None, None),
    ('jump_multi_card_enabled',  bool,  None, None),
]


def rule_settings_payload(gm) -> dict:
    """Snapshot of a GameManager's current rule configuration as
    plain JSON-safe primitives -- what a hosting client sends the
    Internet server inside create_game's settings dict, so the
    server's own GameManager picks up the SAME rules the host's local
    app is currently configured with."""
    return {name: getattr(gm, name) for name, _, _, _ in RULE_SETTING_SPECS}


def apply_rule_settings(gm, payload: dict):
    """Applies a rule_settings_payload()-shaped dict onto a
    GameManager, validating/clamping every value defensively -- this
    runs server-side, accepting client-supplied data. Anything
    missing, unrecognized, or malformed is silently skipped rather
    than raising, so a bad/absent settings dict just leaves
    GameManager's own class defaults in place instead of ever
    crashing the room."""
    if not isinstance(payload, dict):
        return
    for name, typ, lo, hi in RULE_SETTING_SPECS:
        if name not in payload:
            continue
        raw = payload[name]
        try:
            if typ is bool:
                value = bool(raw)
            else:
                value = typ(raw)
                if lo is not None:
                    value = max(lo, value)
                if hi is not None:
                    value = min(hi, value)
        except (TypeError, ValueError):
            continue
        setattr(gm, name, value)


def build_rule_rows(gm) -> List[Tuple[str, str]]:
    """The read-only rule-configuration rows -- everything EXCEPT
    Elimination Mode and AI-fill, which each caller renders from its
    own live/local source instead (see build_settings_summary() below
    for LAN's version, and server/game_room.py's
    settings_summary_rows() for Internet's)."""
    return [
        ("Turn Timer", f"ON ({gm.turn_timer_secs:.0f}s)"
         if gm.timers_enabled else "OFF"),
        ("Hints", f"ON (after {gm.hint_threshold_pct:.0f}% of timer)"
         if (gm.hints_enabled and gm.timers_enabled) else "OFF"),
        ("Post-play window", f"{gm.post_play_delay_secs:.1f}s"),
        ("Jump Counter window", f"{gm.counter_window_secs:.1f}s"),
        ("Ace Suit Integrity", "ON" if gm.ace_suit_integrity else "OFF"),
        ("Pickup Shield (Q/K)", "ON" if gm.pickup_shield_qk_allowed else "OFF"),
        ("Ace Finisher", "ON" if gm.ace_finisher_enabled else "OFF"),
        ("Jump Multi-card", "ON" if gm.jump_multi_card_enabled else "OFF"),
    ]


def build_settings_summary(gm) -> List[Tuple[str, str]]:
    """Full LAN-style summary (Elimination Mode + all rule rows),
    reading Elimination Mode directly off `gm` -- correct for LAN's
    own screens, where by the time this is called `gm` IS (or is
    about to become) the actual game. Byte-for-byte the same rows
    LANHostLobbyScene / LANJoinScene have always shown; only the
    function's location moved (out of scenes.py, which needs pygame,
    into this shared module, which doesn't) so Internet Multiplayer's
    server process can reuse the exact same row-building logic."""
    rows: List[Tuple[str, str]] = [
        ("Elimination Mode", "ON" if gm.elimination_mode else "OFF"),
    ]
    if gm.elimination_mode:
        rows.append(("  AI continues alone",
                     "ON" if gm.elimination_ai_only_continue else "OFF"))
    rows.extend(build_rule_rows(gm))
    return rows
