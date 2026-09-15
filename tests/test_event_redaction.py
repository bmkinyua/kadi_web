"""
Verification for: network/state_sync.py's per-recipient redaction of
'card_drawn'/'pickup_drawn' events.

BACKGROUND: network/event_codec.encode_event() is a generic codec that
faithfully encodes whatever a real GameEvent carries — including, for
a voluntary or forced draw, the actual Card(s) that just landed in a
still-hidden hand. It runs once per event, before any recipient is
known, so it has no way to redact anything itself. Before this fix,
network/host_game.py and server/game_room.py both broadcast that same
already-encoded events list unchanged to EVERY connected player —
meaning every client received the true rank/suit of every other
player's draw the instant it happened, even though the snapshot's
'hand' field for that same player was correctly count-only. The card
was never rendered anywhere (nothing consumed event.card for anyone
but the drawer), so this was a silent wire-level leak rather than a
visible one — but a real one: inspectable via a proxy, a modified
client, or simply printing the decoded event.

This is pure data-transformation testing — network/state_sync.py has
no pygame or socket dependency (see its own module docstring), so
this doesn't need a display, a real GameManager, or a live socket at
all; it constructs the encoded event shape event_codec.encode_event()
actually produces and checks what build_snapshot_for() does with it
per recipient.

Run (from the kadi/ directory):  python -m tests.test_event_redaction
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.state_sync import _redact_events_for, _HIDDEN_CARD
from network.codec import card_to_dict
from models.card import Card
from models.player import HumanPlayer
from constants import Suit
from core.game_manager import GameEvent
from network.event_codec import encode_event

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def run():
    drawer = HumanPlayer(name="Alice", player_id=0)
    other = HumanPlayer(name="Bob", player_id=1)
    real_card = Card(suit=Suit.SPADES, rank='K')  # a real, identifiable card

    # ── 'card_drawn': single-card voluntary draw ────────────────────────
    ev = encode_event(GameEvent('card_drawn', player=drawer, card=real_card))

    to_drawer = _redact_events_for([ev], recipient_id=0)
    check("drawer's own copy keeps the real card",
          to_drawer[0]['fields']['card'] == {'__card__': card_to_dict(real_card)})

    to_other = _redact_events_for([ev], recipient_id=1)
    check("a non-drawer's copy gets the placeholder card, not the real one",
          to_other[0]['fields']['card'] == _HIDDEN_CARD)
    check("redaction didn't mutate the shared encoded event in place "
          "(the drawer's later copy, or a retry, must still see the real card)",
          ev['fields']['card'] == {'__card__': card_to_dict(real_card)})

    # ── 'pickup_drawn': multi-card forced pickup ────────────────────────
    stack = [Card(suit=Suit.SPADES, rank='5'), Card(suit=Suit.LOVE, rank='5'), Card(suit=None, rank='Joker', is_red_joker=True)]
    ev2 = encode_event(GameEvent('pickup_drawn', player=drawer, cards=stack, count=len(stack)))

    to_drawer2 = _redact_events_for([ev2], recipient_id=0)
    check("drawer's own pickup keeps every real card, in order",
          to_drawer2[0]['fields']['cards'] == [{'__card__': card_to_dict(c)} for c in stack])

    to_other2 = _redact_events_for([ev2], recipient_id=1)
    check("a non-drawer sees the placeholder for every card in the pickup stack "
          "(count preserved, identities hidden)",
          to_other2[0]['fields']['cards'] == [_HIDDEN_CARD] * len(stack))
    check("'count' field (public — how many cards, not which) passes through untouched",
          to_other2[0]['fields']['count'] == len(stack))

    # ── Playing a card is what makes it public — must NOT be redacted ──
    ev3 = encode_event(GameEvent('cards_played', player=drawer, cards=[real_card],
                                  effect_text=None))
    to_other3 = _redact_events_for([ev3], recipient_id=1)
    check("'cards_played' is never redacted for anyone — playing a card "
          "is what makes it public in the first place",
          to_other3[0]['fields']['cards'] == [{'__card__': card_to_dict(real_card)}])

    ev4 = encode_event(GameEvent('jump_countered', player=drawer, card=real_card,
                                  cards=[real_card]))
    to_other4 = _redact_events_for([ev4], recipient_id=1)
    check("'jump_countered' is never redacted either, for the same reason",
          to_other4[0]['fields']['cards'] == [{'__card__': card_to_dict(real_card)}])

    # ── Unrelated event kinds pass straight through unexamined ─────────
    ev5 = encode_event(GameEvent('turn_changed', player=other))
    to_any = _redact_events_for([ev5], recipient_id=0)
    check("an event kind with no card field at all passes through untouched",
          to_any[0] == ev5)

    # ── A whole batch, mixed, addressed to the actual mover ────────────
    batch = _redact_events_for([ev, ev2, ev3], recipient_id=0)
    check("a mixed batch redacts only what's needed, leaving the recipient's "
          "own real draws intact alongside untouched play events",
          batch[0]['fields']['card'] == {'__card__': card_to_dict(real_card)}
          and batch[1]['fields']['cards'] == [{'__card__': card_to_dict(c)} for c in stack]
          and batch[2]['fields']['cards'] == [{'__card__': card_to_dict(real_card)}])


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"EVENT REDACTION: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("EVENT REDACTION: ALL CHECKS PASSED")
        sys.exit(0)
