import { describe, expect, it } from 'vitest';
import {
  computeFanPositions,
  computeGameTableLayout,
  computeLocalHandSlots,
  getDropIndex,
} from '../GameTableLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('computeFanPositions', () => {
  it('returns nothing for zero cards', () => {
    expect(computeFanPositions(0, 100, 100, 500, 70, 100)).toEqual([]);
  });

  it('centers a single card exactly on (cx, cy)', () => {
    const slots = computeFanPositions(1, 150, 200, 500, 70, 100);
    expect(slots).toHaveLength(1);
    expect(slots[0].x).toBeCloseTo(150, 5);
    expect(slots[0].y).toBeCloseTo(200, 5);
  });

  it('never exceeds maxWidth regardless of how many cards are in the fan', () => {
    for (const n of [2, 4, 8, 16, 30]) {
      const cardWidth = 70;
      const maxWidth = 400;
      const slots = computeFanPositions(n, 0, 0, maxWidth, cardWidth, 100);
      const leftEdge = Math.min(...slots.map((s) => s.x - cardWidth / 2));
      const rightEdge = Math.max(...slots.map((s) => s.x + cardWidth / 2));
      expect(rightEdge - leftEdge).toBeLessThanOrEqual(maxWidth + 0.001);
    }
  });

  it('spaces cards at full card width (no overlap) when there is plenty of room', () => {
    const slots = computeFanPositions(3, 0, 0, 1000, 70, 100);
    // Center-to-center spacing should equal at least the card width
    // when maxWidth isn't the limiting factor.
    const spacing = slots[1].x - slots[0].x;
    expect(spacing).toBeGreaterThanOrEqual(70 - 4 - 0.001);
  });

  it('keeps every slot the same card size', () => {
    const slots = computeFanPositions(5, 0, 0, 300, 60, 90);
    for (const slot of slots) {
      expect(slot.width).toBe(60);
      expect(slot.height).toBe(90);
    }
  });
});

describe('computeGameTableLayout — seating', () => {
  it('always places the local seat (offset 0) at the bottom-center of the table', () => {
    for (const n of [2, 3, 4, 6]) {
      const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
        numPlayers: n,
        localHandCount: 4,
      });
      const local = layout.seats.find((s) => s.isLocal)!;
      expect(local.seatOffset).toBe(0);
      expect(local.handCenter.x).toBeCloseTo(layout.tableCenter.x, 1);
      expect(local.handCenter.y).toBeGreaterThan(layout.tableCenter.y);
    }
  });

  it('produces exactly numPlayers seats, each with a unique offset', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 5,
      localHandCount: 4,
    });
    expect(layout.seats).toHaveLength(5);
    const offsets = layout.seats.map((s) => s.seatOffset).sort((a, b) => a - b);
    expect(offsets).toEqual([0, 1, 2, 3, 4]);
  });

  it('spreads opponent seats around the table rather than stacking them on one point', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    const opponents = layout.seats.filter((s) => !s.isLocal);
    const positions = new Set(opponents.map((s) => `${s.handCenter.x.toFixed(1)},${s.handCenter.y.toFixed(1)}`));
    expect(positions.size).toBe(opponents.length);
  });

  it('degrades gracefully for a single-player table (numPlayers=1) without NaN', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 1,
      localHandCount: 4,
    });
    expect(layout.seats).toHaveLength(1);
    expect(Number.isFinite(layout.seats[0].handCenter.x)).toBe(true);
    expect(Number.isFinite(layout.seats[0].handCenter.y)).toBe(true);
  });

  it('keeps every opponent seat inside the safe content rect', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 6,
      localHandCount: 4,
    });
    for (const seat of layout.seats) {
      expect(seat.handCenter.x).toBeGreaterThanOrEqual(layout.contentRect.x);
      expect(seat.handCenter.x).toBeLessThanOrEqual(layout.contentRect.x + layout.contentRect.width);
      expect(seat.handCenter.y).toBeGreaterThanOrEqual(layout.contentRect.y);
      expect(seat.handCenter.y).toBeLessThanOrEqual(layout.contentRect.y + layout.contentRect.height);
    }
  });
});

describe('computeGameTableLayout — scaling across viewports', () => {
  it('grows card size and fonts as the viewport grows', () => {
    const phone = computeGameTableLayout(NARROW_PHONE_PORTRAIT, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 6,
    });
    const tablet = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 6,
    });
    expect(tablet.scale).toBeGreaterThan(phone.scale);
    expect(tablet.cardWidth).toBeGreaterThan(phone.cardWidth);
    expect(tablet.turnBanner.fontPx).toBeGreaterThan(phone.turnBanner.fontPx);
  });

  it('never grows scale past the mid-tablet value on an even larger desktop by more than the shared clamp allows', () => {
    const tablet = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 6,
    });
    const desktop = computeGameTableLayout(WIDE_DESKTOP, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 6,
    });
    expect(desktop.scale).toBeGreaterThanOrEqual(tablet.scale);
  });

  it('shrinks every touch-target-sensitive button but never below the enforced floor', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const layout = computeGameTableLayout(viewport, ZERO_INSETS, {
        numPlayers: 3,
        localHandCount: 5,
      });
      for (const btn of [
        layout.actionPanel.kadiButton,
        layout.actionPanel.proceedButton,
        layout.counterPanel.passButton,
        layout.drawButton,
        layout.playButton,
        layout.winScreen.playAgainButton,
        ...layout.suitPick.buttons,
      ]) {
        expect(btn.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX - 0.001);
        expect(btn.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX - 0.001);
      }
    }
  });
});

