import { describe, expect, it } from 'vitest';
import { isCardPlayable } from '../cardPlayability.js';
import type { CardDict, RuleEngineSnapshot } from '@kadi/protocol';

function card(rank: CardDict['rank'], suit: CardDict['suit'] = null, isRedJoker = false): CardDict {
  return { rank, suit, is_red_joker: isRedJoker };
}

function rule(overrides: Partial<RuleEngineSnapshot> = {}): RuleEngineSnapshot {
  return {
    current_suit: 'SPADES',
    pickup_pending: 0,
    pickup_rank: null,
    pickup_suit: null,
    top_card: card('7', 'SPADES'),
    skip_count: 0,
    joker_on_top: false,
    ace_suit_integrity: false,
    pickup_shield_qk_allowed: true,
    ace_finisher_enabled: true,
    jump_multi_card_enabled: true,
    ...overrides,
  };
}

describe('isCardPlayable — no top card yet (opening play)', () => {
  it('anything is playable when there is no top card', () => {
    const r = rule({ top_card: null });
    expect(isCardPlayable(card('4', 'DICE'), r, false)).toBe(true);
    expect(isCardPlayable(card('JOKER', null, true), r, false)).toBe(true);
  });
});

describe('isCardPlayable — joker on top, no pending pickup', () => {
  it('any card is playable', () => {
    const r = rule({ joker_on_top: true, pickup_pending: 0 });
    expect(isCardPlayable(card('4', 'DICE'), r, false)).toBe(true);
  });
});

describe('isCardPlayable — ordinary suit/rank matching', () => {
  it('matches current suit', () => {
    const r = rule({ current_suit: 'LOVE', top_card: card('9', 'SPADES') });
    expect(isCardPlayable(card('4', 'LOVE'), r, false)).toBe(true);
  });

  it('matches top card rank regardless of suit', () => {
    const r = rule({ current_suit: 'LOVE', top_card: card('9', 'SPADES') });
    expect(isCardPlayable(card('9', 'DICE'), r, false)).toBe(true);
  });

  it('rejects a card matching neither suit nor rank', () => {
    const r = rule({ current_suit: 'LOVE', top_card: card('9', 'SPADES') });
    expect(isCardPlayable(card('4', 'DICE'), r, false)).toBe(false);
  });

  it('a Joker is always playable outside a pickup chain', () => {
    const r = rule({ current_suit: 'LOVE', top_card: card('9', 'SPADES') });
    expect(isCardPlayable(card('JOKER', null, false), r, false)).toBe(true);
  });
});

describe('isCardPlayable — special cards (Q/8/J/K) require suit-or-rank match', () => {
  it('Question (8/Q), Kickback (K), Jump (J) each need current-suit or top-rank match', () => {
    const r = rule({ current_suit: 'FLOWERS', top_card: card('5', 'SPADES') });
    for (const rank of ['8', 'Q', 'K', 'J'] as const) {
      expect(isCardPlayable(card(rank, 'FLOWERS'), r, false)).toBe(true); // suit match
      expect(isCardPlayable(card(rank, 'DICE'), r, false)).toBe(false); // neither
    }
    expect(isCardPlayable(card('9', 'DICE'), r, false)).toBe(false); // wrong suit, wrong rank
  });
});

describe('isCardPlayable — ACE (suit-change)', () => {
  it('always playable when ace_suit_integrity is off', () => {
    const r = rule({ ace_suit_integrity: false, current_suit: 'FLOWERS', top_card: card('5', 'SPADES') });
    expect(isCardPlayable(card('ACE', 'DICE'), r, false)).toBe(true);
  });

  it('requires suit or top-rank match when ace_suit_integrity is on', () => {
    const r = rule({ ace_suit_integrity: true, current_suit: 'FLOWERS', top_card: card('5', 'SPADES') });
    expect(isCardPlayable(card('ACE', 'FLOWERS'), r, false)).toBe(true);
    expect(isCardPlayable(card('ACE', 'DICE'), r, false)).toBe(false);
    expect(isCardPlayable(card('ACE', 'SPADES'), r, false)).toBe(false);
  });
});

describe('isCardPlayable — during a pending pickup chain (pickupPending=true)', () => {
  it('a same-rank card always counters', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('2', 'DICE'), r, true)).toBe(true);
  });

  it('a same-suit pickup card counters when chain suit is set', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('3', 'SPADES'), r, true)).toBe(true);
  });

  it('a different-suit, different-rank pickup card does NOT counter', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('3', 'DICE'), r, true)).toBe(false);
  });

  it('any pickup card counters after a Joker-led chain (pickup_suit is null)', () => {
    const r = rule({ pickup_pending: 5, pickup_suit: null, top_card: card('JOKER', null) });
    expect(isCardPlayable(card('3', 'DICE'), r, true)).toBe(true);
  });

  it('a Joker always counters', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('JOKER', null, true), r, true)).toBe(true);
  });

  it('a Question card does NOT count as a solo pickup-counter (it can only lead a multi-card sequence, per core/game_manager.py\'s _do_play)', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('8', 'DICE'), r, true)).toBe(false);
    expect(isCardPlayable(card('Q', 'DICE'), r, true)).toBe(false);
  });

  it('a non-pickup standard card cannot counter', () => {
    const r = rule({ pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('4', 'SPADES'), r, true)).toBe(false);
  });

  it('an ACE shields freely when ace_suit_integrity is off', () => {
    const r = rule({ ace_suit_integrity: false, pickup_pending: 3, pickup_suit: 'DICE' });
    expect(isCardPlayable(card('ACE', 'SPADES'), r, true)).toBe(true);
  });

  it('an ACE must match pickup_suit to shield when ace_suit_integrity is on', () => {
    const r = rule({ ace_suit_integrity: true, pickup_pending: 3, pickup_suit: 'DICE' });
    expect(isCardPlayable(card('ACE', 'DICE'), r, true)).toBe(true);
    expect(isCardPlayable(card('ACE', 'SPADES'), r, true)).toBe(false);
  });

  it('joker_on_top does NOT make everything playable while a pickup is pending', () => {
    // is_playable's early "joker_on_top && pickup_pending==0" bypass
    // must NOT fire once a pickup chain is active -- pending pickup
    // always routes through the counter-only branch.
    const r = rule({ joker_on_top: true, pickup_pending: 2, pickup_suit: 'SPADES', top_card: card('2', 'SPADES') });
    expect(isCardPlayable(card('4', 'DICE'), r, true)).toBe(false);
  });
});
