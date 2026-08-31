"""
KADI - Card and Deck models
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional, List
from constants import Suit, RANKS, CardType, get_card_type, SUIT_SYMBOL, SUIT_LETTER, RANK_DISPLAY


@dataclass
class Card:
    suit: Optional[Suit]    # None for Jokers
    rank: str               # '2'-'9','A','J','Q','K','JOKER'
    card_type: CardType = field(init=False)
    is_red_joker: bool = False   # relevant only for Jokers

    def __post_init__(self):
        self.card_type = get_card_type(self.rank)

    # ── Display helpers ───────────────────────────────────────────────────────
    @property
    def display_rank(self) -> str:
        if self.rank == 'JOKER':
            return 'JKR'
        return RANK_DISPLAY.get(self.rank, self.rank)

    @property
    def display_suit(self) -> str:
        if self.suit is None:
            return '★'
        return SUIT_SYMBOL[self.suit]

    @property
    def suit_name(self) -> str:
        return self.suit.value if self.suit else 'Joker'

    @property
    def display_ascii(self) -> str:
        """Rank + suit using an ASCII letter (e.g. '9H') instead of the
        Unicode SUIT_SYMBOL glyph in display_suit/__repr__ — for the few
        places a card gets folded into a single plain-text on-screen
        message where compositing a vector suit icon isn't practical.
        Some fonts (this project's Poppins included) don't have the
        card-suit Unicode glyphs at all, which renders as a tofu box."""
        if self.rank == 'JOKER':
            return 'JKR'
        return f"{self.display_rank}{SUIT_LETTER[self.suit]}"

    def __repr__(self):
        if self.rank == 'JOKER':
            color = 'Red' if self.is_red_joker else 'Black'
            return f"{color} Joker"
        return f"{self.display_rank}{self.display_suit}"

    def __eq__(self, other):
        if not isinstance(other, Card):
            return False
        return self.rank == other.rank and self.suit == other.suit

    def __hash__(self):
        return hash((self.rank, self.suit))

    # ── Type shortcuts ────────────────────────────────────────────────────────
    @property
    def is_finishing(self) -> bool:
        return self.card_type == CardType.FINISHING

    @property
    def is_pickup(self) -> bool:
        return self.card_type in (CardType.PICKUP_2, CardType.PICKUP_3, CardType.JOKER)

    @property
    def is_special(self) -> bool:
        return self.card_type not in (CardType.FINISHING, CardType.STANDARD, CardType.QUESTION)

    @property
    def pickup_value(self) -> int:
        from constants import PICKUP_VALUES
        return PICKUP_VALUES.get(self.card_type, 0)


class Deck:
    def __init__(self, joker_count: int = 2):
        assert joker_count in (2, 4), "Joker count must be 2 or 4"
        self.joker_count = joker_count
        self._draw_pile: List[Card] = []
        self._discard_pile: List[Card] = []
        self.build()

    def build(self):
        self._draw_pile = []
        for suit in Suit:
            for rank in RANKS:
                self._draw_pile.append(Card(suit=suit, rank=rank))
        # Add jokers
        colors = [True, False] if self.joker_count == 2 else [True, True, False, False]
        for is_red in colors:
            self._draw_pile.append(Card(suit=None, rank='JOKER', is_red_joker=is_red))
        self._discard_pile = []

    def shuffle(self):
        random.shuffle(self._draw_pile)

    def deal(self, count: int = 1) -> List[Card]:
        drawn = []
        for _ in range(count):
            if not self._draw_pile:
                self._recycle_discard()
            if self._draw_pile:
                drawn.append(self._draw_pile.pop())
        return drawn

    def draw_one(self) -> Optional[Card]:
        cards = self.deal(1)
        return cards[0] if cards else None

    def _recycle_discard(self):
        """Reshuffle discard pile back into draw pile, keeping top card."""
        if len(self._discard_pile) <= 1:
            return
        top = self._discard_pile[-1]
        recycle = self._discard_pile[:-1]
        random.shuffle(recycle)
        self._draw_pile = recycle
        self._discard_pile = [top]

    def place_start_card(self) -> Card:
        """Draw cards until we get a valid starting card (4,5,6,7,9,10)."""
        valid_starts = {'4','5','6','7','9','10'}
        self.shuffle()
        attempts = 0
        while attempts < 200:
            card = self.draw_one()
            if card and card.rank in valid_starts:
                self._discard_pile.append(card)
                return card
            elif card:
                self._draw_pile.insert(0, card)
            attempts += 1
        # Fallback: force place
        for i, card in enumerate(self._draw_pile):
            if card.rank in valid_starts:
                self._draw_pile.pop(i)
                self._discard_pile.append(card)
                return card
        raise RuntimeError("Could not find a valid starting card")

    def discard(self, card: Card):
        self._discard_pile.append(card)

    def discard_many(self, cards: List[Card]):
        self._discard_pile.extend(cards)

    def undiscard(self, cards: List[Card]):
        """Remove specific cards back OUT of the discard pile — used
        when a Jump-bundle's non-Jump "extra" card is handed back to the
        player who played it because the Jump chain it rode along with
        got successfully countered (see GameManager._execute_jump_counter).
        Matches cards by identity, not the Card equality override (which
        compares only rank+suit and would risk pulling the wrong physical
        card if, say, both Jokers were on the pile)."""
        remove_ids = {id(c) for c in cards}
        self._discard_pile = [c for c in self._discard_pile if id(c) not in remove_ids]

    @property
    def top_card(self) -> Optional[Card]:
        return self._discard_pile[-1] if self._discard_pile else None

    @property
    def draw_count(self) -> int:
        return len(self._draw_pile)

    @property
    def discard_count(self) -> int:
        return len(self._discard_pile)

    @property
    def is_empty(self) -> bool:
        return len(self._draw_pile) == 0 and len(self._discard_pile) <= 1
