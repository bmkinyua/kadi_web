import { describe, expect, it } from 'vitest';
import {
  RULES_SECTIONS,
  computeRulesFlow,
  computeRulesTitleLayout,
  estimateTextWidth,
  wrapText,
} from '../RulesLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

describe('estimateTextWidth', () => {
  it('grows with text length at a fixed font size', () => {
    expect(estimateTextWidth('hello world', 16)).toBeGreaterThan(estimateTextWidth('hello', 16));
  });

  it('grows with font size at a fixed text length', () => {
    expect(estimateTextWidth('hello', 24)).toBeGreaterThan(estimateTextWidth('hello', 12));
  });

  it('is zero for empty text', () => {
    expect(estimateTextWidth('', 16)).toBe(0);
  });
});

describe('wrapText', () => {
  it('returns a single line when the text already fits', () => {
    const lines = wrapText('short line', 16, 1000);
    expect(lines).toEqual(['short line']);
  });

  it('wraps onto multiple lines when the text exceeds maxWidth', () => {
    const text = 'one two three four five six seven eight nine ten';
    const lines = wrapText(text, 16, 80);
    expect(lines.length).toBeGreaterThan(1);
    // Every line individually must fit (this is the whole contract).
    for (const line of lines) {
      expect(estimateTextWidth(line, 16)).toBeLessThanOrEqual(80 + 0.001);
    }
  });

  it('reassembles to the original text when lines are rejoined with spaces', () => {
    const text = 'the quick brown fox jumps over the lazy dog';
    const lines = wrapText(text, 14, 60);
    expect(lines.join(' ')).toBe(text);
  });

  it('never drops a word, even across many lines', () => {
    const text = RULES_SECTIONS[1][1][2]; // the long Jump (J) paragraph
    const lines = wrapText(text, 16, 120);
    expect(lines.join(' ')).toBe(text);
  });

  it('breaks an unbreakable single word at a character boundary rather than overflowing', () => {
    const unbreakable = 'a'.repeat(200);
    const lines = wrapText(unbreakable, 16, 100);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join('')).toBe(unbreakable);
    for (const line of lines) {
      expect(estimateTextWidth(line, 16)).toBeLessThanOrEqual(100 + 0.001);
    }
  });

  it('handles an empty string as zero lines', () => {
    expect(wrapText('', 16, 100)).toEqual([]);
  });
});

describe('RULES_SECTIONS', () => {
  it('has the expected six sections in the expected order (content is asserted verbatim by hand at review time)', () => {
    const titles = RULES_SECTIONS.map(([title]) => title);
    expect(titles).toEqual([
      'The Basics',
      'Card Effects',
      'Pick-up Chains',
      'Playing Multiple Cards',
      'Declaring KADI & Winning',
      'Settings That Change The Rules',
    ]);
  });

  it('every section has at least one paragraph', () => {
    for (const [, paragraphs] of RULES_SECTIONS) {
      expect(paragraphs.length).toBeGreaterThan(0);
    }
  });
});

