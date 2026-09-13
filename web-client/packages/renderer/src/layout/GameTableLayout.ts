/**
 * KADI web-client — GameTableScene's layout, as pure data (Part B).
 *
 * Sibling to LobbyLayout.ts, same discipline: no Phaser/DOM import,
 * every position/size is a function of (viewport, insets, game
 * state), fully unit-testable without a canvas. GameTableScene.ts's
 * job is "call this, apply the numbers to GameObjects" — see that
 * file and LobbyScene.ts for the pattern this copies.
 *
 * WHAT THIS PORTS FROM THE PYTHON CLIENT, AND WHAT IT DELIBERATELY
 * DOESN'T (per the task brief: "don't reinvent decisions it already
 * got right, and don't blindly copy decisions it got wrong"):
 *
 * - Oval seating (rendering/board_renderer.py's _layout_positions):
 *   ported conceptually (seats placed on an ellipse around a table
 *   center), NOT ported line-for-line. The Python version numbers
 *   seat 0 at angle -90 and then relies on a SEPARATE rotation
 *   (network/client_state.ClientGameManager always rotating the local
 *   seat to index 0, plus scenes.py's own _hotseat_layout_slot) to
 *   make "seat 0" visually land at the bottom for whoever's actually
 *   looking at the screen. This module skips that indirection: seats
 *   are placed directly by SEAT OFFSET FROM THE LOCAL PLAYER
 *   (seatOffset 0 == me, always bottom-center; increasing offset walks
 *   around the ellipse), computed fresh from whatever `you`/`players`
 *   state_sync just reported — no server-side or client-side seat
 *   rotation to keep in sync with.
 * - Card-fan geometry (rendering/board_renderer.py's HandRenderer.
 *   _card_positions): ported faithfully — same self-limiting overlap
 *   formula (a hand's fan never exceeds maxWidth no matter how many
 *   cards it holds), same "grow the gap between cards down to a
 *   floor, then start overlapping" shape. This is exported as its own
 *   pure computeFanPositions() so opponent-hand and local-hand slots
 *   share one geometry function, as HandRenderer.render() does for
 *   both face-up and face-down hands.
 * - Pile/badge placement (draw_piles/_draw_suit_indicator/
 *   draw_pickup_indicator/_draw_turn_indicator's "must pick" banner):
 *   ported CONCEPTUALLY, not pixel-for-pixel — same relative
 *   arrangement this project already fixed several overlap bugs to
 *   reach (suit indicator to the LEFT of the piles, pickup badge
 *   ABOVE pile-center, "must pick" banner BELOW pile-center, never
 *   dead-centered where a seat's own info panel would sit), but this
 *   whole layout is fresh continuous-scale math (see scale.ts), not
 *   the Python client's fixed-resolution-picker pixel offsets — there
 *   is no equivalent lookup table to copy values out of.
 * - The POST_PLAY "Yes! KADI / Proceed" panel (scenes.py's
 *   _draw_kadi_mini): ported minus the Undo row. Undo is
 *   intentionally not a network intent at all (see packages/protocol/
 *   src/messages.ts's file-level note) — there is nothing to retrofit
 *   a third button onto here, unlike the Python client's host-local
 *   case.
 *
 * SCOPE, UPDATED (Prompt 1, §9): this module lays out SINGLE- or
 * MULTI-card selection slots for the local hand (tap to toggle any
 * number of cards, Play sends whatever's selected). Drag-to-reorder
 * IS implemented (GameTableScene.ts owns the drag state and pointer
 * handling; this module only supplies the pure geometry it needs --
 * computeLocalHandSlots for the resting fan, getDropIndex for translating
 * a pointer x into a drop slot -- see handOrder.ts for the
 * local-display-order bookkeeping the drag itself updates).
 * GameTableScene.ts's playability highlighting (which reads this
 * layout's slot rects for hit-testing) only mirrors
 * core/rule_engine.py's single-card is_playable() — see that file's
 * own note for why multi-card sequence legality stays server-only.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
// Reuses LobbyLayout's TextLayout ({x, y, fontPx}) rather than
// redefining an identical shape under a second name -- both modules
// export from the same package barrel (index.ts), and two types
// named TextLayout there would be an ambiguous re-export.
import type { TextLayout } from './LobbyLayout.js';

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One local-hand or opponent-hand card slot — a CENTER point (matches
 * Phaser's default GameObject origin usage in this renderer) plus the
 * card's own scaled size. `overlap` is exposed for tests/documentation
 * of the self-limiting fan formula, not needed by the scene itself. */
