import { describe, expect, it } from 'vitest';
import {
  HELP_SCROLL_STEP,
  computeHelpButtonRect,
  computeHelpOverlayFlow,
  type HelpContent,
} from '../HelpOverlayLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';
import { getSafeContentRect } from '../safeArea.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

const SHORT_CONTENT: HelpContent = {
  title: 'Main Menu',
  sections: [{ heading: 'Getting Started', paragraphs: ['A short paragraph that easily fits on one screen.'] }],
};

function longContent(sectionCount: number): HelpContent {
  return {
    title: 'Gameplay',
    sections: Array.from({ length: sectionCount }, (_, i) => ({
      heading: `Section ${i + 1}`,
      paragraphs: [
        'A reasonably long paragraph of body text meant to wrap across ' +
          'several lines once it is laid out inside the overlay panel, ' +
          'so this file can exercise real multi-section scroll behavior.',
        'A second paragraph in the same section, to make sure paragraph ' +
          'gaps stack correctly across more than one paragraph per section.',
      ],
    })),
  };
}

describe('computeHelpButtonRect', () => {
  it('anchors to the top-right corner of the content rect', () => {
    const contentRect = getSafeContentRect(MID_TABLET_PANEL, ZERO_INSETS);
    const rect = computeHelpButtonRect(MID_TABLET_PANEL, contentRect);
    // Right edge of the button should sit inside, near the right edge of content.
    expect(rect.x + rect.width).toBeLessThanOrEqual(contentRect.x + contentRect.width);
    expect(rect.x + rect.width).toBeGreaterThan(contentRect.x + contentRect.width - 60);
    // Near the top.
    expect(rect.y).toBeGreaterThanOrEqual(contentRect.y);
    expect(rect.y).toBeLessThan(contentRect.y + 60);
  });

  it('respects safe-area insets (does not sit under a notch)', () => {
    const insets = { top: 40, right: 20, bottom: 0, left: 0 };
    const contentRect = getSafeContentRect(NARROW_PHONE_PORTRAIT, insets);
    const rect = computeHelpButtonRect(NARROW_PHONE_PORTRAIT, contentRect);
    expect(rect.y).toBeGreaterThanOrEqual(contentRect.y);
    expect(rect.x + rect.width).toBeLessThanOrEqual(contentRect.x + contentRect.width);
  });

  it('never shrinks below the minimum touch target on a narrow phone', () => {
    const contentRect = getSafeContentRect(NARROW_PHONE_PORTRAIT, ZERO_INSETS);
    const rect = computeHelpButtonRect(NARROW_PHONE_PORTRAIT, contentRect);
    expect(rect.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    expect(rect.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
  });

  it('scales up on a very wide desktop viewport without leaving the corner', () => {
    const contentRect = getSafeContentRect(WIDE_DESKTOP, ZERO_INSETS);
    const rect = computeHelpButtonRect(WIDE_DESKTOP, contentRect);
    expect(rect.x + rect.width).toBeLessThanOrEqual(contentRect.x + contentRect.width);
  });
});

describe('computeHelpOverlayFlow — panel geometry', () => {
  it('centers the panel in the viewport', () => {
    const flow = computeHelpOverlayFlow(MID_TABLET_PANEL, SHORT_CONTENT, 0);
    const centerX = flow.panelRect.x + flow.panelRect.width / 2;
    const centerY = flow.panelRect.y + flow.panelRect.height / 2;
    expect(centerX).toBeCloseTo(MID_TABLET_PANEL.width / 2, 0);
    expect(centerY).toBeCloseTo(MID_TABLET_PANEL.height / 2, 0);
  });

  it('caps panel size on a very large desktop viewport (does not fill the whole screen)', () => {
    const flow = computeHelpOverlayFlow(WIDE_DESKTOP, SHORT_CONTENT, 0);
    expect(flow.panelRect.width).toBeLessThan(WIDE_DESKTOP.width * 0.5);
    expect(flow.panelRect.height).toBeLessThan(WIDE_DESKTOP.height * 0.5);
  });

  it('shrinks to fit (with margin) on a narrow phone rather than overflowing', () => {
    const flow = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, SHORT_CONTENT, 0);
    expect(flow.panelRect.width).toBeLessThanOrEqual(NARROW_PHONE_PORTRAIT.width);
    expect(flow.panelRect.height).toBeLessThanOrEqual(NARROW_PHONE_PORTRAIT.height);
    expect(flow.panelRect.x).toBeGreaterThanOrEqual(0);
    expect(flow.panelRect.y).toBeGreaterThanOrEqual(0);
  });

  it('keeps the close button inside the panel and touch-target sized', () => {
    const flow = computeHelpOverlayFlow(MID_TABLET_PANEL, SHORT_CONTENT, 0);
    expect(flow.closeButton.x).toBeGreaterThanOrEqual(flow.panelRect.x);
    expect(flow.closeButton.x + flow.closeButton.width).toBeLessThanOrEqual(flow.panelRect.x + flow.panelRect.width);
    expect(flow.closeButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    expect(flow.closeButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
  });
});

describe('computeHelpOverlayFlow — section flow / wrapping', () => {
  it('produces one section layout per content section', () => {
    const flow = computeHelpOverlayFlow(MID_TABLET_PANEL, longContent(3), 0);
    expect(flow.sections).toHaveLength(3);
  });

  it('wraps long paragraphs onto multiple lines', () => {
    const flow = computeHelpOverlayFlow(MID_TABLET_PANEL, longContent(1), 0);
    expect(flow.sections[0].bodyLines.length).toBeGreaterThan(2);
  });

  it('stacks sections top-to-bottom without overlap', () => {
    const flow = computeHelpOverlayFlow(MID_TABLET_PANEL, longContent(3), 0);
    for (let i = 1; i < flow.sections.length; i++) {
      const prevLast = flow.sections[i - 1].bodyLines.at(-1)!;
      const thisHeading = flow.sections[i].heading;
      expect(thisHeading.y).toBeGreaterThan(prevLast.y);
    }
  });

  it('reports zero maxScroll when everything fits in the viewport', () => {
    const flow = computeHelpOverlayFlow(WIDE_DESKTOP, SHORT_CONTENT, 0);
    expect(flow.maxScroll).toBe(0);
    expect(flow.scrollbarTrack).toBeNull();
    expect(flow.scrollbarThumb).toBeNull();
  });

  it('reports a positive maxScroll and a scrollbar when content overflows', () => {
    const flow = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, longContent(8), 0);
    expect(flow.maxScroll).toBeGreaterThan(0);
    expect(flow.scrollbarTrack).not.toBeNull();
    expect(flow.scrollbarThumb).not.toBeNull();
  });

  it('scrolling shifts every section upward by exactly scrollOffset', () => {
    const flowAtZero = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, longContent(8), 0);
    const flowScrolled = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, longContent(8), HELP_SCROLL_STEP);
    expect(flowAtZero.sections[0].heading.y - flowScrolled.sections[0].heading.y).toBeCloseTo(HELP_SCROLL_STEP, 0);
  });

  it('the scrollbar thumb moves down as scrollOffset increases', () => {
    const content = longContent(8);
    const flowAtZero = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, content, 0);
    const flowAtMax = computeHelpOverlayFlow(NARROW_PHONE_PORTRAIT, content, flowAtZero.maxScroll);
    expect(flowAtMax.scrollbarThumb!.y).toBeGreaterThan(flowAtZero.scrollbarThumb!.y);
  });

  it('contentHeight and maxScroll stay identical regardless of scrollOffset (only positions shift)', () => {
    const content = longContent(5);
    const flowA = computeHelpOverlayFlow(MID_TABLET_PANEL, content, 0);
    const flowB = computeHelpOverlayFlow(MID_TABLET_PANEL, content, 123);
    expect(flowA.contentHeight).toBeCloseTo(flowB.contentHeight, 6);
    expect(flowA.maxScroll).toBeCloseTo(flowB.maxScroll, 6);
  });
});
