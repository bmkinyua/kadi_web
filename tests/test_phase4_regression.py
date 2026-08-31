"""
PHASE 4 verification: full regression. Confirms single-player (human
vs AI, NO networking at all — no network/* module is even imported by
this file) still works exactly as before, via a headless AI-vs-AI
simulation: ~100 complete games, varying player count and Elimination
Mode, driven purely through core.game_manager.GameManager.update(dt)
exactly the way the real game loop does, checking every game reaches a
real GAME_OVER with no exception and no stall.

This is the one file in this feature that deliberately does NOT import
anything under network/ — its whole point is proving the untouched
majority of the game (core/game_manager.py, core/rule_engine.py,
models/*) still behaves identically, so it needs to exercise exactly
the same code path single-player already used before this feature
existed.

Run (from the kadi/ directory):  python -m tests.test_phase4_regression
"""
from __future__ import annotations
import os
import sys
import random

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState, AIDifficulty
from core.game_manager import GameManager

N_GAMES = 100
DT = 0.05
MAX_ITERS = 30000  # 1500 simulated seconds — elimination-mode games with more
                    # players can run notably longer (players get eliminated
                    # one at a time rather than ending at the first finisher),
                    # so this is set generously high specifically to avoid
                    # confusing "just a long game" with an actual stall.

FAILURES = []
DIFFICULTIES = [AIDifficulty.EASY, AIDifficulty.MEDIUM, AIDifficulty.HARD]


def run_one_game(seed: int) -> dict:
    rng = random.Random(seed)
    n_players = rng.randint(2, 6)
    elimination_mode = rng.random() < 0.5
    configs = [
        {'name': f'AI{i}', 'is_human': False, 'difficulty': rng.choice(DIFFICULTIES)}
        for i in range(n_players)
    ]

    gm = GameManager()
    gm.timers_enabled = True
    gm.new_game(configs, elimination_mode=elimination_mode,
               elimination_ai_only_continue=True)

    iters = 0
    while gm.state != GameState.GAME_OVER and iters < MAX_ITERS:
        gm.update(DT)
        iters += 1

    return {
        'seed': seed,
        'n_players': n_players,
        'elimination_mode': elimination_mode,
        'reached_game_over': gm.state == GameState.GAME_OVER,
        'iters': iters,
        'winner': gm.winner.name if gm.winner else None,
    }


def run():
    print(f"Running {N_GAMES} headless AI-vs-AI games "
          f"(SDL_VIDEODRIVER={os.environ.get('SDL_VIDEODRIVER')})...")
    results = []
    crashes = 0
    stalls = 0
    for i in range(N_GAMES):
        try:
            r = run_one_game(seed=10_000 + i)
        except Exception as e:
            crashes += 1
            print(f"  [CRASH] game {i} (seed={10_000+i}): {type(e).__name__}: {e}")
            continue
        results.append(r)
        if not r['reached_game_over']:
            stalls += 1
            print(f"  [STALL] game {i}: {r['n_players']} players, "
                 f"elimination={r['elimination_mode']}, hit {r['iters']} iters "
                 f"without reaching GAME_OVER")

    print(f"\nCompleted: {len(results)}/{N_GAMES} games ran without exception")
    if results:
        avg_iters = sum(r['iters'] for r in results) / len(results)
        print(f"Average iterations to finish: {avg_iters:.1f} "
             f"(~{avg_iters * DT:.1f} simulated seconds)")

    print(f"\n  [{'PASS' if crashes == 0 else 'FAIL'}] 0 crashes ({crashes} occurred)")
    if crashes:
        FAILURES.append(f"{crashes} game(s) raised an exception")
    print(f"  [{'PASS' if stalls == 0 else 'FAIL'}] 0 stalls ({stalls} occurred)")
    if stalls:
        FAILURES.append(f"{stalls} game(s) never reached GAME_OVER within {MAX_ITERS} iterations")


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"PHASE 4: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(f"PHASE 4: ALL CHECKS PASSED — {N_GAMES}/{N_GAMES} games, 0 crashes, 0 stalls")
        sys.exit(0)
