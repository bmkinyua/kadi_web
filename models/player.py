"""
KADI - Player models
"""
from __future__ import annotations
import random
from collections import Counter
from typing import List, Optional, Tuple, Dict, TYPE_CHECKING
from models.card import Card
from constants import CardType, Suit, AIDifficulty, PICKUP_VALUES, DIFFICULTY_PROFILES
from core.game_logger import game_log
from core import decision_logger
from core import msomi_trainer


def _can_close_with(cards: List[Card], rule_engine: Optional['RuleEngine'] = None) -> bool:
    """Standalone version of Hand.can_declare_kadi that works on any
    plain list of cards (e.g. a hypothetical "remaining hand" the AI is
    evaluating, before it actually plays anything).

    With a rule_engine, delegates to RuleEngine.can_close_hand_with —
    the full grammar-aware check (same-rank finishing set, OR a
    Question/Kickback(even)/Jump chain answered by a same-rank finishing
    set, OR a lone ACE answered by any finishing cards). Without one,
    falls back to just the plain same-rank-finishing-set case, for any
    caller that genuinely has no RuleEngine on hand."""
    if not cards:
        return False
    if rule_engine is not None:
        return rule_engine.can_close_hand_with(cards)
    if not all(c.is_finishing for c in cards):
        return False
    if len(cards) == 1:
        return True
    return len(set(c.rank for c in cards)) == 1

if TYPE_CHECKING:
    from core.rule_engine import RuleEngine

# Neutral default used when scoring plays for a player with no AI
# difficulty profile of its own (a human) — MEDIUM's dials, purely so
# the logged score/feature set stays consistent in shape whether a
# decision came from a human or an AI. MSOMI training works from the
# raw named features regardless, not this particular score.
DEFAULT_EVAL_PROFILE = DIFFICULTY_PROFILES[AIDifficulty.MEDIUM]

_SEARCH_NODE_BUDGET = 20000  # generous safety valve for pathological hands


def compute_threats(opponents: Optional[List[dict]], threshold: int) -> List[dict]:
    """Opponents considered 'close to winning' right now: they've
    declared KADI, or are down to a hand size treated as dangerous.
    Purely based on publicly visible state (hand counts and
    declarations) — never hidden card knowledge. Standalone so both a
    human's and an AI's decisions can be evaluated the same way — see
    AIPlayer._threats, now a thin wrapper around this."""
    if not opponents:
        return []
    return [o for o in opponents
            if not o.get('finished')
            and (o.get('has_declared_kadi') or o.get('hand_count', 99) <= threshold)]


def opens_answer(card: Card, prev: Card, rule_engine: 'RuleEngine') -> bool:
    """Could `card` legally be the FIRST card of the answer section
    that ends a Q/K/J chain led by `prev`? Delegates the actual
    connection rule to RuleEngine._cards_connect so this never drifts
    out of sync with the real validator."""
    if not rule_engine._cards_connect(card, prev):
        return False
    return (card.is_finishing or card.is_pickup or card.rank == 'JOKER'
            or card.card_type in (CardType.JUMP, CardType.KICKBACK, CardType.SUIT_CHANGE))