export interface CardSlot extends Point {
  width: number;
  height: number;
  overlap: number;
}

/**
 * Direct port of HandRenderer._card_positions's formula
 * (rendering/board_renderer.py): a fan of `n` cards centered on
 * (cx, cy), self-limited to `maxWidth` regardless of `n`. Returns
 * CENTER points (Python's version returns top-left corners; centers
 * are more convenient for Phaser's origin(0.5) sprites and for this
 * module's own touch-target math below).
 */
export function computeFanPositions(
  n: number,
  cx: number,
  cy: number,
  maxWidth: number,
  cardWidth: number,
  cardHeight: number,
): CardSlot[] {
  if (n <= 0) return [];
  const overlap = Math.max(10, Math.min(cardWidth - 4, (maxWidth - cardWidth) / Math.max(n - 1, 1)));
  const totalWidth = cardWidth + overlap * (n - 1);
  const startCenterX = cx - totalWidth / 2 + cardWidth / 2;
  const slots: CardSlot[] = [];
  for (let i = 0; i < n; i++) {
    slots.push({
      x: startCenterX + i * overlap,
      y: cy,
      width: cardWidth,
      height: cardHeight,
      overlap,
    });
  }
  return slots;
}

export interface SeatLayout {
  /** 0 == the local player, always bottom-center; increasing offset
   * walks around the table — see this file's docstring for why this
   * replaces the Python client's seat-0-plus-rotation indirection. */
  seatOffset: number;
  isLocal: boolean;
  /** Card-fan/back-stack anchor for this seat. */
  handCenter: Point;
  /** Name/card-count info badge position — sits just below the local
   * seat's fan and just outside opponents' back-stacks, mirroring
   * draw_player_info's panel-below/beside-hand placement. */
  badge: TextLayout;
  /** Only meaningful for the local seat (isLocal === true) — max
   * total width its card fan may occupy, fed to computeFanPositions
   * alongside a scaled card size. Opponents render a compact face-down
   * stack, not a full fan, so they don't need this. */
  maxHandWidth: number;
}

export interface ActionButton extends Box {
  label: string;
}

export interface ActionPanelLayout extends Box {
  /** Only present while the panel is actually showing the local
   * player's own live POST_PLAY decision — see GameTableScene.ts,
   * which mirrors scenes.py's _draw_kadi_mini's is_active gating
   * (an inert "Waiting on <name>..." state renders text only, no
   * buttons, same as the Python client). */
  kadiButton: ActionButton;
  proceedButton: ActionButton;
}

export interface SuitPickLayout extends Box {
  buttons: (ActionButton & { suit: 'SPADES' | 'LOVE' | 'DICE' | 'FLOWERS' })[];
}

export interface CounterPanelLayout extends Box {
  passButton: ActionButton;
}

export interface WinScreenLayout {
  title: TextLayout;
  subtitle: TextLayout;
  playAgainButton: ActionButton;
}

export interface GameTableLayout {
  scale: number;
  contentRect: ContentRect;
  tableCenter: Point;
  tableRadiusX: number;
  tableRadiusY: number;
  seats: SeatLayout[];
  cardWidth: number;
  cardHeight: number;
  discardPile: Box;
  drawPile: Box;
  drawPileLabel: TextLayout;
  discardPileLabel: TextLayout;
  suitIndicator: TextLayout;
  pickupBadge: TextLayout;
  mustPickBanner: TextLayout;
  turnBanner: TextLayout;
  directionBadge: TextLayout;
  actionPanel: ActionPanelLayout;
  suitPick: SuitPickLayout;
  counterPanel: CounterPanelLayout;
  winScreen: WinScreenLayout;
  /** Play/Draw buttons for the local player's own ordinary turn —
   * there is no equivalent explicit button in the Python client (it
   * infers play/draw from card clicks / a keyboard shortcut), but
   * Part D's touch-only input model needs an explicit tappable
   * "Draw" target since there's no card to tap for that action, and
   * an explicit "Play selected" target for the same reason multi-card
   * selection needs a confirm step rather than committing on the
   * first tap. */
  drawButton: ActionButton;
  playButton: ActionButton;
}

