"""
KADI Rule Engine v4
- Suit integrity enforced for ALL special cards (Q/8/J/K) matching top card
- Only Joker bypasses suit check
- ACE suit integrity configurable
- Pickup chain: no hard cap, Joker bypasses suit, 2+3 need suit match
- Q without answer = QUESTION_NO_ANSWER signal (player draws 1)
- process_play correctly handles ACE suit-change in combo plays
- K-return with any valid answer type
"""
from __future__ import annotations
from typing import List, Optional, Tuple
from models.card import Card
from constants import CardType, Suit, PICKUP_VALUES
from core.game_logger import game_log


class RuleEngine:

    def __init__(self):
        self.current_suit: Optional[Suit] = None
        self.pickup_pending: int = 0
        self.pickup_rank: Optional[str] = None
        self.pickup_suit: Optional[Suit] = None
        self._top_card: Optional[Card] = None
        self.skip_count: int = 0
        self.joker_on_top: bool = False
        # If True, ACE card must also match suit to be played
        self.ace_suit_integrity: bool = False
        # Which combos are allowed to shield (fully cancel) an active
        # pick-up chain via a bundled ACE — see process_play/_process_single.
        # True (default): an ACE anywhere in the play shields, including
        # after a Question or Kickback chain (e.g. [Q♦, A♦] cancelling a
        # pending pick-up). False: only a genuinely solo/ACE-led play
        # can shield — a Question or Kickback chain ending in an ACE no
        # longer does. Jump-led combos are EXCLUDED from shielding
        # either way (see _ace_shield_allowed) — not offered as a
        # toggle option at all.
        self.pickup_shield_qk_allowed: bool = True

        # Master on/off for the "ACE + finishing cards" multi-card KADI
        # shape (see order_for_closing's SUIT_CHANGE branch) — quite a
        # different kind of mechanic from the Q/K/J chains (a wildcard
        # connector, not a suit-integrity chain), kept separately
        # toggleable for that reason. Doesn't affect ACE's ordinary
        # single-card uses (shield, suit-request), nor the simple "solo
        # ACE now, declare holding your last finishing card" shortcut,
        # which never goes through this shape at all.
        self.ace_finisher_enabled: bool = True

        # Master on/off for bundling a non-Jump "extra" card behind a
        # Jump chain at all (e.g. [J♦, J♣, 2♣]) — see jump_bundle_legal
        # for the traditional count rule this is subject to when on, and
        # GameManager._execute_jump_counter for what happens to the
        # bundled card if the chain gets interrupted by a counter.
        self.jump_multi_card_enabled: bool = True

    def jump_bundle_legal(self, cards: List[Card], active_player_count: int) -> bool:
        """Traditional rule for bundling a non-Jump "extra" card behind
        a Jump chain, e.g. [J♦, J♣, 2♣] (two Jumps answered by a
        pick-up card) or [J♦, 7♦] (one Jump answered by a finishing
        card). Playing the Jumps alone is unrestricted — the caution
        here is specifically about revealing an extra card alongside
        them.

        The traditional way to play this: the Jump count must exactly
        equal (active players - 1) — enough to clear every other player
        and land the turn straight back on you, IF the chain survives
        uncountered, before the extra card would ever matter. That's
        what makes it safe to lead with: nobody learns what the extra
        card is unless the Jumps actually come all the way back around.
        If a counter interrupts the chain first, the extra card is
        handed back to you unplayed and the game continues with just
        the Jumps that were actually answered — see
        GameManager._execute_jump_counter.

        Bundling anything other than that exact count is illegal, not
        just inadvisable — with 6 players for example this is hard to
        pull off outside Elimination Mode gradually thinning the table
        down to a number where you can actually hold enough Jumps.
        """
        j_count = 0
        for c in cards:
            if c.card_type == CardType.JUMP:
                j_count += 1
            else:
                break
        if j_count == 0 or j_count == len(cards):
            return True  # pure Jump stack, no bundled extra card — unrestricted
        if not self.jump_multi_card_enabled:
            return False
        return j_count == active_player_count - 1

    def _combo_leading_type(self, cards: List[Card]):
        """The chain type leading this whole play, if any — Q/K/J if the
        play opens with a run of that type, else the type of cards[0]
        itself (e.g. SUIT_CHANGE for a lone/leading ACE). Used to decide
        whether a bundled ACE is allowed to shield a pending pick-up —
        see pickup_shield_mode."""
        return cards[0].card_type if cards else None

    def _ace_shield_allowed(self, leading_type) -> bool:
        """Whether an ACE ending a combo with this leading type is
        allowed to shield a pending pick-up — NEVER for a Jump-led combo
        regardless of setting (see pickup_shield_qk_allowed's docstring
        for why); a solo/ACE-led play always may; a Question- or
        Kickback-led chain only when pickup_shield_qk_allowed is True."""
        if leading_type == CardType.JUMP:
            return False
        if leading_type == CardType.SUIT_CHANGE:
            return True
        return self.pickup_shield_qk_allowed

    def ace_shields_pickup(self, cards: List[Card]) -> bool:
        """Would playing this exact combo, right now, shield (fully
        cancel) a pending pick-up via a bundled ACE? This is the single
        source of truth for both (a) whether an ACE-ending combo counts
        as a legal response to a pending pick-up at all, and (b) the
        actual effect process_play applies — kept as one function so
        those two checks can never drift apart (a combo that's accepted
        as "resolving" the pick-up must actually resolve it)."""
        if (self.pickup_pending == 0 or not cards
                or cards[-1].card_type != CardType.SUIT_CHANGE):
            return False
        return self._ace_shield_allowed(self._combo_leading_type(cards))

    def set_top_card(self, card: Card, declared_suit: Optional[Suit] = None):
        self._top_card = card
        self.joker_on_top = (card.rank == 'JOKER')
        if declared_suit:
            self.current_suit = declared_suit
        elif card.suit:
            self.current_suit = card.suit

    # ─── Single-card playability ──────────────────────────────────────────────

    def is_playable(self, card: Card) -> bool:
        top = self._top_card
        if top is None:
            return True

        # Joker on top with no pending pickup → any card playable
        if self.joker_on_top and self.pickup_pending == 0:
            return True

        # During pickup chain: only counter cards
        if self.pickup_pending > 0:
            return self._can_counter_pickup(card)

        # Joker always playable
        if card.rank == 'JOKER':
            return True

        # ACE: playable if suit integrity off OR matches suit/rank
        if card.card_type == CardType.SUIT_CHANGE:
            if not self.ace_suit_integrity:
                return True
            return card.suit == self.current_suit or (top and card.rank == top.rank)

        # Special cards (Q/8/J/K) — MUST match suit OR same rank
        if card.card_type in (CardType.QUESTION, CardType.KICKBACK, CardType.JUMP):
            if card.suit == self.current_suit:
                return True
            if top and card.rank == top.rank:
                return True
            return False

        # Finishing / pickup standard: match suit or rank
        if card.suit == self.current_suit:
            return True
        if top and card.rank == top.rank:
            return True

        return False

    def _can_counter_pickup(self, card: Card) -> bool:
        """Cards that can counter an active pickup chain."""
        # ACE shields — suit integrity only enforced if ace_suit_integrity setting is on
        if card.card_type == CardType.SUIT_CHANGE:
            if not self.ace_suit_integrity:
                return True   # setting off — ACE always shields, no suit check
            if self.pickup_suit is None:
                return True   # Joker-led chain — ACE blocks freely regardless of setting
            return card.suit == self.pickup_suit
        # Joker always counters (no suit integrity ever)
        if card.rank == 'JOKER':
            return True
        # Question cards can precede a counter
        if card.card_type == CardType.QUESTION:
            return True
        if not card.is_pickup:
            return False
        top = self._top_card
        # Same rank any suit
        if top and card.rank == top.rank:
            return True
        # After Joker (no suit): any pickup counters
        if self.pickup_suit is None:
            return True
        # Same suit as chain start
        if card.suit == self.pickup_suit:
            return True
        return False

    # ─── Multi-card sequence validation ──────────────────────────────────────

    def is_valid_sequence(self, cards: List[Card]) -> Tuple[bool, str]:
        """
        Validate a multi-card play.
        Returns (valid, reason).
        """
        n = len(cards)
        if n == 0:
            return False, "No cards"
        if n == 1:
            return True, ""

        # All same rank → always valid set
        if len(set(c.rank for c in cards)) == 1:
            return True, ""

        first = cards[0]

        # ── Question chain ──────────────────────────────────────────────
        if first.card_type == CardType.QUESTION:
            return self._validate_question_chain(cards)

        # ── Pure pickup mix ─────────────────────────────────────────────
        if first.is_pickup or first.rank == 'JOKER':
            if all(c.is_pickup or c.rank == 'JOKER' for c in cards):
                return self._validate_pickup_mix(cards)

        # ── K sequence (with or without answer) ─────────────────────────
        if first.card_type == CardType.KICKBACK:
            return self._validate_k_sequence(cards)

        # ── J sequence (with or without answer) ─────────────────────────
        if first.card_type == CardType.JUMP:
            return self._validate_j_sequence(cards)

        # ── ACE + finishing ─────────────────────────────────────────────
        if first.card_type == CardType.SUIT_CHANGE:
            return self._validate_special_then_finishing(cards)

        # ── Special + finishing (fallback) ──────────────────────────────
        return self._validate_special_then_finishing(cards)

    # ── Question chain ─────────────────────────────────────────────────────

    def _validate_question_chain(self, cards: List[Card]) -> Tuple[bool, str]:
        """
        Q/8 cards link by suit OR rank.
        Must be followed by an answer (finishing/pickup/J/K/ACE).
        No answer = QUESTION_NO_ANSWER (valid play, draw 1 penalty).
        """
        q_end = 0
        for i, c in enumerate(cards):
            if c.card_type == CardType.QUESTION:
                q_end = i + 1
            else:
                break

        q_section   = cards[:q_end]
        ans_section = cards[q_end:]

        # Q chain integrity: consecutive Qs must link by suit or rank
        for i in range(1, len(q_section)):
            prev = q_section[i-1]
            curr = q_section[i]
            if curr.suit != prev.suit and curr.rank != prev.rank:
                # ASCII-only — U+2192 (→) isn't in any of this project's
                # bundled fonts and rendered as a tofu box when this
                # reason string reached the "Invalid: ..." toast.
                return False, f"Q chain broken: {prev} to {curr} (need same suit or rank)"

        # No answer — valid play but penalty applies
        if not ans_section:
            return True, "QUESTION_NO_ANSWER"

        last_q = q_section[-1]
        first_ans = ans_section[0]

        # Answer must connect to last Q
        if not self._cards_connect(first_ans, last_q):
            return False, f"Answer {first_ans} doesn't connect to {last_q}"

        return self._validate_answer(ans_section, last_q)

    # ── K sequence ─────────────────────────────────────────────────────────

    def _validate_k_sequence(self, cards: List[Card]) -> Tuple[bool, str]:
        """K cards (any count), optionally followed by an answer — but
        ONLY an even K count may carry one. House rule: a single (or any
        odd count) K is a standalone reversal — it hands control on to
        the next player in the new direction immediately, so nothing
        may be bundled after it in the same play. An even K count
        cancels the reversal and returns the turn to the same player,
        who may freely bundle any valid answer onto the same play.
        """
        k_end = 0
        for i, c in enumerate(cards):
            if c.card_type == CardType.KICKBACK:
                k_end = i + 1
            else:
                break

        k_section   = cards[:k_end]
        ans_section = cards[k_end:]

        if not ans_section:
            return True, ""   # pure K stack always valid

        k_count   = len(k_section)
        k_return  = (k_count % 2 == 0)   # even = returns to player
        last_k    = k_section[-1]

        # Odd K count = reversal to the next player — that reversal is
        # this play's complete effect. No trailing card may be bundled
        # onto it; the K(s) must be played alone.
        if not k_return:
            return False, (f"Odd K count ({k_count}) must be played alone — "
                            f"no trailing card allowed after a reversal")

        # Even K (returns to player): any valid answer is allowed freely
        return self._validate_answer(ans_section, last_k)

    # ── J sequence ─────────────────────────────────────────────────────────

    def _validate_j_sequence(self, cards: List[Card]) -> Tuple[bool, str]:
        """J cards optionally followed by any valid answer."""
        j_end = 0
        for i, c in enumerate(cards):
            if c.card_type == CardType.JUMP:
                j_end = i + 1
            else:
                break

        j_section   = cards[:j_end]
        ans_section = cards[j_end:]

        if not ans_section:
            return True, ""   # pure J chain

        last_j    = j_section[-1]
        first_ans = ans_section[0]

        if not self._cards_connect(first_ans, last_j):
            return False, f"Answer {first_ans} doesn't connect to J {last_j}"

        return self._validate_answer(ans_section, last_j)

    # ── Answer validation ───────────────────────────────────────────────────

    def _validate_answer(self, ans: List[Card], prev: Card) -> Tuple[bool, str]:
        """Validate the answer section of a Q/J/K chain."""
        if not ans:
            return False, "No answer"
        first = ans[0]

        # Finishing cards (same rank set)
        if first.is_finishing:
            if not all(c.is_finishing for c in ans):
                return False, "Mixed finishing/non-finishing in answer"
            if len(set(c.rank for c in ans)) > 1:
                return False, "Finishing answer must be same rank"
            return True, ""

        # Pickup mix
        if first.is_pickup or first.rank == 'JOKER':
            if all(c.is_pickup or c.rank == 'JOKER' for c in ans):
                return self._validate_pickup_mix(ans)
            return False, "Pickup answer must only contain pickup cards"

        # Pure J chain answer
        if first.card_type == CardType.JUMP:
            if all(c.card_type == CardType.JUMP for c in ans):
                return True, ""
            return False, "J answer must be all J cards"

        # Pure K chain answer
        if first.card_type == CardType.KICKBACK:
            if all(c.card_type == CardType.KICKBACK for c in ans):
                return True, ""
            return False, "K answer must be all K cards"

        # Single ACE answer (suit change)
        if first.card_type == CardType.SUIT_CHANGE:
            if len(ans) == 1:
                return True, ""
            return False, "Only one ACE allowed as answer"

        return False, f"Invalid answer card: {first}"

    # ── Connection check ────────────────────────────────────────────────────

    def _cards_connect(self, card: Card, prev: Card) -> bool:
        """Two consecutive cards in a sequence connect by suit or rank."""
        if card.rank == 'JOKER':
            return True   # Joker connects to anything
        if card.card_type == CardType.SUIT_CHANGE:
            return True   # ACE connects to anything as answer
        if card.suit == prev.suit:
            return True
        if card.rank == prev.rank:
            return True
        return False

    # ── Pickup mix ──────────────────────────────────────────────────────────

    def _validate_pickup_mix(self, cards: List[Card]) -> Tuple[bool, str]:
        """
        Pickup mixing rules (NO hard cap):
        - All same rank: always ok
        - Joker: no suit check, connects to anything
        - 2+3 or 3+2: must share suit with previous non-Joker card
        """
        if len(cards) == 1:
            return True, ""
        if len(set(c.rank for c in cards)) == 1:
            return True, ""

        # Walk through chain checking suit integrity
        last_suit = None   # suit of last non-Joker card
        for i, card in enumerate(cards):
            if card.rank == 'JOKER':
                # Joker resets — no suit required for next card
                last_suit = None
                continue
            if last_suit is None:
                # After Joker or first card: no constraint
                last_suit = card.suit
            else:
                prev = cards[i-1]
                prev_suit = None
                # Find last non-Joker suit
                for j in range(i-1, -1, -1):
                    if cards[j].rank != 'JOKER':
                        prev_suit = cards[j].suit
                        break
                if prev_suit is not None and card.rank != cards[i-1].rank:
                    # Different rank + different suit = invalid
                    if card.suit != prev_suit:
                        return False, f"{cards[i-1]}+{card}: different rank needs same suit"
                last_suit = card.suit

        return True, ""

    # ── Special + finishing ─────────────────────────────────────────────────

    def _validate_special_then_finishing(self, cards: List[Card]) -> Tuple[bool, str]:
        """Special cards (non-finishing) followed by finishing cards."""
        finishing_start = None
        for i, c in enumerate(cards):
            if c.is_finishing:
                finishing_start = i
                break
        if finishing_start is None:
            return False, "No finishing card found in sequence"
        for c in cards[finishing_start:]:
            if not c.is_finishing:
                return False, "Non-finishing card after finishing cards"
        return True, ""

    # ─── Process play ─────────────────────────────────────────────────────

    def process_play(self, cards: List[Card], declared_suit: Optional[Suit] = None) -> dict:
        game_log.debug(f"process_play cards={cards} declared_suit={declared_suit} "
                        f"pickup_pending(before)={self.pickup_pending} "
                        f"pickup_suit(before)={self.pickup_suit}")
        result = {
            'pickup_total':    0,
            'skip':            False,
            'skip_count':      0,
            'reverse':         False,
            'reverse_count':   0,
            'k_return':        False,
            'suit_changed':    False,
            'declared_suit':   declared_suit,
            'shielded':        False,
            'joker_on_pickup': False,
            'question_chain':  False,
        }

        has_question = any(c.card_type == CardType.QUESTION for c in cards)
        if has_question:
            result['question_chain'] = True

        leading_type = self._combo_leading_type(cards)
        for card in cards:
            self._process_single(card, result, declared_suit, leading_type)

        # Even K count → k_return, odd → reverse.
        # k_return ("play again") only applies when the play is a *bare*
        # K stack — i.e. nothing was bundled on after the last King. If
        # the player bundled an answer card (or more) after the K's in
        # the same combo (e.g. [K♣, K♠, 7♠]), that combo is already a
        # complete play: the extra turn the even-K stack would have
        # granted was already spent playing the bundled card(s), so the
        # turn must move on normally instead of returning to this player
        # again. Without this check, any even-count K combo with a
        # trailing card wrongly gave the player a second, unrelated play.
        last_k_idx = None
        for i, c in enumerate(cards):
            if c.card_type == CardType.KICKBACK:
                last_k_idx = i
        has_trailing_after_k = (last_k_idx is not None
                                 and last_k_idx < len(cards) - 1)

        k_count = result['reverse_count']
        if k_count > 0:
            result['reverse']  = (k_count % 2 == 1)
            result['k_return'] = (k_count % 2 == 0) and not has_trailing_after_k

        last_card = cards[-1]
        # The declared suit should only override current_suit when the
        # ACE itself is the card actually ending up on top (i.e. it's the
        # last card played). If other cards were bundled on AFTER the ACE
        # in the same move (e.g. an ACE+finishing combo like
        # [A♠, 9♦, 9♣]), last_card is one of those, not the ACE — and it
        # has its own suit that's about to be shown as the top card. Using
        # the ACE's earlier declared_suit there produced a real bug: the
        # "current suit" indicator could show a suit that flat-out
        # contradicted the actual top card on screen. The last card played
        # always wins for what "current suit" means going forward.
        suit_override = declared_suit if (result['suit_changed']
                                          and last_card.card_type == CardType.SUIT_CHANGE) else None
        self.set_top_card(last_card, suit_override)

        if result['shielded']:
            self.pickup_pending = 0
            self.pickup_rank    = None
            self.pickup_suit    = None

        self.skip_count = result['skip_count']
        game_log.debug(f"process_play result={result} "
                        f"pickup_pending(after)={self.pickup_pending} "
                        f"pickup_suit(after)={self.pickup_suit}")
        return result

    def _process_single(self, card: Card, result: dict, declared_suit: Optional[Suit],
                         leading_type=None):
        if card.card_type == CardType.QUESTION:
            pass  # effects from answer card
        elif card.card_type == CardType.SUIT_CHANGE:
            # Shielding (fully cancelling) a pending pick-up via a
            # bundled ACE is restricted per pickup_shield_qk_allowed —
            # and, no matter that setting, NEVER allowed when the play
            # is Jump-led. A Jump-led shield would let a player lock in
            # the shield's benefit unconditionally while the Jump's own
            # genuine risk (being countered) is sidestepped entirely,
            # since countering a Jump doesn't undo cards already played
            # — an asymmetric "free" combo the other allowed shapes
            # don't have. See ace_shields_pickup, the single source of
            # truth this mirrors (also used as the resolves-pending-
            # pickup gate).
            if self.pickup_pending > 0 and self._ace_shield_allowed(leading_type):
                result['shielded'] = True
            else:
                result['suit_changed'] = True
                if declared_suit:
                    self.current_suit = declared_suit
        elif card.card_type == CardType.KICKBACK:
            result['reverse_count'] += 1
        elif card.card_type == CardType.JUMP:
            result['skip']       = True
            result['skip_count'] += 1
        elif card.is_pickup or card.rank == 'JOKER':
            val = PICKUP_VALUES.get(card.card_type, 5)  # Joker = 5

            if self.pickup_pending == 0:
                self.pickup_pending = val
                self.pickup_rank    = card.rank
                self.pickup_suit    = card.suit  # None for Joker
            else:
                prev_was_joker = (self.pickup_suit is None)
                curr_is_joker  = (card.rank == 'JOKER')

                if curr_is_joker:
                    # Joker always adds +5, and — critically — a Joker on top
                    # of the chain means no suit integrity applies anymore
                    # (the chain is now "Joker-led" going forward), exactly
                    # like a Joker starting a fresh chain. Without this reset
                    # the engine kept enforcing the suit of whatever card
                    # started the chain even though the Joker is now on top,
                    # incorrectly blocking valid pick-up cards of any suit.
                    self.pickup_pending += val
                    self.pickup_suit = None
                    self.pickup_rank = 'JOKER'
                    result['joker_on_pickup'] = True
                elif prev_was_joker:
                    # After Joker: any pickup accumulates, adopt its suit
                    self.pickup_pending += val
                    self.pickup_suit = card.suit
                    self.pickup_rank = card.rank
                elif card.rank == self.pickup_rank:
                    # Same rank continues the chain regardless of suit
                    # (e.g. 3♣ on a pending 3♠). Previously pickup_suit was
                    # left untouched here, so it kept pointing at whatever
                    # suit started the chain even after a different-suited
                    # card became the new top card. That stale suit then
                    # fed two things incorrectly: (1) any *next* card
                    # extending by suit-match (a 2 after a 3, say) was
                    # checked against a suit no longer showing on the pile,
                    # and (2) an ACE played to shield the pickup (when the
                    # "ACE Suit Integrity" setting is on) was checked
                    # against that same stale suit — so a player holding an
                    # Ace that matched the *visible* top card's suit could
                    # see it rejected. Updating pickup_suit here keeps it
                    # tracking whatever suit is actually on top.
                    self.pickup_pending += val
                    self.pickup_suit = card.suit
                elif card.suit == self.pickup_suit:
                    self.pickup_pending += val
                    self.pickup_rank = card.rank

            result['pickup_total'] = self.pickup_pending

    # ─── KADI validation ─────────────────────────────────────────────────

    def is_valid_kadi_finish(self, cards: List[Card]) -> bool:
        if not cards:
            return False
        last = cards[-1]
        if not last.is_finishing:
            return False
        if not self.is_playable(cards[0]):
            return False
        ok, reason = self.is_valid_sequence(cards)
        if not ok or reason == "QUESTION_NO_ANSWER":
            return False
        return True

    def resolve_pickup(self) -> int:
        count           = self.pickup_pending
        self.pickup_pending = 0
        self.pickup_rank    = None
        self.pickup_suit    = None
        return count

    def can_declare_kadi(self, hand) -> bool:
        return hand.can_declare_kadi(self)

    def can_close_hand_with(self, cards: List[Card]) -> bool:
        """KADI-declare ELIGIBILITY check: could this exact set of cards,
        played together in SOME legal order on some future turn, validly
        end the game? This is deliberately broader than "all finishing,
        same rank" — is_valid_kadi_finish (the check applied when you
        actually PLAY your declared finish) already accepts any fully-
        resolved sequence ending on a finishing card, including a
        Question-chain, an even-count Kickback run, or a Jump run,
        answered by a same-rank finishing set — or a lone ACE answered
        by any finishing cards. The eligibility check used to only
        recognize the plain same-rank case, so a hand like [Q♦, Q♥, 6♦,
        6♥] (a legal Q-chain-then-6s play) couldn't be declared even
        though playing it out later absolutely would have worked.

        Unlike is_valid_kadi_finish, this does NOT check
        is_playable(cards[0]) against the CURRENT top card — eligibility
        is being judged for a hand that will only actually be played on
        some FUTURE turn, against whatever the top card is then (that
        gets re-checked for real by is_valid_kadi_finish at that point).
        See order_for_closing for the shape rules themselves.
        """
        return self.order_for_closing(cards) is not None

    def order_for_closing(self, cards: List[Card], prefer_playable_now: bool = False,
                          active_player_count: Optional[int] = None) -> Optional[List[Card]]:
        """If `cards` (played together, in some order) could validly end
        the game, return a concrete legal ordering of them — otherwise
        None. Recognizes: a same-rank finishing set; a Question chain,
        even-count Kickback run, or Jump run answered by a same-rank
        finishing set (suit integrity enforced via RuleEngine._cards_connect,
        same as any other play); or a lone ACE answered by any finishing
        cards. Used both for KADI-declare eligibility (can_close_hand_with,
        where the current top card and active player count are both
        irrelevant — see its docstring) and by the AI to actually
        construct a multi-card closing play once declared
        (prefer_playable_now=True), instead of only ever considering one
        finishing card at a time.

        With prefer_playable_now, tries every valid leader/finisher
        matching pair (there can be more than one when there's more than
        one leader — e.g. [Q♦, Q♥, 6♦, 6♥] could open on either Q) and
        returns one whose FIRST card is actually is_playable against the
        current top card, falling back to any structurally valid
        ordering if none of them are. Without it, just returns the first
        valid ordering found, since eligibility doesn't care which one.

        When constructing an actual play (prefer_playable_now=True) for
        a Jump-led shape, pass active_player_count too — see
        jump_bundle_legal — so this never hands back a Jump+finishing
        combo that GameManager._do_play would just reject for not
        meeting the traditional Jump-count rule.

        House rule choice: a Kickback-led shape only counts here with an
        EVEN Kickback count. The underlying grammar would also accept an
        odd count with a connecting answer, but odd-count Kickback
        finishes are deliberately excluded to keep this shape's parity
        unambiguous.
        """
        if not cards:
            return None

        if all(c.is_finishing for c in cards):
            return list(cards) if len(set(c.rank for c in cards)) == 1 else None

        finishing = [c for c in cards if c.is_finishing]
        leaders   = [c for c in cards if not c.is_finishing]
        if not finishing:
            return None
        if len(set(c.card_type for c in leaders)) != 1:
            return None   # the grammar has no mixed-leader-type chains

        leader_type = leaders[0].card_type

        if leader_type == CardType.SUIT_CHANGE:
            if not self.ace_finisher_enabled:
                return None
            # ACE+finishing needs no suit connection AND no same-rank
            # requirement among the finishing cards at all (see
            # RuleEngine._validate_special_then_finishing) — only one
            # ACE is meaningful as a single leader here.
            if len(leaders) != 1:
                return None
            ordered = leaders + finishing
            ok, reason = self.is_valid_sequence(ordered)
            return ordered if (ok and reason != "QUESTION_NO_ANSWER") else None

        if leader_type not in (CardType.QUESTION, CardType.KICKBACK, CardType.JUMP):
            return None
        if leader_type == CardType.JUMP:
            if not self.jump_multi_card_enabled:
                return None
            if active_player_count is not None and not self.jump_bundle_legal(cards, active_player_count):
                return None
        if leader_type == CardType.KICKBACK and len(leaders) % 2 != 0:
            return None   # house rule: even Kickback counts only
        if len(set(c.rank for c in finishing)) != 1:
            return None   # a Q/K/J-chain's finishing answer must be one rank

        # Consecutive leaders are always same rank (all Q, all K, or all
        # J), so their relative order never affects CHAIN validity — but
        # the answer's FIRST card specifically needs to connect by suit
        # to whichever leader ends up last, and the leader that ends up
        # FIRST is the one that actually has to be is_playable right now.
        # Build every valid (leader, finisher) match, not just the first
        # one found, so there's a real choice of which leader opens.
        candidates = []
        for l in leaders:
            for f in finishing:
                if l.suit != f.suit:
                    continue
                ordered = ([x for x in leaders if x is not l] + [l]
                           + [f] + [x for x in finishing if x is not f])
                ok, reason = self.is_valid_sequence(ordered)
                if ok and reason != "QUESTION_NO_ANSWER":
                    candidates.append(ordered)

        if not candidates:
            return None
        if prefer_playable_now:
            for c in candidates:
                if self.is_playable(c[0]):
                    return c
        return candidates[0]