def enumerate_legal_plays(hand_cards: List[Card], rule_engine: 'RuleEngine',
                          opponents: Optional[List[dict]] = None) -> List[List[Card]]:
    """Every distinct legal card sequence the engine will actually
    accept this turn, for a player holding `hand_cards` — the same
    checks GameManager._do_play makes (RuleEngine.is_playable on the
    opener, RuleEngine.is_valid_sequence on the whole sequence, the
    pending-pick-up "must end in a pick-up/Joker/ACE" rule, and the
    traditional Jump-bundle count rule — see RuleEngine.jump_bundle_legal)
    — found by exploring every branch the grammar in RuleEngine actually
    allows, not just the first matching card at each step.

    Standalone (not a method) so a HUMAN's options can be evaluated the
    same way an AI's are — see AIPlayer._enumerate_legal_plays, now a
    thin wrapper around this, and GameManager's human-decision logging,
    which is the actual reason this needed to stop being AI-only."""
    hand = list(hand_cards)
    n = len(hand)
    found: List[Tuple[List[Card], bool]] = []  # (sequence, fully_resolved)
    nodes = [0]
    active_count = 1 + sum(1 for o in (opponents or []) if not o.get('finished'))

    def resolves_pickup(seq_idx: List[int]) -> bool:
        if rule_engine.pickup_pending == 0:
            return True
        seq = [hand[i] for i in seq_idx]
        last = seq[-1]
        return (last.is_pickup or last.rank == 'JOKER'
                or (last.card_type == CardType.SUIT_CHANGE and rule_engine.ace_shields_pickup(seq)))

    def record(seq_idx: List[int]):
        seq = [hand[i] for i in seq_idx]
        ok, reason = rule_engine.is_valid_sequence(seq)
        if not ((ok or reason == "QUESTION_NO_ANSWER") and resolves_pickup(seq_idx)):
            return
        if not rule_engine.jump_bundle_legal(seq, active_count):
            return
        found.append((seq, ok))

    def candidate_indices(seq_idx: List[int], remaining_idx: List[int]) -> List[int]:
        first, last = hand[seq_idx[0]], hand[seq_idx[-1]]
        same_type_so_far = lambda t: all(hand[i].card_type == t for i in seq_idx)
        out: List[int] = []
        seen = set()

        def add(i):
            if i not in seen:
                seen.add(i)
                out.append(i)

        # Same-rank stacking is always structurally worth trying
        # next — is_valid_sequence accepts an all-same-rank set
        # unconditionally, regardless of card type.
        for i in remaining_idx:
            if hand[i].rank == last.rank:
                add(i)

        if first.card_type == CardType.QUESTION and same_type_so_far(CardType.QUESTION):
            for i in remaining_idx:
                c = hand[i]
                if c.card_type == CardType.QUESTION and c.suit == last.suit:
                    add(i)
                elif opens_answer(c, last, rule_engine):
                    add(i)
        elif first.card_type == CardType.KICKBACK and same_type_so_far(CardType.KICKBACK):
            for i in remaining_idx:
                c = hand[i]
                if c.card_type == CardType.KICKBACK:
                    add(i)
                elif opens_answer(c, last, rule_engine):
                    add(i)
        elif first.card_type == CardType.JUMP and same_type_so_far(CardType.JUMP):
            for i in remaining_idx:
                c = hand[i]
                if c.card_type == CardType.JUMP:
                    add(i)
                elif opens_answer(c, last, rule_engine):
                    add(i)
        elif first.is_pickup or first.rank == 'JOKER':
            # Pickup-mix rules (same rank always fine, Joker resets
            # the suit constraint, 2/3 need to share suit otherwise)
            # are only checked precisely at record()-time — here we
            # just offer every remaining pickup/Joker as a candidate.
            for i in remaining_idx:
                c = hand[i]
                if c.is_pickup or c.rank == 'JOKER':
                    add(i)
        elif first.card_type == CardType.SUIT_CHANGE or not first.is_finishing:
            # ACE-led (or any other non-finishing opener falling
            # through to "special + finishing"): only a finishing
            # card can ever extend it — see
            # RuleEngine._validate_special_then_finishing.
            for i in remaining_idx:
                if hand[i].is_finishing:
                    add(i)

        return out

    def extend(seq_idx: List[int], remaining_idx: List[int]):
        nodes[0] += 1
        if nodes[0] > _SEARCH_NODE_BUDGET:
            return
        record(seq_idx)
        for i in candidate_indices(seq_idx, remaining_idx):
            new_remaining = [j for j in remaining_idx if j != i]
            extend(seq_idx + [i], new_remaining)

    for i in range(n):
        if rule_engine.is_playable(hand[i]):
            remaining_idx = [j for j in range(n) if j != i]
            extend([i], remaining_idx)

    # Collapse equivalent-content orderings — the exact same
    # underlying cards, just played in a different order — into one
    # representative per unique card set. Order among otherwise-
    # interchangeable cards (e.g. which of three finishing cards
    # comes second vs third after an ACE) doesn't change anything
    # the scorer cares about, so without this an ACE + three
    # finishing cards would show up as up to 6 near-identical
    # "options" that are really the same play, padding option counts
    # and diluting the MSOMI log's ranking signal. The one thing
    # order genuinely CAN change is whether a Q/K/J chain ends up
    # fully resolved or only qualifies as an unanswered-question
    # play (see RuleEngine._validate_question_chain) — when both
    # show up for the same card set, keep the fully-resolved one.
    best: Dict[frozenset, Tuple[List[Card], bool]] = {}
    for seq, ok in found:
        key = frozenset(id(c) for c in seq)
        prev = best.get(key)
        if prev is None or (ok and not prev[1]):
            best[key] = (seq, ok)

    return [seq for seq, _ in best.values()]


