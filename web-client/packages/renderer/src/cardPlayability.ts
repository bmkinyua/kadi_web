/**
 * KADI - client-side SINGLE-CARD playability hint.
 *
 * Faithful port of core/rule_engine.py's is_playable()/
 * _can_counter_pickup() for the single-card case ONLY. This exists
 * purely to highlight which cards in the local hand are worth
 * tapping -- it is NEVER the thing that decides whether a play is
 * accepted. The server (core/rule_engine.py, unmodified) re-validates
 * every intent_play/intent_counter from scratch; a card highlighted
 * as "playable" here that turns out not to be part of a legal combo
 * (see the multi-card note below) is simply rejected server-side the
 * same silent way any other illegal intent already is.
 *
 * NOT PORTED, ON PURPOSE: is_valid_sequence() and everything under
 * it (_validate_question_chain, _validate_pickup_mix,
 * _validate_k_sequence, _validate_j_sequence, jump_bundle_legal,
 * ace_shields_pickup) -- the multi-card combo legality rules. Those
 * depend on chain state (leading card type, how many cards deep,
 * whether a bundled extra card's count matches active_player_count,
 * ...) that would need to be kept in lockstep with the server's own
 * rule engine by hand, in two languages, forever -- exactly the kind
 * of drift risk the file-level note in packages/protocol/src/
 * messages.ts flags for the message shapes themselves, except worse
 * here because rule_engine.py's sequence validation is ~250 lines of
 * genuinely intricate branching (see that file), not a wire shape.
 * GameTableScene.ts's "is this card worth tapping" highlight only
 * ever looks at ONE card at a time as a result -- selecting several
 * cards together shows each as individually playable-or-not by this
 * same single-card rule, with no attempt to judge whether the
 * SPECIFIC COMBINATION selected would actually be accepted.
 *
 * ONE DELIBERATE DIVERGENCE from a pure is_playable() port: during a
 * pending pickup, a Question card (8/Q) is real-rule-engine-eligible
 * to LEAD a multi-card counter sequence, but core/game_manager.py's
 * _do_play() explicitly rejects it played ALONE ("cannot be played
 * alone" -- the sequence must end in an actual resolving card). Since
 * this function only ever judges one card in isolation, mirroring the
 * engine's permissive "legal sequence-opener" answer here would
 * highlight a card whose SOLO play is guaranteed to be silently
 * rejected -- see canCounterPickup()'s own docstring for how this was
 * actually caught (it hung a real network integration test).
 */
import type { CardDict, RuleEngineSnapshot } from '@kadi/protocol';

// constants.py's get_card_type -- only the branches is_playable/
// _can_counter_pickup actually consult.
type CardKind = 'QUESTION' | 'KICKBACK' | 'JUMP' | 'SUIT_CHANGE' | 'PICKUP' | 'STANDARD';

function cardKind(card: CardDict): CardKind {
  if (card.rank === '8' || card.rank === 'Q') return 'QUESTION';
  if (card.rank === 'K') return 'KICKBACK';
  if (card.rank === 'J') return 'JUMP';
  if (card.rank === 'ACE') return 'SUIT_CHANGE';
  if (card.rank === '2' || card.rank === '3') return 'PICKUP';
  return 'STANDARD';
}

function isPickupCard(card: CardDict): boolean {
  return card.rank === '2' || card.rank === '3' || card.rank === 'JOKER';
}

/**
 * Mirrors RuleEngine.is_playable(card) for the single-card case.
 * `pickupPending` is passed separately (rather than trusting
 * ruleEngine.pickup_pending > 0 implicitly) so call sites that
 * already computed it once don't repeat themselves -- see
 * GameTableScene.ts's renderLocalHand.
 */
export function isCardPlayable(card: CardDict, rule: RuleEngineSnapshot, pickupPending: boolean): boolean {
  const top = rule.top_card;
  if (!top) return true;

  if (rule.joker_on_top && !pickupPending) return true;

  if (pickupPending) return canCounterPickup(card, rule);

  if (card.rank === 'JOKER') return true;

  const kind = cardKind(card);

  if (kind === 'SUIT_CHANGE') {
    if (!rule.ace_suit_integrity) return true;
    return card.suit === rule.current_suit || (!!top && card.rank === top.rank);
  }

  if (kind === 'QUESTION' || kind === 'KICKBACK' || kind === 'JUMP') {
    if (card.suit === rule.current_suit) return true;
    if (top && card.rank === top.rank) return true;
    return false;
  }

  // Finishing / pickup standard: match suit or rank.
  if (card.suit === rule.current_suit) return true;
  if (top && card.rank === top.rank) return true;
  return false;
}

/** Mirrors RuleEngine._can_counter_pickup(card), WITH ONE DELIBERATE
 * NARROWING versus the engine's own version — see the note on the
 * QUESTION branch below. This function answers "would submitting
 * JUST this one card, alone, actually resolve the pending pickup?",
 * which is what matters for a single-tap highlight in a UI whose Play
 * button sends exactly the selected cards (see GameTableScene.ts). The
 * engine's _can_counter_pickup answers a related but different
 * question — "is this a legal card to LEAD a multi-card counter
 * sequence with?" — which is a broader set (see
 * core/game_manager.py's _do_play(): "A lone Question (8/Q) card is
 * allowed to PRECEDE a counter inside the same multi-card play, but
 * cannot be played alone"). Highlighting a Question card as
 * pickup-safe here, only for a solo tap-and-Play of it to be silently
 * rejected server-side, is a worse UX than just not highlighting it —
 * this was caught for real by this project's own network integration
 * test (see @kadi/client-core's gameIntegration.test.ts and this
 * package's own test file), which hung indefinitely resending the
 * exact same doomed lone-Question-card play every tick until this was
 * fixed. Selecting a Question card ALONGSIDE an actual resolving card
 * (multi-select, then Play) still works and is still validated
 * server-side exactly as always — this only changes which cards a
 * SOLO tap is hinted as likely to succeed. */
function canCounterPickup(card: CardDict, rule: RuleEngineSnapshot): boolean {
  if (cardKind(card) === 'SUIT_CHANGE') {
    if (!rule.ace_suit_integrity) return true;
    if (rule.pickup_suit === null) return true;
    return card.suit === rule.pickup_suit;
  }
  if (card.rank === 'JOKER') return true;
  // NOT `if (cardKind(card) === 'QUESTION') return true;` here --
  // see this function's docstring. A Question card never resolves a
  // pickup by itself, only as the lead-in to a multi-card sequence
  // this single-card hint isn't attempting to judge.
  if (!isPickupCard(card)) return false;

  const top = rule.top_card;
  if (top && card.rank === top.rank) return true;
  if (rule.pickup_suit === null) return true;
  return card.suit === rule.pickup_suit;
}
