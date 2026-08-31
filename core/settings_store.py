"""
KADI - Settings persistence.

Saves/loads the subset of GameManager fields that represent user-facing
settings (timers, rules toggles, hints, logging, resolution) to a small
JSON file in KADI's per-user application data directory — the same
directory game_logger uses for the logs/ folder, so everything KADI
writes lives in one place.
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict

from core.game_logger import base_dir, game_log

SETTINGS_FILENAME = "settings.json"

# Every persisted field, with its default. This list is also the source
# of truth for reset_to_defaults() — if a new setting is added to
# GameManager, add it here too and both save/load/reset pick it up.
DEFAULTS: Dict[str, Any] = {
    'turn_timer_secs':           150.0,
    'post_play_delay_secs':      60.0,
    'counter_window_secs':       60.0,
    'timers_enabled':            True,
    'joker_count':               2,
    'suit_change_after_shield':  False,
    'ace_suit_integrity':        False,
    'pickup_shield_qk_allowed':  True,
    'ace_finisher_enabled':      True,
    'jump_multi_card_enabled':   True,
    'log_level':                 'HIGH',
    # 0 = unlimited (default) — see core.game_logger.cleanup_old_logs's
    # own docstring for why this stays opt-in rather than a default
    # cap: these files are also Chuo/MSOMI training data.
    'max_log_pairs':             0,
    'hints_enabled':             False,
    'hint_threshold_pct':        50.0,
    'resolution':                [1280, 800],
    'skip_startup_resolution_picker': False,
    'music_enabled':             True,
    'sfx_enabled':               True,
    'sfx_volume':                0.5,
    'music_volume':              0.5,
    # Dev-only toggle for the placeholder banner ad slot (see scenes.py's
    # AdBanner). No real ad network is wired in, and — per the itch.io
    # -> Steam -> publisher distribution plan (Steam's Steamworks
    # documentation explicitly bans third-party ad networks as a
    # revenue model; see "Advertising on Steam") — none is currently
    # planned. Defaults to False so a fresh install/build never shows
    # the placeholder anywhere, including the main menu. The toggle,
    # AdBanner class, and render-gate logic are all left fully intact
    # (not removed) so this can be flipped back on for testing, or if a
    # direct-sold sponsorship (the one ad-adjacent option Steam's policy
    # still allows) is ever pursued.
    'ads_enabled':                False,
}


def _settings_path() -> str:
    return os.path.join(base_dir(), SETTINGS_FILENAME)


def settings_to_dict(gm) -> Dict[str, Any]:
    data = {}
    for key in DEFAULTS:
        val = getattr(gm, key, DEFAULTS[key])
        # tuples aren't JSON-native; store resolution as a plain list
        if isinstance(val, tuple):
            val = list(val)
        data[key] = val
    return data


def apply_settings_dict(gm, data: Dict[str, Any]):
    for key, default in DEFAULTS.items():
        val = data.get(key, default)
        if key == 'resolution':
            val = tuple(val) if val else tuple(default)
        setattr(gm, key, val)
    # log_level needs to actually (re)configure the logger, not just set
    # the attribute — mirrors what the Settings screen's buttons do.
    gm.set_log_level(getattr(gm, 'log_level', 'OFF'))


def save_settings(gm) -> bool:
    """Write current settings to disk. Returns True on success."""
    try:
        path = _settings_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings_to_dict(gm), f, indent=2)
        return True
    except Exception as e:
        game_log.info(f"Failed to save settings: {e}")
        return False


def load_settings(gm) -> bool:
    """Load settings from disk into gm, if a settings file exists.
    Returns True if a file was found and applied, False if using
    defaults (e.g. first run — the file just doesn't exist yet)."""
    path = _settings_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        apply_settings_dict(gm, data)
        return True
    except Exception as e:
        game_log.info(f"Failed to load settings ({e}) — using defaults")
        return False


def reset_to_defaults(gm):
    """Reset every persisted setting back to its default and save that
    immediately, so 'Reset to Defaults' is itself durable."""
    apply_settings_dict(gm, DEFAULTS)
    save_settings(gm)