const BASE_CARD_W = 70;
const BASE_CARD_H = 100;

const BASE_TABLE_RX_FRAC = 0.34;
const BASE_TABLE_RY_FRAC = 0.26;

export interface GameTableLayoutOptions {
  /** Total seats at the table, including the local player. */
  numPlayers: number;
  /** How many cards the local player currently holds — drives the
   * hand-fan slot count. Opponents never need this (they render a
   * compact face-down badge, not a per-card fan). */
  localHandCount: number;
}

export function computeGameTableLayout(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  options: GameTableLayoutOptions,
): GameTableLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const n = Math.max(1, options.numPlayers);

  const cardWidth = BASE_CARD_W * scale;
  const cardHeight = (cardWidth * BASE_CARD_H) / BASE_CARD_W;

  const tableCenter: Point = {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + contentRect.height / 2,
  };
  const tableRadiusX = contentRect.width * BASE_TABLE_RX_FRAC;
  const tableRadiusY = contentRect.height * BASE_TABLE_RY_FRAC;

  // Local hand sits below the table oval, inside the safe content
  // rect, with room left underneath for the action panel/buttons.
  const localHandCenter: Point = {
    x: tableCenter.x,
    y: contentRect.y + contentRect.height - cardHeight * 0.9,
  };
  const localMaxHandWidth = Math.min(contentRect.width * 0.92, 520 * scale);

  const seats: SeatLayout[] = [];
  for (let seatOffset = 0; seatOffset < n; seatOffset++) {
    const isLocal = seatOffset === 0;
    let handCenter: Point;
    let maxHandWidth = 0;
    if (isLocal) {
      handCenter = localHandCenter;
      maxHandWidth = localMaxHandWidth;
    } else {
      // See this file's docstring: angle 90° (screen down) is always
      // the local seat; other seats walk around the ellipse from
      // there, so this needs no server-side or client-side seat
      // rotation to stay correct as `you` changes between games.
      const angleDeg = 90 + (360 / n) * seatOffset;
      const rad = (angleDeg * Math.PI) / 180;
      handCenter = {
        x: tableCenter.x + tableRadiusX * Math.cos(rad),
        y: tableCenter.y + tableRadiusY * Math.sin(rad),
      };
    }
    const badgeOffsetY = isLocal ? -(cardHeight / 2 + 14 * scale) : cardHeight / 2 + 8 * scale;
    seats.push({
      seatOffset,
      isLocal,
      handCenter,
      maxHandWidth,
      badge: {
        x: handCenter.x,
        y: handCenter.y + badgeOffsetY,
        fontPx: fontPx(isLocal ? 'ui_small' : 'ui_tiny', scale),
      },
    });
  }

  const pileGap = 6 * scale;
  const discardPile: Box = {
    x: tableCenter.x - cardWidth - pileGap / 2,
    y: tableCenter.y - cardHeight / 2,
    width: cardWidth,
    height: cardHeight,
  };
  const drawPile: Box = {
    x: tableCenter.x + pileGap / 2,
    y: tableCenter.y - cardHeight / 2,
    width: cardWidth,
    height: cardHeight,
  };
  const pileLabelGap = 6 * scale;
  const discardPileLabel: TextLayout = {
    x: discardPile.x + discardPile.width / 2,
    y: discardPile.y + discardPile.height + pileLabelGap,
    fontPx: fontPx('ui_tiny', scale),
  };
  const drawPileLabel: TextLayout = {
    x: drawPile.x + drawPile.width / 2,
    y: drawPile.y + drawPile.height + pileLabelGap,
    fontPx: fontPx('ui_tiny', scale),
  };

  // Suit indicator: open felt to the LEFT of the piles (see this
  // file's docstring — mirrors _draw_suit_indicator's placement fix).
  const suitIndicator: TextLayout = {
    x: discardPile.x - 34 * scale,
    y: tableCenter.y,
    fontPx: fontPx('ui_small', scale),
  };
  // Pickup badge: ABOVE pile-center; must-pick banner: BELOW
  // pile-center — mirrors draw_pickup_indicator/_draw_turn_indicator's
  // fix keeping the two from ever overlapping each other or a seat panel.
  const pickupBadge: TextLayout = {
    x: drawPile.x + drawPile.width + 34 * scale,
    y: tableCenter.y - 14 * scale,
    fontPx: fontPx('ui_medium', scale),
  };
  const mustPickBanner: TextLayout = {
    x: drawPile.x + drawPile.width + 34 * scale,
    y: tableCenter.y + 14 * scale,
    fontPx: fontPx('ui_small', scale),
  };

  const turnBanner: TextLayout = {
    x: tableCenter.x,
    y: contentRect.y + 20 * scale,
    fontPx: fontPx('ui_medium', scale),
  };
  const directionBadge: TextLayout = {
    x: contentRect.x + 50 * scale,
    y: contentRect.y + contentRect.height - 20 * scale,
    fontPx: fontPx('ui_tiny', scale),
  };

  // Action panel (POST_PLAY KADI/Proceed): to the side of the local
  // hand, same relative placement as scenes.py's _draw_kadi_mini
  // (px = hand_cx + offset, clamped to stay on-screen).
  const panelWidth = Math.min(210 * scale, contentRect.width * 0.5);
  const buttonHeight = enforceMinTouchTarget({ width: panelWidth - 18 * scale, height: 36 * scale }).height;
  const panelHeight = 26 * scale + buttonHeight * 2 + 12 * scale;
  const panelX = Math.min(
    localHandCenter.x + localMaxHandWidth / 2 + 20 * scale,
    contentRect.x + contentRect.width - panelWidth - 10 * scale,
  );
  const panelY = Math.max(
    contentRect.y + 10 * scale,
    Math.min(localHandCenter.y - panelHeight / 2, contentRect.y + contentRect.height - panelHeight - 10 * scale),
  );
  const buttonWidth = enforceMinTouchTarget({ width: panelWidth - 18 * scale, height: buttonHeight }).width;
  const kadiButton: ActionButton = {
    x: panelX + 9 * scale,
    y: panelY + 26 * scale,
    width: buttonWidth,
    height: buttonHeight,
    label: 'Yes! KADI',
  };
  const proceedButton: ActionButton = {
    x: panelX + 9 * scale,
    y: kadiButton.y + buttonHeight + 6 * scale,
    width: buttonWidth,
    height: buttonHeight,
    label: 'Proceed',
  };
  const actionPanel: ActionPanelLayout = {
    x: panelX,
    y: panelY,
    width: panelWidth,
    height: panelHeight,
    kadiButton,
    proceedButton,
  };

  // Suit-pick panel: four suit buttons, centered on the table —
  // this is a modal-style decision (SUIT_PICK blocks everything else
  // for the acting player), so unlike the action panel it doesn't
  // need to dodge the local hand.
  const suitOrder: ('SPADES' | 'LOVE' | 'DICE' | 'FLOWERS')[] = ['SPADES', 'LOVE', 'DICE', 'FLOWERS'];
  const suitBtnSize = enforceMinTouchTarget({ width: 64 * scale, height: 64 * scale });
  const suitGap = 12 * scale;
  const suitPanelWidth = suitBtnSize.width * suitOrder.length + suitGap * (suitOrder.length - 1) + 24 * scale;
  const suitPanelHeight = suitBtnSize.height + 48 * scale;
  const suitPanelX = tableCenter.x - suitPanelWidth / 2;
  const suitPanelY = tableCenter.y - suitPanelHeight / 2;
  const suitButtons = suitOrder.map((suit, i) => ({
    suit,
    x: suitPanelX + 12 * scale + i * (suitBtnSize.width + suitGap),
    y: suitPanelY + 40 * scale,
    width: suitBtnSize.width,
    height: suitBtnSize.height,
    label: suit,
  }));
  const suitPick: SuitPickLayout = {
    x: suitPanelX,
    y: suitPanelY,
    width: suitPanelWidth,
    height: suitPanelHeight,
    buttons: suitButtons,
  };

  // Counter panel (JUMP_COUNTER_WINDOW "Pass" — countering itself
  // happens by tapping a J in hand, same as an ordinary play, so this
  // only needs one explicit button): reuses the action panel's slot
  // so the two decisions (which are mutually exclusive in time) never
  // fight for space.
  const counterPanel: CounterPanelLayout = {
    x: panelX,
    y: panelY,
    width: panelWidth,
    height: buttonHeight + 44 * scale,
    passButton: {
      x: panelX + 9 * scale,
      y: panelY + 26 * scale,
      width: buttonWidth,
      height: buttonHeight,
      label: 'Pass',
    },
  };

  const winButtonSize = enforceMinTouchTarget({ width: 200 * scale, height: 50 * scale });
  const winScreen: WinScreenLayout = {
    title: {
      x: tableCenter.x,
      y: tableCenter.y - 60 * scale,
      fontPx: fontPx('ui_large', scale),
    },
    subtitle: {
      x: tableCenter.x,
      y: tableCenter.y,
      fontPx: fontPx('ui_normal', scale),
    },
    playAgainButton: {
      x: tableCenter.x - winButtonSize.width / 2,
      y: tableCenter.y + 40 * scale,
      width: winButtonSize.width,
      height: winButtonSize.height,
      label: 'Back to Lobby',
    },
  };

  const drawButtonSize = enforceMinTouchTarget({ width: cardWidth, height: 32 * scale });
  const drawButton: ActionButton = {
    x: drawPile.x + drawPile.width / 2 - drawButtonSize.width / 2,
    y: drawPile.y - drawButtonSize.height - 6 * scale,
    width: drawButtonSize.width,
    height: drawButtonSize.height,
    label: 'Draw',
  };
  const playButtonSize = enforceMinTouchTarget({ width: 110 * scale, height: 40 * scale });
  const playButton: ActionButton = {
    x: localHandCenter.x - playButtonSize.width / 2,
    y: localHandCenter.y + cardHeight / 2 + 18 * scale,
    width: playButtonSize.width,
    height: playButtonSize.height,
    label: 'Play',
  };

  return {
    scale,
    contentRect,
    tableCenter,
    tableRadiusX,
    tableRadiusY,
    seats,
    cardWidth,
    cardHeight,
    discardPile,
    drawPile,
    discardPileLabel,
    drawPileLabel,
    suitIndicator,
    pickupBadge,
    mustPickBanner,
    turnBanner,
    directionBadge,
    actionPanel,
    suitPick,
    counterPanel,
    winScreen,
    drawButton,
    playButton,
  };
}