describe('computeRulesFlow', () => {
  it('produces one panel per section, matching RULES_SECTIONS length and order', () => {
    const flow = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(flow.sections).toHaveLength(RULES_SECTIONS.length);
    flow.sections.forEach((section, i) => {
      expect(section.title.text).toBe(RULES_SECTIONS[i][0]);
    });
  });

  it('stacks panels strictly top-to-bottom with no overlap', () => {
    const flow = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    for (let i = 1; i < flow.sections.length; i++) {
      const prev = flow.sections[i - 1].panelRect;
      const cur = flow.sections[i].panelRect;
      expect(cur.y).toBeGreaterThanOrEqual(prev.y + prev.height);
    }
  });

  it('places the back button below the last section panel', () => {
    const flow = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const last = flow.sections[flow.sections.length - 1].panelRect;
    expect(flow.backButton.y).toBeGreaterThanOrEqual(last.y + last.height);
  });

  it('every body line sits inside its own panel horizontally', () => {
    const flow = computeRulesFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    for (const section of flow.sections) {
      for (const line of section.bodyLines) {
        expect(line.x).toBeGreaterThanOrEqual(section.panelRect.x);
        expect(line.x).toBeLessThan(section.panelRect.x + section.panelRect.width);
      }
    }
  });

  it('shifts every y position by exactly the scroll delta, leaving contentHeight/maxScroll unchanged', () => {
    const flowA = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const flowB = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 120);

    expect(flowB.contentHeight).toBeCloseTo(flowA.contentHeight, 5);
    expect(flowB.maxScroll).toBeCloseTo(flowA.maxScroll, 5);

    for (let i = 0; i < flowA.sections.length; i++) {
      expect(flowB.sections[i].panelRect.y).toBeCloseTo(flowA.sections[i].panelRect.y - 120, 5);
      expect(flowB.sections[i].title.y).toBeCloseTo(flowA.sections[i].title.y - 120, 5);
    }
    expect(flowB.backButton.y).toBeCloseTo(flowA.backButton.y - 120, 5);
  });

  it('scrollOffset never changes the wrapping itself (line count/text per section is scroll-independent)', () => {
    const flowA = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const flowB = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 500);
    for (let i = 0; i < flowA.sections.length; i++) {
      expect(flowB.sections[i].bodyLines.map((l) => l.text)).toEqual(
        flowA.sections[i].bodyLines.map((l) => l.text),
      );
    }
  });

  it('maxScroll is 0 when all content already fits inside a very tall viewport', () => {
    const flow = computeRulesFlow({ width: 1024, height: 20000 }, ZERO_INSETS, 0);
    expect(flow.maxScroll).toBe(0);
  });

  it('maxScroll is positive when content overflows a short viewport', () => {
    const flow = computeRulesFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    expect(flow.maxScroll).toBeGreaterThan(0);
  });

  it('maxScroll equals contentHeight - viewportHeight whenever content overflows', () => {
    const flow = computeRulesFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    if (flow.contentHeight > flow.viewportHeight) {
      expect(flow.maxScroll).toBeCloseTo(flow.contentHeight - flow.viewportHeight, 5);
    }
  });

  it('grows font sizes and card width when the viewport grows', () => {
    const phone = computeRulesFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    const tablet = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(tablet.scale).toBeGreaterThan(phone.scale);
    expect(tablet.sections[0].title.fontPx).toBeGreaterThan(phone.sections[0].title.fontPx);
    expect(tablet.cardWidth).toBeGreaterThan(phone.cardWidth);
  });

  it('caps card width well short of the full viewport on a very wide desktop', () => {
    const flow = computeRulesFlow(WIDE_DESKTOP, ZERO_INSETS, 0);
    expect(flow.cardWidth).toBeLessThan(flow.contentRect.width * 0.8);
  });

  it('keeps the card centered horizontally at every viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const flow = computeRulesFlow(viewport, ZERO_INSETS, 0);
      const contentCenter = flow.contentRect.x + flow.contentRect.width / 2;
      const cardCenter = flow.sections[0].panelRect.x + flow.sections[0].panelRect.width / 2;
      expect(cardCenter).toBeCloseTo(contentCenter, 1);
    }
  });

  it('the back button meets the minimum touch-target size at every viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const flow = computeRulesFlow(viewport, ZERO_INSETS, 0);
      expect(flow.backButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(flow.backButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('respects safe-area insets by shifting contentRect and viewportTop inward', () => {
    const insets = { top: 40, right: 10, bottom: 20, left: 10 };
    const withInsets = computeRulesFlow(MID_TABLET_PANEL, insets, 0);
    const without = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(withInsets.contentRect.y).toBe(40);
    expect(withInsets.viewportTop).toBeGreaterThan(without.viewportTop);
  });

  it('viewportTop sits below the fixed title (computeRulesTitleLayout)', () => {
    const flow = computeRulesFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const title = computeRulesTitleLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(flow.viewportTop).toBeGreaterThan(title.y + title.fontPx);
  });
});