def evaluate_play(hand_cards: List[Card], seq: List[Card], rule_engine: 'RuleEngine',
                   has_declared_kadi: bool, opponents: Optional[List[dict]] = None,
                   profile: Optional[dict] = None) -> dict:
    """Score one legal play and return a full, named feature
    breakdown alongside it — not just a number. This is exactly the
    kind of structured, per-decision training signal a future MSOMI
    policy needs: what was legally available, what each option's
    concrete properties were, and what actually got chosen.

    Standalone so a HUMAN's options can be scored the same way an AI's
    are — see AIPlayer._evaluate_play, now a thin wrapper around this
    using its own difficulty profile. Humans have no such profile, so
    callers evaluating a human's decision should pass profile=None,
    which falls back to DEFAULT_EVAL_PROFILE (MEDIUM's dials) — only
    the SCORE is profile-sensitive; every named feature is not."""
    profile = profile or DEFAULT_EVAL_PROFILE
    used_ids = {id(c) for c in seq}
    remaining = [c for c in hand_cards if id(c) not in used_ids]
    _, reason = rule_engine.is_valid_sequence(seq)
    unanswered_question = (reason == "QUESTION_NO_ANSWER")
    empties_hand = not remaining
    # Going cardless without a prior KADI declaration doesn't win —
    # GameManager._finish_play just makes the player draw a card
    # right back next turn — so it's never something to volunteer
    # for when a legal alternative avoids it.
    wastes_win = empties_hand and not has_declared_kadi
    leaves_kadi = _can_close_with(remaining, rule_engine)
    pickup_value = sum(PICKUP_VALUES.get(c.card_type, 0) for c in seq)
    has_suit_change = any(c.card_type == CardType.SUIT_CHANGE for c in seq)
    has_skip = any(c.card_type == CardType.JUMP for c in seq)
    has_kickback = any(c.card_type == CardType.KICKBACK for c in seq)
    has_question = any(c.card_type == CardType.QUESTION for c in seq)

    threats = compute_threats(opponents, profile['threat_hand_count'])
    next_is_threat = any(o.get('is_next') for o in threats)

    # Spending only part of a same-rank finishing cluster (e.g.
    # playing one 9 out of three) strands the rest, costing a
    # future shot at a single big same-rank KADI close-out.
    rank_counts = Counter(c.rank for c in hand_cards)
    stranded_cluster_cost = 0.0
    if seq and seq[0].is_finishing:
        cluster = rank_counts[seq[0].rank]
        played_of_rank = sum(1 for c in seq if c.rank == seq[0].rank)
        stranded_cluster_cost = max(0, cluster - played_of_rank) * profile['cluster_preservation']

    score = 0.0
    if wastes_win:
        score -= 1000.0
    elif leaves_kadi:
        score += 500.0 + len(seq) * 2
    elif unanswered_question:
        score -= 15.0
    else:
        score += len(seq) * 10.0

    score += pickup_value * 3
    score -= stranded_cluster_cost
    if has_suit_change:
        score += 8
    if has_question and not leaves_kadi:
        score += 5  # rich chain-starter even when it isn't the KADI move itself

    if next_is_threat:
        if pickup_value > 0:
            score += profile['disrupt_bonus'] * 2  # forces a draw AND voids their KADI
        if has_kickback:
            score += profile['disrupt_bonus'] // 2
        if has_skip:
            score += profile['disrupt_bonus']

    return {
        'cards': seq, 'score': score,
        'cards_played': len(seq), 'cards_remaining': len(remaining),
        'empties_hand': empties_hand, 'wastes_win': wastes_win,
        'leaves_kadi': leaves_kadi, 'unanswered_question': unanswered_question,
        'pickup_value_added': pickup_value, 'has_suit_change': has_suit_change,
        'has_skip': has_skip, 'has_kickback': has_kickback, 'has_question': has_question,
        'next_is_threat': next_is_threat, 'stranded_cluster_cost': stranded_cluster_cost,
    }


