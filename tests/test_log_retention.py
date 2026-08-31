"""
Verifies the log-pair retention cap added to core/game_logger.py
(cleanup_old_logs), core/settings_store.py's DEFAULTS['max_log_pairs'],
and core/game_manager.py's GameManager.max_log_pairs.

Covers:
  - max_pairs <= 0 is a guaranteed no-op (default — "unlimited")
  - under-the-cap directories are left untouched
  - over-the-cap directories delete the OLDEST pairs first, by mtime
    (NOT filename — LOG_*.log's DDMMYYYY stamp does not sort correctly
    across month/year boundaries, so this specifically exercises a
    case where filename-sort and mtime-sort disagree)
  - a .log file with no .jsonl sidecar (partial/older log) is handled
    without error — only files that actually exist get removed
  - settings round-trip: max_log_pairs persists via
    settings_to_dict()/apply_settings_dict() same as every other
    DEFAULTS key, and defaults to 0 (unlimited) on a fresh GameManager

Run (from the kadi/ directory):  python -m tests.test_log_retention
"""
from __future__ import annotations
import os
import sys
import tempfile
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_logger import cleanup_old_logs
from core.game_manager import GameManager
from core.settings_store import DEFAULTS, settings_to_dict, apply_settings_dict

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def _make_pair(d, base, mtime):
    log_p = os.path.join(d, base + ".log")
    jsonl_p = os.path.join(d, base + ".jsonl")
    with open(log_p, "w") as f:
        f.write("x")
    with open(jsonl_p, "w") as f:
        f.write("x")
    os.utime(log_p, (mtime, mtime))
    os.utime(jsonl_p, (mtime, mtime))
    return log_p, jsonl_p


def test_unlimited_is_noop():
    with tempfile.TemporaryDirectory() as d:
        for i in range(5):
            _make_pair(d, f"LOG_pair{i}", time.time() + i)
        deleted = cleanup_old_logs(0, log_dir=d)
        check("max_pairs=0 deletes nothing", deleted == 0)
        check("max_pairs=0 leaves all files", len(os.listdir(d)) == 10)

        deleted = cleanup_old_logs(-5, log_dir=d)
        check("negative max_pairs also a no-op", deleted == 0 and len(os.listdir(d)) == 10)


def test_under_cap_is_noop():
    with tempfile.TemporaryDirectory() as d:
        for i in range(3):
            _make_pair(d, f"LOG_pair{i}", time.time() + i)
        deleted = cleanup_old_logs(10, log_dir=d)
        check("under-cap directory untouched", deleted == 0 and len(os.listdir(d)) == 6)


def test_deletes_oldest_by_mtime_not_filename():
    with tempfile.TemporaryDirectory() as d:
        # Deliberately construct filenames whose DDMMYYYY string-sort
        # ORDER disagrees with real chronological (mtime) order — a
        # January file should string-sort before a December one from
        # the PREVIOUS year, but is actually newer.
        now = time.time()
        old_base = "LOG_15122025_120000"   # 15 Dec 2025 — chronologically oldest
        new_base = "LOG_10012026_090000"   # 10 Jan 2026 — chronologically newest
        mid_base = "LOG_20122025_150000"   # 20 Dec 2025 — chronologically middle

        _make_pair(d, old_base, now - 300)
        _make_pair(d, mid_base, now - 200)
        _make_pair(d, new_base, now - 100)

        deleted = cleanup_old_logs(2, log_dir=d)
        remaining = sorted(os.listdir(d))
        check("deletes exactly 1 pair to get from 3 to cap of 2", deleted == 1)
        check("the chronologically OLDEST pair is gone",
              f"{old_base}.log" not in remaining and f"{old_base}.jsonl" not in remaining)
        check("the two newer pairs survive",
              f"{mid_base}.log" in remaining and f"{new_base}.log" in remaining)


def test_missing_jsonl_sidecar_handled():
    with tempfile.TemporaryDirectory() as d:
        # Oldest pair has no .jsonl sidecar at all.
        log_only = os.path.join(d, "LOG_bare.log")
        with open(log_only, "w") as f:
            f.write("x")
        os.utime(log_only, (time.time() - 100, time.time() - 100))
        _make_pair(d, "LOG_full", time.time())

        deleted = cleanup_old_logs(1, log_dir=d)
        remaining = sorted(os.listdir(d))
        check("bare .log (no sidecar) deleted without error", deleted == 1)
        check("only the newer full pair remains",
              remaining == sorted(["LOG_full.log", "LOG_full.jsonl"]))


def test_settings_defaults_and_roundtrip():
    check("DEFAULTS has max_log_pairs = 0 (unlimited)",
          DEFAULTS.get('max_log_pairs') == 0)

    gm = GameManager()
    check("fresh GameManager defaults to unlimited", gm.max_log_pairs == 0)

    gm.max_log_pairs = 42
    data = settings_to_dict(gm)
    check("settings_to_dict includes max_log_pairs", data.get('max_log_pairs') == 42)

    gm2 = GameManager()
    apply_settings_dict(gm2, data)
    check("apply_settings_dict round-trips the value", gm2.max_log_pairs == 42)


def main():
    print("=== test_log_retention ===")
    test_unlimited_is_noop()
    test_under_cap_is_noop()
    test_deletes_oldest_by_mtime_not_filename()
    test_missing_jsonl_sidecar_handled()
    test_settings_defaults_and_roundtrip()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
