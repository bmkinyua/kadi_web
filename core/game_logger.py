"""
KADI - Game logging utility.

Provides a single configurable logger ('kadi') that, depending on the
configured level, writes a timestamped log file into a `logs/` folder
inside KADI's per-user application data directory (not next to the
executable/script — see _base_dir() below).

Levels:
  OFF  - no logging at all (default for normal play)
  LOW  - only major events: turns, plays, draws, wins, errors
  HIGH - everything: every rule-engine decision, button click, state
         transition. Use this during development/bug-hunting, then
         share the resulting log file.

Usage:
    from core.game_logger import game_log, set_log_level
    set_log_level("HIGH")
    game_log.info("Something happened")
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime

LOG_DIR_NAME = "logs"

_logger = logging.getLogger("kadi")
_logger.setLevel(logging.CRITICAL + 1)  # effectively silent until configured
_file_handler: logging.Handler | None = None
_current_level_name: str = "OFF"


APP_NAME = "KADI"

# Filenames/dirnames that live directly in the app data directory — used
# by _migrate_legacy_data_if_needed() to know what to look for/copy from
# the old next-to-executable location. Kept here (rather than importing
# each dependent module's constant) to avoid any import cycles, since
# those modules import FROM this one.
_LEGACY_ENTRIES = ("logs", "msomi_models", "settings.json", "savegame.json")

_migration_done = False


def _legacy_base_dir() -> str:
    """The OLD behavior: directory the executable/script lives in. Kept
    only as (a) the source for one-time migration and (b) the fallback
    for unknown/unsupported OSes."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # core/game_logger.py -> kadi/ (project root)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _per_user_data_dir() -> str:
    """OS-conventional per-user application data directory for KADI.
    Always writable regardless of where the game itself is installed
    (e.g. Program Files / /Applications, which typically aren't writable
    without elevation once packaged by a real installer)."""
    plat = sys.platform

    if plat.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return os.path.join(root, APP_NAME)
        return _legacy_base_dir()

    if plat == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                             "Application Support", APP_NAME)

    if plat.startswith("linux"):
        root = os.environ.get("XDG_DATA_HOME")
        if not root:
            root = os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(root, APP_NAME)

    # Unknown/unsupported OS — don't guess, keep the old safe behavior.
    return _legacy_base_dir()


def _migrate_legacy_data_if_needed(new_dir: str) -> None:
    """One-time migration: if `new_dir` doesn't exist yet (first run
    under the new per-user-data-dir behavior) and the OLD next-to-
    executable location has any of logs/, msomi_models/, settings.json,
    or savegame.json, copy them over. Never overwrites — only runs on a
    clean first run under the new behavior, so it's safe to call this
    on every startup; after the first successful run `new_dir` already
    exists and this becomes a no-op immediately."""
    global _migration_done
    if _migration_done:
        return
    _migration_done = True

    if os.path.exists(new_dir):
        return  # already migrated (or a fresh per-user dir with real data)

    old_dir = _legacy_base_dir()
    if os.path.normcase(os.path.abspath(old_dir)) == os.path.normcase(os.path.abspath(new_dir)):
        return  # legacy and new resolve to the same place (unknown OS) — nothing to migrate

    found = [e for e in _LEGACY_ENTRIES if os.path.exists(os.path.join(old_dir, e))]
    if not found:
        return

    import shutil
    os.makedirs(new_dir, exist_ok=True)
    migrated = []
    for entry in found:
        src = os.path.join(old_dir, entry)
        dst = os.path.join(new_dir, entry)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            migrated.append(entry)
        except Exception as e:
            game_log.info(f"Migration: failed to copy {entry}: {e}")

    if migrated:
        game_log.info(
            f"Migrated legacy data from {old_dir} to {new_dir}: {', '.join(migrated)}")


def _base_dir() -> str:
    """Per-user application data directory KADI reads/writes everything
    from (logs, MSOMI models, settings, save file) — OS-conventional and
    always writable, regardless of where the game itself is installed."""
    new_dir = _per_user_data_dir()
    _migrate_legacy_data_if_needed(new_dir)
    os.makedirs(new_dir, exist_ok=True)
    return new_dir


def base_dir() -> str:
    """Public alias of _base_dir() for other modules (e.g. settings_store)
    that need the same per-user application data directory convention."""
    return _base_dir()