def evaluate_draw(hand_count: int) -> dict:
    """The one legal option enumerate_legal_plays can never surface on
    its own: voluntarily drawing instead of playing at all. The rules
    (see GameManager.human_draw / _do_draw) never require playing just
    because a legal play exists — a player can always draw instead,
    pending pick-up included (accepting the accumulated penalty rather
    than countering it). Scored as a small, fixed "lost tempo" cost:
    enough to lose to any ordinary decent play (which starts at +10 for
    a single harmless card), but enough to WIN against a play that's
    actively bad — most importantly a lone legal card that would empty
    the hand without a prior KADI declaration."""
    return {
        'cards': None, 'score': -2.0,
        'cards_played': 0, 'cards_remaining': hand_count,
        'empties_hand': False, 'wastes_win': False,
        'leaves_kadi': False, 'unanswered_question': False,
        'pickup_value_added': 0, 'has_suit_change': False,
        'has_skip': False, 'has_kickback': False, 'has_question': False,
        'next_is_threat': False, 'stranded_cluster_cost': 0.0,
    }


class Hand:
    def __init__(self):
        self._cards: List[Card] = []

    def add(self, cards: List[Card]):
        self._cards.extend(cards)

    def remove(self, cards: List[Card]):
        for card in cards:
            self._cards.remove(card)

    def remove_one(self, card: Card):
        self._cards.remove(card)

    def get_playable(self, rule_engine: 'RuleEngine') -> List[Card]:
        return [c for c in self._cards if rule_engine.is_playable(c)]

    @property
    def cards(self) -> List[Card]:
        return list(self._cards)

    @property
    def count(self) -> int:
        return len(self._cards)

    def is_empty(self) -> bool:
        return len(self._cards) == 0

    def has_only_finishing(self) -> bool:
        return all(c.is_finishing for c in self._cards)

    def has_finishing_card(self) -> bool:
        return any(c.is_finishing for c in self._cards)

    def can_declare_kadi(self, rule_engine: Optional['RuleEngine'] = None) -> bool:
        """
        A KADI declaration is only legitimate if this hand can be closed
        out in exactly ONE further legal move. With a rule_engine, that
        covers everything is_valid_kadi_finish itself would accept when
        you actually go to play it: a same-rank finishing set, a
        Question-chain/even-count-Kickback-run/Jump-run answered by a
        same-rank finishing set (suit integrity enforced throughout —
        see RuleEngine.can_close_hand_with), or a lone ACE answered by
        any finishing cards. Without a rule_engine, falls back to just
        the plain same-rank-finishing-set case.

        Anything that doesn't fit one of those shapes needs more than
        one future move to clear and so isn't a real KADI position yet,
        however "safe" those cards look — e.g. 2+ finishing cards of
        different ranks with nothing connecting them, like [10, 9].

        (This used to allow declaring with an arbitrarily large remaining
        hand as long as it wasn't ONLY non-finishing cards, which is what
        let the AI declare KADI while still holding two or three
        unrelated cards — a real bug, not a house-rule choice.)
        """
        if self.count == 0:
            return False
        return _can_close_with(self._cards, rule_engine)

    def __repr__(self):
        return f"Hand({self._cards})"


class Player:
    def __init__(self, name: str, player_id: int, is_human: bool = True):
        self.name = name
        self.player_id = player_id
        self.is_human = is_human
        self.hand = Hand()
        self.has_declared_kadi = False
        self.score = 0           # wins count
        self._seat_angle = 0.0   # for table positioning
        # Elimination Mode: True once this player has legitimately
        # finished (emptied their hand with a declared KADI) and is out
        # of the round. In standard mode this never gets set, since the
        # game ends outright at the first win.
        self.finished = False
        self.finish_place = None  # 1 = first out (best), etc. Set on finish.
        # True only if this player's connection was forcibly removed
        # for being unavailable too long (see
        # core.game_manager.GameManager.force_remove_player) -- distinct
        # from a normal `finished` (which always means "legitimately
        # emptied their hand"). Never set for AI seats.
        self.disconnected = False

    def draw_cards(self, deck, count: int = 1) -> List[Card]:
        cards = deck.deal(count)
        self.hand.add(cards)
        self.has_declared_kadi = False  # declaration void if forced to draw
        return cards

    def play_cards(self, cards: List[Card], deck):
        self.hand.remove(cards)
        deck.discard_many(cards)

    def reset_kadi(self):
        self.has_declared_kadi = False

    def __repr__(self):
        return f"Player({self.name}, {self.hand.count} cards)"


