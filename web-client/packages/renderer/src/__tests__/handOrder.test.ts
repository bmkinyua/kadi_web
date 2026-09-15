import { describe, expect, it } from 'vitest';
import { cardKey, moveCard, reconcileHandOrder } from '../handOrder.js';
import type { CardDict } from '@kadi/protocol';

function card(rank: CardDict['rank'], suit: CardDict['suit'], isRedJoker = false): CardDict {
  return { rank, suit, is_red_joker: isRedJoker };
}

describe('moveCard', () => {
  it('moves a card from one index to another, shifting everything between', () => {
    const result = moveCard(['A', 'B', 'C', 'D'], 1, 3);
    expect(result).toEqual(['A', 'C', 'D', 'B']);
  });

  it('drag to same position is a no-op', () => {
    const result = moveCard(['A', 'B', 'C'], 1, 1);
    expect(result).toEqual(['A', 'B', 'C']);
  });

  it('drag first-to-last', () => {
    const result = moveCard(['A', 'B', 'C', 'D'], 0, 3);
    expect(result).toEqual(['B', 'C', 'D', 'A']);
  });

  it('drag last-to-first', () => {
    const result = moveCard(['A', 'B', 'C', 'D'], 3, 0);
    expect(result).toEqual(['D', 'A', 'B', 'C']);
  });

  it('moving backwards (to a lower index) shifts the intervening cards forward', () => {
    const result = moveCard(['A', 'B', 'C', 'D'], 3, 1);
    expect(result).toEqual(['A', 'D', 'B', 'C']);
  });

  it('clamps an out-of-range target index instead of throwing', () => {
    expect(moveCard(['A', 'B', 'C'], 0, 99)).toEqual(['B', 'C', 'A']);
    expect(moveCard(['A', 'B', 'C'], 99, 0)).toEqual(['C', 'A', 'B']);
    expect(moveCard(['A', 'B', 'C'], -5, 1)).toEqual(['B', 'A', 'C']);
  });

  it('returns an empty array unchanged', () => {
    expect(moveCard([], 0, 0)).toEqual([]);
  });

  it('never mutates the input array', () => {
    const input = ['A', 'B', 'C'];
    const copy = [...input];
    moveCard(input, 0, 2);
    expect(input).toEqual(copy);
  });

  it('single-card hand is always a no-op regardless of indices', () => {
    expect(moveCard(['A'], 0, 0)).toEqual(['A']);
  });
});

describe('cardKey', () => {
  it('is stable for the same card', () => {
    const a = card('K', 'SPADES');
    const b = card('K', 'SPADES');
    expect(cardKey(a)).toBe(cardKey(b));
  });

  it('differs by rank, suit, or joker color', () => {
    const keys = new Set([
      cardKey(card('K', 'SPADES')),
      cardKey(card('Q', 'SPADES')),
      cardKey(card('K', 'LOVE')),
      cardKey(card('JOKER', null, true)),
      cardKey(card('JOKER', null, false)),
    ]);
    expect(keys.size).toBe(5);
  });
});

describe('reconcileHandOrder', () => {
  it('preserves a previously-dragged order when the server hand is unchanged', () => {
    const dragged = [card('K', 'SPADES'), card('2', 'LOVE'), card('ACE', 'DICE')];
    // Server re-sends the SAME cards in its own (different) order.
    const serverHand = [card('2', 'LOVE'), card('ACE', 'DICE'), card('K', 'SPADES')];
    expect(reconcileHandOrder(dragged, serverHand)).toEqual(dragged);
  });

  it('appends a newly-drawn card at the end, after the preserved order', () => {
    const dragged = [card('K', 'SPADES'), card('2', 'LOVE')];
    const serverHand = [card('2', 'LOVE'), card('K', 'SPADES'), card('9', 'FLOWERS')];
    expect(reconcileHandOrder(dragged, serverHand)).toEqual([
      card('K', 'SPADES'),
      card('2', 'LOVE'),
      card('9', 'FLOWERS'),
    ]);
  });

  it('drops a card that was just played, keeping the rest in order', () => {
    const dragged = [card('K', 'SPADES'), card('2', 'LOVE'), card('ACE', 'DICE')];
    const serverHand = [card('2', 'LOVE'), card('ACE', 'DICE')]; // K♠ was played
    expect(reconcileHandOrder(dragged, serverHand)).toEqual([card('2', 'LOVE'), card('ACE', 'DICE')]);
  });

  it('falls back to the server order on the very first snapshot (no previous order yet)', () => {
    const serverHand = [card('2', 'LOVE'), card('K', 'SPADES')];
    expect(reconcileHandOrder([], serverHand)).toEqual(serverHand);
  });

  it('handles an emptied hand (last card just played)', () => {
    const dragged = [card('K', 'SPADES')];
    expect(reconcileHandOrder(dragged, [])).toEqual([]);
  });

  it('never mutates its inputs', () => {
    const dragged = [card('K', 'SPADES'), card('2', 'LOVE')];
    const serverHand = [card('2', 'LOVE'), card('K', 'SPADES')];
    const draggedCopy = JSON.parse(JSON.stringify(dragged));
    const serverCopy = JSON.parse(JSON.stringify(serverHand));
    reconcileHandOrder(dragged, serverHand);
    expect(dragged).toEqual(draggedCopy);
    expect(serverHand).toEqual(serverCopy);
  });
});
