"""
Field-reported bug: a human/AI player who goes cardless (0 cards)
while a pickup debt (from a Red-Joker-led / countered pick-up chain)
is pending against THEM was getting the generic "cardless auto-draw
1 card" treatment, with the pickup debt left dangling on the rule
engine instead of being resolved. The turn would then move on and the
debt would get silently charged to whichever OTHER player next
happened to voluntarily draw a card — even one who had already taken
their own turn and countered.

Concretely, from the field log: BMK played [Red Joker, 3(clubs)],
leaving Player 2 to pick up 8. Player 2 countered with a 2(clubs),
raising the debt to 10 and passing it back to BMK — but BMK had just
gone cardless doing so. On BMK's next turn (hand empty, pickup_pending
== 10) the old code just dealt BMK 1 card and moved on; the 10-card
debt then got dumped onto Player 2 on THEIR following turn instead.

This test drives that exact shape of scenario directly against
GameManager/RuleEngine (no UI, no full random deal) and asserts the
cardless player pays their own pending pickup in full, immediately.

Run (from the kadi/ directory):  python -m tests.test_cardless_pickup_debt
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState, Suit
from core.game_manager import GameManager
from models.card import Card

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def run_cardless_owes_pickup():
    print("\n-- Cardless player on the hook for a pending pickup pays it themselves --")
    gm = GameManager()
    gm.new_game([
        {'name': 'BMK', 'is_human': True},
        {'name': 'Player 2', 'is_human': True},
    ])
    gm.state = GameState.PLAYING

    bmk, p2 = gm.players[0], gm.players[1]

    # Reproduce the exact moment from the log: BMK just played their
    # last two cards (Red Joker + 3-clubs), leaving themselves cardless
    # with a pickup debt of 10 outstanding against them (already raised
    # once by Player 2's countering 2-clubs), and it's now BMK's turn.
    bmk.hand.remove(list(bmk.hand.cards))
    gm.rule_engine.pickup_pending = 10
    gm.rule_engine.pickup_suit = Suit.FLOWERS
    gm.rule_engine._top_card = Card(suit=gm.rule_engine.pickup_suit, rank='2')
    gm.current_player_idx = 0
    p2_count_before = p2.hand.count

    gm._start_turn()

    check("BMK's hand was NOT left empty (they paid the pickup themselves)",
          bmk.hand.count == 10)
    check("the pickup debt was actually resolved (not left dangling)",
          gm.rule_engine.pickup_pending == 0)
    check("it is still BMK being resolved, not silently Player 2",
          gm.current_player_idx == 0)
    check("Player 2's hand was untouched by BMK's debt",
          p2.hand.count == p2_count_before)
    check("game correctly opened POST_PLAY for BMK after the forced draw",
          gm.state == GameState.POST_PLAY)


def run_cardless_no_pickup_unaffected():
    print("\n-- Cardless player with NO pending pickup still gets the normal 1-card draw --")
    gm = GameManager()
    gm.new_game([
        {'name': 'BMK', 'is_human': True},
        {'name': 'Player 2', 'is_human': True},
    ])
    gm.state = GameState.PLAYING
    bmk = gm.players[0]
    bmk.hand.remove(list(bmk.hand.cards))
    gm.rule_engine.pickup_pending = 0
    gm.current_player_idx = 0

    gm._start_turn()

    check("cardless player with no pickup debt draws exactly 1 card (unchanged behavior)",
          bmk.hand.count == 1)
    check("state correctly opened POST_PLAY", gm.state == GameState.POST_PLAY)


if __name__ == '__main__':
    run_cardless_owes_pickup()
    run_cardless_no_pickup_unaffected()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"CARDLESS PICKUP DEBT: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("CARDLESS PICKUP DEBT: ALL CHECKS PASSED")
        sys.exit(0)