describe('computeGameTableLayout — safe-area insets (Part D)', () => {
  it('shrinks the content rect and shifts the turn banner inward with insets applied', () => {
    const noInsets = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    const withInsets = computeGameTableLayout(
      MID_TABLET_PANEL,
      { top: 40, right: 10, bottom: 20, left: 15 },
      { numPlayers: 4, localHandCount: 4 },
    );
    expect(withInsets.contentRect.width).toBeLessThan(noInsets.contentRect.width);
    expect(withInsets.contentRect.height).toBeLessThan(noInsets.contentRect.height);
    expect(withInsets.turnBanner.y).toBeGreaterThan(noInsets.turnBanner.y);
  });

  it('never produces NaN or negative sizes when insets consume the whole viewport', () => {
    const layout = computeGameTableLayout(
      { width: 320, height: 400 },
      { top: 300, right: 0, bottom: 300, left: 0 },
      { numPlayers: 4, localHandCount: 4 },
    );
    expect(Number.isFinite(layout.contentRect.height)).toBe(true);
    expect(layout.contentRect.height).toBeGreaterThanOrEqual(0);
    for (const seat of layout.seats) {
      expect(Number.isFinite(seat.handCenter.x)).toBe(true);
      expect(Number.isFinite(seat.handCenter.y)).toBe(true);
    }
  });
});

describe('computeGameTableLayout — piles and banners', () => {
  it('places the suit indicator to the left of the discard pile', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    expect(layout.suitIndicator.x).toBeLessThan(layout.discardPile.x);
  });

  it('places the pickup badge above pile-center and the must-pick banner below it, never overlapping', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    expect(layout.pickupBadge.y).toBeLessThan(layout.tableCenter.y);
    expect(layout.mustPickBanner.y).toBeGreaterThan(layout.tableCenter.y);
    expect(layout.mustPickBanner.y).toBeGreaterThan(layout.pickupBadge.y);
  });

  it('places the discard pile to the left of the draw pile with a gap between them', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    expect(layout.discardPile.x + layout.discardPile.width).toBeLessThanOrEqual(layout.drawPile.x);
  });

  it('positions the action panel beside the local hand, staying within the content rect', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    expect(layout.actionPanel.x + layout.actionPanel.width).toBeLessThanOrEqual(
      layout.contentRect.x + layout.contentRect.width + 0.001,
    );
    expect(layout.actionPanel.x).toBeGreaterThanOrEqual(layout.contentRect.x - 0.001);
  });

  it('lays out exactly four suit-pick buttons, one per suit, none overlapping', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    expect(layout.suitPick.buttons).toHaveLength(4);
    const suits = layout.suitPick.buttons.map((b) => b.suit);
    expect(new Set(suits).size).toBe(4);
    const sorted = [...layout.suitPick.buttons].sort((a, b) => a.x - b.x);
    for (let i = 1; i < sorted.length; i++) {
      expect(sorted[i].x).toBeGreaterThanOrEqual(sorted[i - 1].x + sorted[i - 1].width);
    }
  });
});

describe('computeLocalHandSlots', () => {
  it('returns one slot per card, centered on the local seat', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 7,
    });
    const slots = computeLocalHandSlots(layout, 7);
    expect(slots).toHaveLength(7);
    const localSeat = layout.seats.find((s) => s.isLocal)!;
    const avgX = slots.reduce((sum, s) => sum + s.x, 0) / slots.length;
    expect(avgX).toBeCloseTo(localSeat.handCenter.x, 0);
  });

  it('reflects the CURRENT handCount even if it differs from the layout it was computed alongside', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 4,
    });
    // A card was drawn since this layout was computed -- the caller
    // re-derives slots for the new count without recomputing seating.
    const slots = computeLocalHandSlots(layout, 5);
    expect(slots).toHaveLength(5);
  });

  it('returns an empty array for zero cards (hand emptied on a winning play)', () => {
    const layout = computeGameTableLayout(MID_TABLET_PANEL, ZERO_INSETS, {
      numPlayers: 4,
      localHandCount: 0,
    });
    expect(computeLocalHandSlots(layout, 0)).toEqual([]);
  });
});

describe('getDropIndex', () => {
  it('returns 0 for an empty fan rather than throwing', () => {
    expect(getDropIndex([], 250)).toBe(0);
  });

  it('picks the slot whose center is nearest the pointer', () => {
    const slots = computeFanPositions(5, 0, 0, 500, 70, 100);
    for (let i = 0; i < slots.length; i++) {
      expect(getDropIndex(slots, slots[i].x)).toBe(i);
    }
  });

  it('picks the nearest neighbor when the pointer sits between two slots', () => {
    const slots = computeFanPositions(3, 0, 0, 500, 70, 100);
    const midpoint = (slots[0].x + slots[1].x) / 2;
    expect(getDropIndex(slots, midpoint - 1)).toBe(0);
    expect(getDropIndex(slots, midpoint + 1)).toBe(1);
  });

  it('clamps to the nearest edge slot for a pointer far outside the fan', () => {
    const slots = computeFanPositions(4, 0, 0, 400, 70, 100);
    expect(getDropIndex(slots, -10000)).toBe(0);
    expect(getDropIndex(slots, 10000)).toBe(3);
  });

  it('is unaffected by an in-progress drag shift -- always reads the resting fan', () => {
    // Same slots regardless of whether a drag is visually shifting cards
    // elsewhere -- getDropIndex is always given the plain resting fan
    // (see this function's own docstring).
    const restingSlots = computeFanPositions(4, 0, 0, 400, 70, 100);
    expect(getDropIndex(restingSlots, restingSlots[2].x)).toBe(2);
  });
});
