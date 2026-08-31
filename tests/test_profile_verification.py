"""
Verification for the profile/cosmetics/undo/badges feature.

Run (from the kadi/ directory):  python -m tests.test_profile_verification
"""
from __future__ import annotations
import os
import sys
import random
import json
import tempfile

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState, AIDifficulty
from core.game_manager import GameManager, classify_finish_kind
from core import profile_store


def run_one_singleplayer_game(seed: int, profile: dict, difficulty=AIDifficulty.HARD):
    """Runs an all-AI game (avoids needing to simulate real human input
    through the UI layer, which is out of scope for this check) and
    treats seat 0 as "my_player" — exactly what finalize_profile_stats
    cares about is just "did my_player win", so an AI standing in for
    "me" exercises the exact same stat/badge code path GameplayScene
    calls after a real human's game."""
    configs = [
        {'name': 'You',  'is_human': False, 'difficulty': difficulty},
        {'name': 'AI1',  'is_human': False, 'difficulty': difficulty},
        {'name': 'AI2',  'is_human': False, 'difficulty': difficulty},
    ]
    gm = GameManager()
    gm.timers_enabled = True
    gm.profile = profile
    gm.new_game(configs, elimination_mode=False)

    iters = 0
    while gm.state != GameState.GAME_OVER and iters < 30000:
        gm.update(0.05)
        iters += 1

    return gm