/** Local-hand card slots for this layout — the one call site
 * GameTableScene uses for both drawing the fan and hit-testing taps
 * against it (Part D). Pulled out as its own function (rather than
 * folded into computeGameTableLayout's return) because the number of
 * cards in hand changes far more often (every draw/play) than
 * anything else in the layout, and recomputing the whole table layout
 * on every hand-size change would be wasteful and would also needlessly
 * re-run seat placement math that has nothing to do with the local
 * player's own card count. */
export function computeLocalHandSlots(layout: GameTableLayout, handCount: number): CardSlot[] {
  const localSeat = layout.seats.find((s) => s.isLocal);
  if (!localSeat) return [];
  return computeFanPositions(
    handCount,
    localSeat.handCenter.x,
    localSeat.handCenter.y,
    localSeat.maxHandWidth,
    layout.cardWidth,
    layout.cardHeight,
  );
}

/**
 * Direct port of HandRenderer.get_drop_index (rendering/board_renderer.py):
 * given the local hand's own (undragged) fan slots and a pointer's current
 * x position, returns the slot index whose CENTER is nearest that x --
 * i.e. the position a dragged card would land in if released right now.
 * Deliberately fed the base (pre-drag-shift) slots, same as the Python
 * version always recomputing plain `_card_positions` rather than reusing
 * whatever visual insertion-gap shift a drag-in-progress is showing --
 * the drop target is a function of the pointer against the RESTING fan,
 * not against its own gap-shifted rendering.
 */
export function getDropIndex(slots: CardSlot[], pointerX: number): number {
  if (slots.length === 0) return 0;
  let bestIdx = 0;
  let bestDist = Infinity;
  for (let i = 0; i < slots.length; i++) {
    const dist = Math.abs(pointerX - slots[i].x);
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = i;
    }
  }
  return bestIdx;
}
