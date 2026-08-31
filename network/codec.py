"""
KADI - LAN networking: Card/Suit <-> JSON-safe dict codec.

Deliberately mirrors core/save_manager.py's `_card_to_dict` /
`_card_from_dict` format (suit as its enum .name, rank as the raw
string) so the same mental model applies whether state is going to
disk or over the wire. Kept as its own tiny module rather than
importing from save_manager, since save_manager is about local-disk
persistence and has no reason to depend on networking (or vice versa).
"""
from __future__ import annotations
from typing import List, Optional
from constants import Suit
from models.card import Card


def card_to_dict(card: Optional[Card]) -> Optional[dict]:
    if card is None:
        return None
    return {
        'suit': card.suit.name if card.suit else None,
        'rank': card.rank,
        'is_red_joker': card.is_red_joker,
    }


def card_from_dict(d: Optional[dict]) -> Optional[Card]:
    if d is None:
        return None
    suit = Suit[d['suit']] if d.get('suit') else None
    return Card(suit=suit, rank=d['rank'], is_red_joker=d.get('is_red_joker', False))


def cards_to_list(cards: List[Card]) -> List[dict]:
    return [card_to_dict(c) for c in cards]


def cards_from_list(data: List[dict]) -> List[Card]:
    return [card_from_dict(c) for c in data]


def suit_to_str(suit: Optional[Suit]) -> Optional[str]:
    return suit.name if suit else None


def suit_from_str(name: Optional[str]) -> Optional[Suit]:
    return Suit[name] if name else None
