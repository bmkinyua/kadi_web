import { describe, expect, it } from 'vitest';
import {
  CHUO_TABS,
  computeChuoFlow,
  computeChuoTitleLayout,
  type ChuoRowInput,
} from '../ChuoLayout.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };
const PHONE: { width: number; height: number } = { width: 390, height: 780 };

describe('computeChuoTitleLayout', () => {
  it('centers the title horizontally within the content rect', () => {
    const layout = computeChuoTitleLayout(PHONE, ZERO_INSETS);
    expect(layout.x).toBeCloseTo(PHONE.width / 2, 0);
  });
});

describe('computeChuoFlow — tabs', () => {
  it('produces one tab button per CHUO_TABS entry, in order', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', [], 0);
    expect(flow.tabButtons.map((t) => t.id)).toEqual(CHUO_TABS.map((t) => t.id));
  });

  it('marks only the active tab as active', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'features', [], 0);
    for (const tab of flow.tabButtons) {
      expect(tab.active).toBe(tab.id === 'features');
    }
  });

  it('lays tab buttons left to right with no overlap', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', [], 0);
    for (let i = 1; i < flow.tabButtons.length; i += 1) {
      const prev = flow.tabButtons[i - 1];
      const cur = flow.tabButtons[i];
      expect(cur.rect.x).toBeGreaterThanOrEqual(prev.rect.x + prev.rect.width);
    }
  });
});

describe('computeChuoFlow — checkbox rows (Data/Features tabs)', () => {
  const rows: ChuoRowInput[] = [
    { kind: 'checkbox', key: 'log1', label: 'LOG_1.jsonl', sublabel: '2.1 KB', checked: true },
    { kind: 'checkbox', key: 'log2', label: 'LOG_2.jsonl', sublabel: '900 B', checked: false },
  ];

  it('produces one positioned row per input row, in order', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 0);
    expect(flow.rows).toHaveLength(2);
    expect(flow.rows[0].input.key).toBe('log1');
    expect(flow.rows[1].input.key).toBe('log2');
  });

  it('stacks checkbox rows top to bottom with no overlap', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 0);
    const [first, second] = flow.rows;
    expect(second.rowRect.y).toBeGreaterThanOrEqual(first.rowRect.y + first.rowRect.height);
  });

  it('places the checkbox before the label horizontally', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 0);
    const row = flow.rows[0];
    if (row.kind !== 'checkbox') throw new Error('expected checkbox row');
    expect(row.checkboxRect.x).toBeLessThan(row.labelPos.x);
  });

  it('only produces a sublabel position when the input has a sublabel', () => {
    const noSublabel: ChuoRowInput[] = [{ kind: 'checkbox', key: 'f', label: 'has_skip', checked: true }];
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'features', noSublabel, 0);
    const row = flow.rows[0];
    if (row.kind !== 'checkbox') throw new Error('expected checkbox row');
    expect(row.sublabelPos).toBeNull();
  });
});

describe('computeChuoFlow — number rows (Model tab)', () => {
  const rows: ChuoRowInput[] = [
    { kind: 'number', key: 'human_weight', label: 'Human decision weight', value: 2, unit: 'x' },
    { kind: 'number', key: 'iterations', label: 'Training iterations', value: 300, unit: '' },
  ];

  it('places decrement before increment, both to the right of the label', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'model', rows, 0);
    const row = flow.rows[0];
    if (row.kind !== 'number') throw new Error('expected number row');
    expect(row.decrementRect.x).toBeLessThan(row.incrementRect.x);
    expect(row.decrementRect.x).toBeGreaterThan(row.labelPos.x);
  });
});

describe('computeChuoFlow — model rows (Train & Results tab, saved models list)', () => {
  const rows: ChuoRowInput[] = [{ kind: 'model', key: 'msomi_2026.json', label: 'msomi_2026.json' }];

  it('places delete to the right of load, both to the right of the label', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'results', rows, 0);
    const row = flow.rows[0];
    if (row.kind !== 'model') throw new Error('expected model row');
    expect(row.loadButton.x).toBeGreaterThan(row.labelPos.x);
    expect(row.deleteButton.x).toBeGreaterThan(row.loadButton.x);
  });
});

describe('computeChuoFlow — text rows wrap and stack height correctly', () => {
  it('wraps a long status/results line into multiple RulesTextLine entries', () => {
    const longText =
      'Trained on 128 decisions (94 human, 34 AI). Agreement: 87% overall, 91% on human-only decisions.';
    const rows: ChuoRowInput[] = [{ kind: 'text', key: 'results', text: longText }];
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'results', rows, 0);
    const row = flow.rows[0];
    if (row.kind !== 'text') throw new Error('expected text row');
    expect(row.lines.length).toBeGreaterThan(1);
    // Re-joining the wrapped lines (space-separated) should reconstruct
    // the original words with nothing dropped.
    expect(row.lines.map((l) => l.text).join(' ')).toBe(longText);
  });
});

describe('computeChuoFlow — scroll geometry', () => {
  it('maxScroll is 0 when all rows fit in the viewport', () => {
    const rows: ChuoRowInput[] = [{ kind: 'checkbox', key: 'only', label: 'one row', checked: true }];
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 0);
    expect(flow.maxScroll).toBe(0);
  });

  it('maxScroll grows past 0 once enough rows overflow the viewport', () => {
    const manyRows: ChuoRowInput[] = Array.from({ length: 40 }, (_, i) => ({
      kind: 'checkbox' as const,
      key: `log${i}`,
      label: `LOG_${i}.jsonl`,
      checked: false,
    }));
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', manyRows, 0);
    expect(flow.maxScroll).toBeGreaterThan(0);
  });

  it('scrolling shifts every row upward by exactly scrollOffset, contentHeight unchanged', () => {
    const rows: ChuoRowInput[] = Array.from({ length: 5 }, (_, i) => ({
      kind: 'checkbox' as const,
      key: `log${i}`,
      label: `LOG_${i}.jsonl`,
      checked: false,
    }));
    const flowAtZero = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 0);
    const flowScrolled = computeChuoFlow(PHONE, ZERO_INSETS, 'data', rows, 50);
    expect(flowScrolled.contentHeight).toBeCloseTo(flowAtZero.contentHeight, 5);
    for (let i = 0; i < rows.length; i += 1) {
      expect(flowAtZero.rows[i].rowRect.y - flowScrolled.rows[i].rowRect.y).toBeCloseTo(50, 5);
    }
  });
});

describe('computeChuoFlow — back button and backend label', () => {
  it('anchors the back button near the bottom-left of the content rect', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', [], 0);
    expect(flow.backButton.y + flow.backButton.height).toBeLessThanOrEqual(
      flow.contentRect.y + flow.contentRect.height + 1,
    );
    expect(flow.backButton.x).toBeGreaterThanOrEqual(flow.contentRect.x);
  });

  it('places the backend label on the same row as the back button, to its right', () => {
    const flow = computeChuoFlow(PHONE, ZERO_INSETS, 'data', [], 0);
    expect(flow.backendLabelPos.x).toBeGreaterThan(flow.backButton.x);
  });
});
