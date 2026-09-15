import { describe, expect, it } from 'vitest';
import { computeGameConfigFlow, MAX_OPPONENTS, MIN_OPPONENTS } from '../GameConfigLayout.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const SHORT_PHONE = { width: 360, height: 500 };

function flow(overrides: Partial<Parameters<typeof computeGameConfigFlow>[3]> = {}, scrollOffset = 0) {
  return computeGameConfigFlow(MID_TABLET_PANEL, ZERO_INSETS, scrollOffset, {
    vsAi: true,
    opponentCount: 3,
    eliminationMode: false,
    ...overrides,
  });
}

describe('computeGameConfigFlow', () => {
  it('opponent count is 1-5, never 0 -- matches the real PC _opp_buttons list, not a spectator-mode misread', () => {
    const f = flow();
    const countRow = f.rows.find((r) => r.kind === 'opponentCount');
    expect(countRow).toBeDefined();
    if (countRow?.kind === 'opponentCount') {
      expect(countRow.buttons.map((b) => b.n)).toEqual([1, 2, 3, 4, 5]);
      expect(MIN_OPPONENTS).toBe(1);
      expect(MAX_OPPONENTS).toBe(5);
    }
  });

  it('vsAi=true shows difficulty + MSOMI rows, never local hot-seat name fields', () => {
    const f = flow({ vsAi: true });
    expect(f.rows.some((r) => r.kind === 'difficulty')).toBe(true);
    expect(f.rows.some((r) => r.kind === 'msomi')).toBe(true);
    expect(f.rows.some((r) => r.kind === 'textfield' && r.id.startsWith('local:'))).toBe(false);
  });

  it('vsAi=false shows one hot-seat name field per opponent, never difficulty/MSOMI', () => {
    const f = flow({ vsAi: false, opponentCount: 4 });
    const localFields = f.rows.filter((r) => r.kind === 'textfield' && r.id.startsWith('local:'));
    expect(localFields).toHaveLength(4);
    expect(f.rows.some((r) => r.kind === 'difficulty')).toBe(false);
    expect(f.rows.some((r) => r.kind === 'msomi')).toBe(false);
  });

  it('hot-seat field count tracks opponentCount exactly, clamped to 1-5', () => {
    for (const n of [1, 2, 3, 4, 5]) {
      const f = flow({ vsAi: false, opponentCount: n });
      const localFields = f.rows.filter((r) => r.kind === 'textfield' && r.id.startsWith('local:'));
      expect(localFields).toHaveLength(n);
    }
    const clampedHigh = flow({ vsAi: false, opponentCount: 9 });
    expect(clampedHigh.rows.filter((r) => r.kind === 'textfield' && r.id.startsWith('local:'))).toHaveLength(5);
    const clampedLow = flow({ vsAi: false, opponentCount: 0 });
    expect(clampedLow.rows.filter((r) => r.kind === 'textfield' && r.id.startsWith('local:'))).toHaveLength(1);
  });

  it('always includes exactly one "Your Name" text field regardless of mode', () => {
    for (const vsAi of [true, false]) {
      const f = flow({ vsAi });
      const nameFields = f.rows.filter((r) => r.kind === 'textfield' && r.id === 'playerName');
      expect(nameFields).toHaveLength(1);
    }
  });

  it('always includes an Elimination Mode toggle, in both modes', () => {
    for (const vsAi of [true, false]) {
      const f = flow({ vsAi });
      expect(f.rows.some((r) => r.kind === 'toggle' && r.id === 'eliminationMode')).toBe(true);
    }
  });

  it('AI-only-continue sub-toggle only appears for vsAi + eliminationMode both true', () => {
    expect(flow({ vsAi: true, eliminationMode: false }).rows.some((r) => r.kind === 'toggle' && r.id === 'eliminationAiOnlyContinue')).toBe(false);
    expect(flow({ vsAi: false, eliminationMode: true }).rows.some((r) => r.kind === 'toggle' && r.id === 'eliminationAiOnlyContinue')).toBe(false);
    expect(flow({ vsAi: true, eliminationMode: true }).rows.some((r) => r.kind === 'toggle' && r.id === 'eliminationAiOnlyContinue')).toBe(true);
  });

  it('scroll offset shifts every row upward by the same amount, without changing maxScroll', () => {
    const base = flow({ vsAi: false, opponentCount: 5 }, 0);
    const scrolled = flow({ vsAi: false, opponentCount: 5 }, 40);
    expect(scrolled.maxScroll).toBe(base.maxScroll);
    const baseName = base.rows.find((r) => r.kind === 'textfield' && r.id === 'playerName');
    const scrolledName = scrolled.rows.find((r) => r.kind === 'textfield' && r.id === 'playerName');
    if (baseName?.kind === 'textfield' && scrolledName?.kind === 'textfield') {
      expect(baseName.box.y - scrolledName.box.y).toBeCloseTo(40, 5);
    }
  });

  it('maxScroll grows with a shorter viewport and with more hot-seat fields', () => {
    const shortMax = computeGameConfigFlow(SHORT_PHONE, ZERO_INSETS, 0, {
      vsAi: false,
      opponentCount: 5,
      eliminationMode: true,
    }).maxScroll;
    const tallMax = computeGameConfigFlow(MID_TABLET_PANEL, ZERO_INSETS, 0, {
      vsAi: false,
      opponentCount: 1,
      eliminationMode: false,
    }).maxScroll;
    expect(shortMax).toBeGreaterThan(tallMax);
  });

  it('Start button always sits above Back, both below every row', () => {
    const f = flow({ vsAi: true, eliminationMode: true });
    expect(f.backButton.y).toBeGreaterThan(f.startButton.y);
    for (const row of f.rows) {
      const rowBottom =
        row.kind === 'note'
          ? Math.max(...row.lines.map((l) => l.y))
          : row.kind === 'textfield'
            ? row.box.y + row.box.height
            : row.kind === 'opponentCount'
              ? Math.max(...row.buttons.map((b) => b.rect.y + b.rect.height))
              : row.kind === 'difficulty'
                ? Math.max(...row.buttons.map((b) => b.rect.y + b.rect.height))
                : row.kind === 'msomi'
                  ? row.toggle.y + row.toggle.height
                  : row.button.y + row.button.height;
      expect(f.startButton.y).toBeGreaterThanOrEqual(rowBottom - 1);
    }
  });
});