def get_log_dir() -> str:
    """Public: the logs/ directory itself, created if it doesn't exist
    yet — used by Chuo's log-file picker so it always looks in exactly
    the same place every log and JSONL sidecar actually gets written."""
    log_dir = os.path.join(_base_dir(), LOG_DIR_NAME)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _new_log_path() -> str:
    log_dir = os.path.join(_base_dir(), LOG_DIR_NAME)
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    return os.path.join(log_dir, f"LOG_{stamp}.log")


def set_log_level(level_name: str):
    """level_name: 'OFF', 'LOW', or 'HIGH'."""
    global _file_handler, _current_level_name
    level_name = (level_name or "OFF").upper()
    _current_level_name = level_name

    # Tear down any existing file handler first
    if _file_handler is not None:
        _logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass
        _file_handler = None

    if level_name == "OFF":
        _logger.setLevel(logging.CRITICAL + 1)
        return

    py_level = logging.INFO if level_name == "LOW" else logging.DEBUG
    _logger.setLevel(py_level)

    path = _new_log_path()
    handler = logging.FileHandler(path, mode='w', encoding='utf-8')
    handler.setLevel(py_level)
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S")
    handler.setFormatter(fmt)
    _logger.addHandler(handler)
    _file_handler = handler
    _logger.info(f"=== KADI log started — level={level_name} — {path} ===")


def get_log_level() -> str:
    return _current_level_name


def cleanup_old_logs(max_pairs: int, log_dir: str | None = None) -> int:
    """Enforce a cap on the number of LOG_*.log (+ paired .jsonl sidecar)
    files kept in the logs/ folder, deleting the OLDEST pairs first once
    the count exceeds max_pairs.

    max_pairs <= 0 means "unlimited" (the default — see
    core/settings_store.py's DEFAULTS['max_log_pairs']) and this is a
    guaranteed no-op in that case, since these logs are also Chuo/MSOMI
    training data (see ChuoScene's Data tab) and a player may want
    months of accumulated games to train from; the cap is opt-in, not
    imposed.

    log_dir is only exposed for tests — real callers should omit it and
    let this resolve get_log_dir() itself, same as every other log path
    in this module.

    A "pair" is identified by its .log file; a missing .jsonl sidecar
    (logging was HIGH/LOW but MSOMI decision-logging produced nothing,
    or a partial/older log predates the sidecar convention) is fine —
    only the files that actually exist get deleted. Ordering is by file
    mtime (NOT filename — _new_log_path()'s DDMMYYYY_HHMMSS stamp sorts
    correctly within a single day but NOT across month/year boundaries,
    e.g. "16082026" would incorrectly sort before "01092026").

    Returns the number of pairs deleted (0 if nothing needed deleting,
    including the max_pairs<=0 no-op case).
    """
    if max_pairs <= 0:
        return 0

    target_dir = log_dir if log_dir is not None else get_log_dir()
    try:
        entries = os.listdir(target_dir)
    except OSError:
        return 0

    log_files = [f for f in entries if f.startswith("LOG_") and f.endswith(".log")]
    if len(log_files) <= max_pairs:
        return 0

    def _mtime(fname: str) -> float:
        try:
            return os.path.getmtime(os.path.join(target_dir, fname))
        except OSError:
            return 0.0

    # Oldest first.
    log_files.sort(key=_mtime)
    to_delete = log_files[:len(log_files) - max_pairs]

    deleted = 0
    for fname in to_delete:
        log_path = os.path.join(target_dir, fname)
        jsonl_path = os.path.splitext(log_path)[0] + ".jsonl"
        ok = True
        for p in (log_path, jsonl_path):
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError as e:
                    ok = False
                    game_log.info(f"cleanup_old_logs: failed to remove {p}: {e}")
        if ok:
            deleted += 1
    return deleted


def get_current_jsonl_path() -> str | None:
    """Path of the MSOMI decision-log JSONL sidecar for the CURRENT text
    log file, or None if logging is off. Always the text log's own path
    with a .jsonl extension instead of .log, so the two rotate together
    automatically — one is for people to read, the other (see
    core/decision_logger.py) is the full-fidelity, machine-readable
    training data Chuo reads from. Deriving this fresh from the file
    handler each call (rather than tracking it separately) means there's
    only one source of truth for "is logging on and where," so the two
    files can never drift out of sync with each other."""
    if _file_handler is None:
        return None
    base, _ = os.path.splitext(_file_handler.baseFilename)
    return base + ".jsonl"


# Convenience proxy object: game_log.info(...), game_log.debug(...), etc.
game_log = _logger
