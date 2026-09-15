/**
 * KADI web-client — local hand-display-order bookkeeping (drag-to-reorder,
 * Prompt 1 in KADI_web_port_implementation_plan.md's §9 tracking).
 *
 * Framework-free and pure (no Phaser import), same discipline as
 * layout/GameTableLayout.ts, so the actual reorder/reconciliation math is
 * unit-testable without a canvas. GameTableScene.ts is the only caller:
 * it owns a `myHandOrder: CardDict[]` field and calls these two functions
 * on drag-release and on every state_sync respectively.
 *
 * WHY THIS EXISTS AT ALL (mirrors network/client_state.py's
 * ClientGameManager._my_hand_order / reorder_hand / _apply_snapshot's
 * reconciliation step exactly -- see that module's docstring):
 * server/network/state_sync.py's build_snapshot_for sends a player's own
 * hand as `cards_to_list(p.hand.cards)` -- whatever order the SERVER's
 * authoritative Hand list happens to be in (deal order, mutated only by
 * draw/play), never anything a client asked for. server/game_room.py's
 * _match_hand_cards matches a play/counter intent against that hand by
 * VALUE (rank+suit), consuming each requested card at most once, not by
 * position -- so card order is never consulted for legality anywhere
 * server-side. Confirmed here for the web port exactly as scenes.py's
 * _reorder_hand / network/client_state.py's module docstring already
 * establish for the Python client: "Hand order is a purely local,
 * client-side concern." A local drag-to-reorder therefore never needs a
 * server round-trip -- but without something like reconcileHandOrder,
 * the very next state_sync would rebuild the hand in the server's own
 * order and instantly undo the drag.
 */
import type { CardDict } from '@kadi/protocol';

/** A standard 52-card deck plus at most two jokers never has two cards
 * that are simultaneously the same rank, suit, AND joker-color -- so this
 * triple is a stable, sufficient identity key for matching "the same
 * card" between two hand snapshots (models/card.py's Card.__eq__ mirrors
 * the same rank/suit/is_red_joker triple on the Python side). */
export function cardKey(card: CardDict): string {
  return `${card.rank}|${card.suit ?? ''}|${card.is_red_joker}`;
}

/**
 * Direct port of ClientGameManager._apply_snapshot's hand-order
 * reconciliation (network/client_state.py): keep every card from
 * `previousOrder` that's still present in `serverHand` (in that same
 * relative order), consuming it from the pool at most once, then append
 * whatever's left in the pool (newly-drawn cards, or the server's own
 * order on the very first snapshot when previousOrder is empty) in the
 * order the server sent them. Cards no longer held (just played) simply
 * drop out. Returns a fresh array; never mutates either input.
 */
export function reconcileHandOrder(previousOrder: CardDict[], serverHand: CardDict[]): CardDict[] {
  const pool = [...serverHand];
  const reordered: CardDict[] = [];
  for (const prev of previousOrder) {
    const key = cardKey(prev);
    const poolIdx = pool.findIndex((c) => cardKey(c) === key);
    if (poolIdx !== -1) {
      reordered.push(pool[poolIdx]);
      pool.splice(poolIdx, 1);
    }
  }
  reordered.push(...pool);
  return reordered;
}

/** Clamp an index into the valid range for an array of length n (n>0
 * guaranteed by moveCard's own empty-array guard before calling this). */
function clampIndex(i: number, n: number): number {
  return Math.max(0, Math.min(n - 1, i));
}

/**
 * Direct port of scenes.py's _reorder_hand / ClientGameManager.
 * reorder_hand's pop-then-insert semantics: move the item at `fromIdx` to
 * `toIdx`, shifting everything between them by one. Out-of-range indices
 * are clamped rather than throwing (a drag can report a target beyond
 * the current hand length for an instant between renders); moving an
 * item to its own position is a correct no-op. Returns a fresh array;
 * never mutates `items`.
 */
export function moveCard<T>(items: readonly T[], fromIdx: number, toIdx: number): T[] {
  const n = items.length;
  if (n === 0) return [];
  const from = clampIndex(fromIdx, n);
  const to = clampIndex(toIdx, n);
  const arr = [...items];
  const [moved] = arr.splice(from, 1);
  arr.splice(to, 0, moved);
  return arr;
}