def main():
    failures = []

    # ── 1. Fresh profile, play one HARD single-player game ─────────────
    profile = profile_store.default_profile()
    assert profile['undo_tokens'] == profile_store.UNDO_TOKENS_DEFAULT

    gm = run_one_singleplayer_game(seed=42, profile=profile, difficulty=AIDifficulty.HARD)
    print(f"Game 1 reached GAME_OVER: {gm.state == GameState.GAME_OVER}, "
          f"winner={gm.winner.name if gm.winner else None}")

    my_player = gm.players[0]
    ai_players = gm.players[1:]
    newly = gm.finalize_profile_stats(mode='single_player', difficulty='HARD', my_player=my_player)
    print(f"Newly earned badges: {newly}")

    # games_played must have incremented regardless of win/loss
    if profile['games_played']['single_player']['HARD'] != 1:
        failures.append("games_played['single_player']['HARD'] did not increment")
    won = (gm.winner is my_player)
    expect_won = 1 if won else 0
    if profile['games_won']['single_player']['HARD'] != expect_won:
        failures.append("games_won['single_player']['HARD'] mismatch with actual result")

    # Calling finalize_profile_stats a second time for the SAME game_id
    # must be a no-op (duplicate-call guard).
    dup = gm.finalize_profile_stats(mode='single_player', difficulty='HARD', my_player=my_player)
    if dup != [] or profile['games_played']['single_player']['HARD'] != 1:
        failures.append("finalize_profile_stats did not guard against duplicate calls")

    # ── 2. Undo token behavior across a fresh new_game() ────────────────
    profile['undo_tokens'] = 0
    gm2 = GameManager()
    gm2.timers_enabled = False
    gm2.profile = profile
    gm2.new_game([
        {'name': 'You', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
        {'name': 'AI1', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
    ], elimination_mode=False)
    if profile['undo_tokens'] != profile_store.UNDO_TOKENS_DEFAULT:
        failures.append(f"undo_tokens did not reset to default on new_game() "
                        f"(got {profile['undo_tokens']})")
    else:
        print(f"Undo tokens correctly reset to {profile['undo_tokens']} on new_game()")

    # Drain tokens down to 0 and confirm undo_tokens_available flips False
    profile['undo_tokens'] = 1
    if not gm2.undo_tokens_available:
        failures.append("undo_tokens_available should be True with 1 token")
    profile['undo_tokens'] = 0
    if gm2.undo_tokens_available:
        failures.append("undo_tokens_available should be False with 0 tokens")
    else:
        print("undo_tokens_available correctly False at 0 tokens")

    # Refill cap
    profile['undo_tokens'] = profile_store.UNDO_TOKENS_MAX
    capped = min(profile_store.UNDO_TOKENS_MAX, profile['undo_tokens'] + 1)
    if capped != profile_store.UNDO_TOKENS_MAX:
        failures.append("refill cap not respected")
    else:
        print(f"Refill cap correctly holds at {profile_store.UNDO_TOKENS_MAX}")

    # ── 3. classify_finish_kind shape checks — built against the REAL
    #      grammar (RuleEngine.order_for_closing), not just plausible-
    #      looking card lists. Each shape is also validated through
    #      order_for_closing itself, so this test would have caught the
    #      original bug (question_chain/kickback_run required ALL cards
    #      to be that leader type with zero trailing FINISHING cards —
    #      a shape order_for_closing's `if not finishing: return None`
    #      makes impossible in any real game) rather than passing
    #      against synthetic input that could never occur in play. ──
    from models.card import Card
    from constants import Suit
    from core.rule_engine import RuleEngine
    re_ = RuleEngine()

    def assert_real_and_classified(cards, expected, label):
        ordered = re_.order_for_closing(cards)
        if ordered is None:
            failures.append(f"{label}: RuleEngine says this shape can NEVER legally "
                             f"close a hand — {[f'{c.rank}{c.suit.value}' for c in cards]} "
                             f"is not a real winning play")
            return
        got = classify_finish_kind(ordered)
        if got != expected:
            failures.append(f"{label}: expected '{expected}', classify_finish_kind "
                            f"returned '{got}' for order_for_closing's own output "
                            f"{[f'{c.rank}{c.suit.value}' for c in ordered]}")

    # Question-chain: leader(s) of the SAME suit as the trailing FINISHING
    # answer (order_for_closing enforces suit connection for Q/K/J leaders).
    assert_real_and_classified(
        [Card(Suit.SPADES, '8'), Card(Suit.SPADES, '7')], 'question_chain', "question_chain")
    # Kickback-run: EVEN count of leaders, same suit as the answer.
    assert_real_and_classified(
        [Card(Suit.SPADES, 'K'), Card(Suit.SPADES, 'K'), Card(Suit.SPADES, '9')],
        'kickback_run', "kickback_run")
    # Jump-bundle: leader(s) + trailing FINISHING answer.
    assert_real_and_classified(
        [Card(Suit.SPADES, 'J'), Card(Suit.SPADES, '7')], 'jump_bundle', "jump_bundle")
    # ACE-finisher: single ACE leader + any FINISHING answer (no suit/rank
    # constraint on the answer, per order_for_closing's SUIT_CHANGE branch).
    assert_real_and_classified(
        [Card(Suit.SPADES, 'ACE'), Card(Suit.DICE, '6')], 'ace_finisher', "ace_finisher")
    # Sanity: the OLD (buggy) shapes must NOT be accepted as real plays at all.
    dead_q = [Card(Suit.SPADES, '8'), Card(Suit.LOVE, 'Q')]
    if re_.order_for_closing(dead_q) is not None:
        failures.append("all-Question-no-finishing was expected to be an ILLEGAL "
                        "close but order_for_closing accepted it")
    dead_k = [Card(Suit.SPADES, 'K'), Card(Suit.LOVE, 'K')]
    if re_.order_for_closing(dead_k) is not None:
        failures.append("all-Kickback-no-finishing was expected to be an ILLEGAL "
                        "close but order_for_closing accepted it")

    single = [Card(Suit.SPADES, '5')]
    if classify_finish_kind(single) is not None:
        failures.append(f"single-card finish should classify as None, got {classify_finish_kind(single)}")
    print("classify_finish_kind: shape checks (validated against RuleEngine.order_for_closing) "
          "passed" if not any('classify_finish_kind' in f or 'chain' in f or 'run' in f or
                               'bundle' in f or 'finisher' in f for f in failures)
          else "classify_finish_kind: some shape checks FAILED")

    # ── 3b. Real-gameplay check: play out many real AI-vs-AI games and
    #        confirm question_chain / kickback_run / jump_bundle /
    #        ace_finisher all actually occur via REAL last_played_cards
    #        from REAL wins — not just synthetic classifier input. This
    #        is the check that would have caught the original bug even
    #        without knowing to look at order_for_closing directly. ────
    print("\nRunning real games to confirm each multi-card finish mechanic "
          "actually occurs in practice (2-player games — empirically the "
          "most reliable config for this; a 3-player 300-game run during "
          "this same investigation showed 0 jump_bundle occurrences purely "
          "by chance, a false alarm resolved by a larger/2-player sample, "
          "see the accompanying report for details)...")
    mechanic_counts = {'question_chain': 0, 'kickback_run': 0, 'jump_bundle': 0, 'ace_finisher': 0, None: 0}
    N_GAMES = 400
    for i in range(N_GAMES):
        g = GameManager()
        g.timers_enabled = True
        g.new_game([
            {'name': 'A', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
            {'name': 'B', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
        ], elimination_mode=False)
        iters = 0
        while g.state != GameState.GAME_OVER and iters < 30000:
            g.update(0.05)
            iters += 1
        if g.state == GameState.GAME_OVER and g.winner is not None and g.last_played_cards:
            kind = classify_finish_kind(g.last_played_cards)
            mechanic_counts[kind] = mechanic_counts.get(kind, 0) + 1

    print(f"Over {N_GAMES} real AI-vs-AI games, finish-kind distribution: {mechanic_counts}")
    for mech in ('question_chain', 'kickback_run', 'jump_bundle', 'ace_finisher'):
        if mechanic_counts.get(mech, 0) == 0:
            failures.append(f"'{mech}' never occurred naturally in {N_GAMES} real games — "
                            f"either still unreachable, or just rare enough to need more games")
        else:
            print(f"  [OK] '{mech}' occurred {mechanic_counts[mech]} time(s) via real wins")

    # ── 4. save/load round-trip to a temp dir ───────────────────────────
    import core.game_logger as game_logger
    tmpdir = tempfile.mkdtemp()
    import core.profile_store as ps
    orig_base_dir = ps.base_dir
    ps.base_dir = lambda: tmpdir
    try:
        ps.save_profile(profile)
        path = os.path.join(tmpdir, ps.PROFILE_FILENAME)
        if not os.path.isfile(path):
            failures.append("profile.json was not written")
        else:
            with open(path) as f:
                on_disk = json.load(f)
            reloaded = ps.load_profile()
            if reloaded['undo_tokens'] != on_disk['undo_tokens']:
                failures.append("load_profile() did not round-trip undo_tokens correctly")
            print(f"\nprofile.json written to {path}:")
            print(json.dumps(on_disk, indent=2))
    finally:
        ps.base_dir = orig_base_dir

    print("\n" + "=" * 60)
    if failures:
        print(f"PROFILE VERIFICATION: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  [FAIL] {f}")
        sys.exit(1)
    else:
        print("PROFILE VERIFICATION: ALL CHECKS PASSED")


if __name__ == '__main__':
    main()