class HumanPlayer(Player):
    def __init__(self, name: str, player_id: int):
        super().__init__(name, player_id, is_human=True)


class AIPlayer(Player):
    def __init__(self, name: str, player_id: int, difficulty: AIDifficulty = AIDifficulty.MEDIUM):
        super().__init__(name, player_id, is_human=False)
        self.difficulty = difficulty
        self.profile = DIFFICULTY_PROFILES[difficulty]
        self._think_timer = 0.0
        self._think_duration = self._get_think_time()
        self._chosen_action = None   # set by decide(), consumed by game_manager
        self._chosen_suit = None
        # Optional MSOMI model dict (see core/msomi_trainer), attached
        # via the MSOMI settings' "attach a model" flow. Orthogonal to
        # difficulty per the original spec — combinable with EASY/
        # MEDIUM/HARD, not a 4th difficulty tier: when set, it replaces
        # _evaluate_play's hand-tuned score with the model's learned
        # one, while the difficulty's own optimal_play_chance still
        # governs how often the top-scored option actually gets played.
        self.msomi_model: Optional[dict] = None

    def _get_think_time(self) -> float:
        return {
            AIDifficulty.EASY:   random.uniform(0.8, 1.5),
            AIDifficulty.MEDIUM: random.uniform(0.5, 1.0),
            AIDifficulty.HARD:   random.uniform(0.3, 0.7),
        }[self.difficulty]

    def start_thinking(self):
        import random as r
        self._think_timer = 0.0
        self._think_duration = self._get_think_time()
        self._chosen_action = None
        self._chosen_suit = None

    def update_thinking(self, dt: float) -> bool:
        """Returns True when decision is ready."""
        self._think_timer += dt
        return self._think_timer >= self._think_duration

    def decide(self, rule_engine: 'RuleEngine', deck, opponents: Optional[List[dict]] = None) -> dict:
        """
        Returns action dict:
          {'type': 'play', 'cards': [...], 'suit': Suit|None, 'declare_kadi': bool}
          {'type': 'draw'}

        `opponents` is an optional list of dicts describing what's
        publicly known about the other players right now (hand_count,
        has_declared_kadi, finished, is_next, likely_suit) — see
        GameManager._opponent_context(). It never reveals hidden hand
        contents; it only lets higher difficulties play more purposefully
        (disrupting a player who's about to win, steering a suit change
        away from what a threat likely needs) instead of playing blind.
        Passing nothing preserves the old, opponent-unaware behaviour.

        The decision itself is a full exhaustive search (see
        _enumerate_legal_plays): every legal sequence actually reachable
        from this hand right now — mid a pending pick-up or a normal
        turn alike — is enumerated and scored (_evaluate_play), and
        difficulty only changes how likely this player is to actually
        take the top-scoring option (profile['optimal_play_chance'])
        versus a random legal alternative. One search, one scorer, one
        selection rule at every difficulty, instead of three separate
        hand-built heuristics.
        """
        # When KADI is already declared, the ONLY legal next play is
        # normally a valid finishing card (see RuleEngine.is_valid_kadi_finish)
        # — a distinct, narrow rule from ordinary play, not a strategic
        # choice, so it's handled directly rather than through the
        # general search. EXCEPT: an active pick-up chain overrides this
        # too, same as it overrides everything else — GameManager._do_play
        # checks pickup_pending before it ever checks has_declared_kadi,
        # so a declared player facing a pending pick-up must resolve THAT
        # first via a normal pickup/Joker/ACE-shield play, not a finishing
        # card (the two are mutually exclusive last-card types, so trying
        # a finish here would just get rejected and waste the turn).
        if self.has_declared_kadi and rule_engine.pickup_pending == 0:
            # Try the whole remaining hand as one closing combo first —
            # e.g. a declared [Q♦, Q♥, 6♦, 6♥] should actually get played
            # as that one Q-chain-then-6s move and win outright, not
            # trickle out as lone finishing cards over several turns
            # because only single cards were ever considered here.
            active_count = 1 + sum(1 for o in (opponents or []) if not o.get('finished'))
            whole_hand_order = rule_engine.order_for_closing(
                self.hand.cards, prefer_playable_now=True, active_player_count=active_count)
            if whole_hand_order is not None and rule_engine.is_valid_kadi_finish(whole_hand_order):
                return {'type': 'play', 'cards': whole_hand_order, 'suit': None, 'declare_kadi': False}

            playable = self.hand.get_playable(rule_engine)
            finishing_playable = [c for c in playable
                                  if rule_engine.is_valid_kadi_finish([c])]
            if not finishing_playable:
                return {'type': 'draw'}
            card = self._pick_best_finishing(finishing_playable)
            cards = self._build_finishing_set(card)
            return {'type': 'play', 'cards': cards, 'suit': None, 'declare_kadi': False}

        options = self._enumerate_legal_plays(rule_engine, opponents)
        if not options:
            return {'type': 'draw'}

        cards = self._choose_play(options, rule_engine, opponents)
        if cards is None:
            return {'type': 'draw'}
        suit = self._pick_suit(cards, opponents) if any(c.card_type == CardType.SUIT_CHANGE for c in cards) else None
        declare_kadi = self._should_declare_kadi(cards, rule_engine)
        return {'type': 'play', 'cards': cards, 'suit': suit, 'declare_kadi': declare_kadi}

    def _pick_best_finishing(self, finishing: List[Card]) -> Card:
        """Pick highest-count finishing card (to play sets)."""
        rank_counts = {}
        for c in self.hand.cards:
            if c.is_finishing:
                rank_counts[c.rank] = rank_counts.get(c.rank, 0) + 1
        return max(finishing, key=lambda c: rank_counts.get(c.rank, 0))

    def _build_finishing_set(self, card: Card) -> List[Card]:
        """Build a set of same-rank finishing cards. `card` has already
        been validated (it came from finishing_playable, checked against
        is_valid_kadi_finish), so it MUST lead the returned list — the
        engine only re-checks is_playable on cards[0], and hand order is
        otherwise arbitrary, so blindly rebuilding "same rank" straight
        from hand order could put an unvalidated card first and get the
        whole legal play rejected."""
        same = [c for c in self.hand.cards if c.rank == card.rank and c.is_finishing and c != card]
        return [card] + same

    def decide_counter(self, rule_engine: 'RuleEngine') -> Optional[Card]:
        """Return a J card to counter a pending J (Jump) play, or None.

        J is the only card that can counter a J — there is no other
        counter mechanic in the game. Aggression scales with difficulty
        via profile['counter_aggression']."""
        counters = [c for c in self.hand.cards if c.card_type == CardType.JUMP]
        if not counters:
            return None
        if random.random() < self.profile['counter_aggression']:
            return random.choice(counters)
        return None

    def _threats(self, opponents: Optional[List[dict]]) -> List[dict]:
        """Thin wrapper around the standalone compute_threats — see its
        docstring. Kept as a method since it needs this AI's own
        difficulty profile for the hand-size threshold."""
        return compute_threats(opponents, self.profile['threat_hand_count'])

    def _remaining_after(self, seq: List[Card]) -> List[Card]:
        """Cards left in hand after playing `seq`, matched by object
        identity rather than the Card equality override (which compares
        only rank+suit and would treat the two Jokers, both suit=None
        rank='JOKER', as interchangeable)."""
        used_ids = {id(c) for c in seq}
        return [c for c in self.hand.cards if id(c) not in used_ids]

    def _enumerate_legal_plays(self, rule_engine: 'RuleEngine',
                               opponents: Optional[List[dict]] = None) -> List[List[Card]]:
        """Thin wrapper around the standalone enumerate_legal_plays —
        see its docstring. Kept as a method for backward-compatible call
        sites within AIPlayer."""
        return enumerate_legal_plays(self.hand.cards, rule_engine, opponents)

    def _evaluate_play(self, seq: List[Card], rule_engine: 'RuleEngine',
                        opponents: Optional[List[dict]] = None) -> dict:
        """Thin wrapper around the standalone evaluate_play — see its
        docstring. Kept as a method since it needs this AI's own
        difficulty profile and has_declared_kadi state. When an MSOMI
        model is attached (see __init__), its learned score replaces
        the hand-tuned one here — every OTHER named feature is computed
        identically either way, since those come straight from the game
        state, not from either scoring approach."""
        ev = evaluate_play(self.hand.cards, seq, rule_engine, self.has_declared_kadi,
                           opponents, self.profile)
        if self.msomi_model is not None:
            ev['score'] = msomi_trainer.score_option(self.msomi_model, ev)
        return ev

    def _evaluate_draw(self) -> dict:
        """Thin wrapper around the standalone evaluate_draw — see
        _evaluate_play's docstring re: MSOMI model substitution."""
        ev = evaluate_draw(self.hand.count)
        if self.msomi_model is not None:
            ev['score'] = msomi_trainer.score_option(self.msomi_model, ev)
        return ev

    def _choose_play(self, options: List[List[Card]], rule_engine: 'RuleEngine',
                      opponents: Optional[List[dict]] = None) -> Optional[List[Card]]:
        profile = self.profile
        threats = self._threats(opponents)
        next_is_threat = any(o.get('is_next') for o in threats)
        heads_up = (opponents is not None and len(opponents) == 1)

        # "Kuficha Joker" hold-back (see DIFFICULTY_PROFILES['hoard_pickup']):
        # heads-up only, while a legal non-pickup alternative exists and
        # nobody's about to win, sometimes withhold an available
        # pickup/Joker instead of reflexively dumping it, so it survives
        # to be sprung later. Once down to exactly [pickup/Joker,
        # finishing card] the trap is set and this stops holding back —
        # _evaluate_play's leaves_kadi/wastes_win scoring already makes
        # the pickup-first play win from there on its own.
        pool = options
        trap_ready = (
            heads_up and self.hand.count == 2
            and any(c.is_finishing for c in self.hand.cards)
            and any((c.is_pickup or c.rank == 'JOKER') for c in self.hand.cards)
        )
        if (heads_up and profile['hoard_pickup'] > 0 and not trap_ready
                and not next_is_threat and random.random() < profile['hoard_pickup']):
            non_pickup = [seq for seq in pool if not any(c.is_pickup or c.rank == 'JOKER' for c in seq)]
            if non_pickup:
                pool = non_pickup

        evaluated = [self._evaluate_play(seq, rule_engine, opponents) for seq in pool]
        evaluated.append(self._evaluate_draw())
        evaluated.sort(key=lambda ev: ev['score'], reverse=True)

        # Every difficulty runs the exact same search-and-score pipeline
        # above; the ONLY difference between EASY, MEDIUM, and HARD is
        # how likely this player is to actually take the top-scoring
        # option versus a random legal one — see
        # DIFFICULTY_PROFILES['optimal_play_chance']. HARD sits close to
        # 1.0 (plays what it finds is objectively best almost every
        # time); EASY is low enough that it visibly makes real mistakes,
        # including occasionally the self-defeating ones (going cardless
        # without KADI, missing an open KADI) a genuine beginner would
        # make.
        chosen = evaluated[0] if random.random() < profile['optimal_play_chance'] else random.choice(evaluated)

        self._log_decision(evaluated, chosen, rule_engine)
        return chosen['cards']

    def _log_decision(self, evaluated: List[dict], chosen: dict, rule_engine: 'RuleEngine'):
        """Log the FULL ranked option set this turn, not just the move
        made — every option's cards and score, which one was picked, and
        how far down the ranking that was. The text-log line here stays
        a readable top-6 summary; the actual full-fidelity training
        data (every option, every field) goes to the JSONL sidecar via
        decision_logger — see its module docstring."""
        chosen_rank = evaluated.index(chosen)
        fmt = lambda cards: [str(c) for c in cards] if cards is not None else 'DRAW'
        top = ", ".join(f"{fmt(ev['cards'])}={ev['score']:.0f}" for ev in evaluated[:6])
        game_log.debug(
            f"{self.name} MSOMI difficulty={self.difficulty.name} "
            f"options={len(evaluated)} chosen_rank={chosen_rank}/{len(evaluated)} "
            f"chosen={fmt(chosen['cards'])} score={chosen['score']:.0f} "
            f"leaves_kadi={chosen['leaves_kadi']} wastes_win={chosen['wastes_win']} "
            f"top6=[{top}]")
        decision_logger.log_decision(
            is_human=False, player_name=self.name, difficulty=self.difficulty.name,
            hand_before=self.hand.cards, evaluated=evaluated, chosen=chosen,
            declared_kadi=self.has_declared_kadi, pickup_pending=rule_engine.pickup_pending,
            top_card=rule_engine._top_card)

    def _pick_suit(self, cards: List[Card], opponents: Optional[List[dict]] = None) -> Suit:
        """Pick the suit to switch to after playing an ACE (or a shield).

        If this play bundles the ACE together with other cards (e.g. an
        ACE+finishing sequence found by the exhaustive search), the suit declared
        MUST match the LAST card in that combo — the engine always makes
        cards[-1] the new visible top card (see RuleEngine.process_play),
        so declaring anything else would show a "current suit" badge
        that visibly contradicts the top card just played. (There was a
        real bug here: the engine used to let the ACE's declared suit
        stick even when a later, different-suited card ended the combo —
        fixed in RuleEngine.process_play. This mirrors that fix so the
        AI's own suit choice isn't wasted on a combo where it would be
        overridden anyway.) Coherency wins over strategy here — there's
        no real choice left once these specific cards are locked in.

        If instead this is a LONE ACE that leaves exactly one finishing
        card behind — a KADI declare — the honest move is requesting
        that last card's own suit, so it's automatically playable next
        turn. But that also telegraphs exactly what's needed, and any
        opponent paying attention will reasonably try to steer the suit
        away from it. "Bluff calling" (see
        DIFFICULTY_PROFILES['bluff_suit_request']): sometimes request a
        decoy suit instead, gambling that opponents trying to block the
        "obvious" suit switch to the real one by mistake. Genuinely
        risky — if nobody takes the bait the AI is stuck needing rank
        luck instead — so it's a probability, not a guaranteed move.

        Otherwise (a lone ACE / shield with no KADI in play), base
        preference is the suit we hold the most of. At higher
        difficulty, if a threatening opponent (KADI declared, or very
        low on cards) has a clear suit "signature" from their own public
        play history, steer away from that suit instead — denying them
        the suit their last few plays suggest they need — as long as
        there's still another suit of our own worth switching to.
        """
        accompanying = [c for c in cards if c.card_type != CardType.SUIT_CHANGE]
        if accompanying and accompanying[-1].suit:
            return accompanying[-1].suit

        remaining_after = [c for c in self.hand.cards if c not in cards]
        if len(remaining_after) == 1 and remaining_after[0].is_finishing and remaining_after[0].suit:
            honest_suit = remaining_after[0].suit
            bluff_chance = self.profile.get('bluff_suit_request', 0)
            if bluff_chance and random.random() < bluff_chance:
                decoys = [s for s in Suit if s != honest_suit]
                if decoys:
                    return random.choice(decoys)
            return honest_suit

        suit_counts = {}
        for c in self.hand.cards:
            if c.suit:
                suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
        if not suit_counts:
            return random.choice(list(Suit))

        ranked = sorted(suit_counts, key=suit_counts.get, reverse=True)
        best = ranked[0]

        threats = self._threats(opponents)
        if not threats or random.random() >= self.profile['block_awareness']:
            return best

        danger_suits = {o['likely_suit'] for o in threats if o.get('likely_suit')}
        if not danger_suits:
            return best

        for suit in ranked:
            if suit not in danger_suits:
                return suit
        return best  # every suit we hold looks dangerous — no safe pivot

    def _should_declare_kadi(self, played_cards: List[Card], rule_engine: 'RuleEngine') -> bool:
        """Only declare if the remaining hand is actually closeable in
        one further move — mirrors the authoritative rule in
        Hand.can_declare_kadi (via the shared _can_close_with helper) so
        the AI never declares a position the game would be wrong to
        accept."""
        return _can_close_with(self._remaining_after(played_cards), rule_engine)
