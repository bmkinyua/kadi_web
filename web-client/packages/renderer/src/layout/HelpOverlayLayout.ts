/**
 * KADI web-client — the shared Help Overlay ("?" button + scrollable
 * popup), as pure position/wrap math.
 *
 * Ported from rendering/widgets.py's `HelpOverlay` class (`_layout()`/
 * `_flow()`/`_max_scroll()`) and `make_help_button()`. Used identically
 * by all five screens that have one on the PC side -- Main Menu,
 * Mode Select (GameConfigScene), Chuo, Multiplayer Menu, and Gameplay
 * itself (GameTableScene) -- exactly as scenes.py's own five call
 * sites all construct a HelpOverlay the same way and differ only in
 * which HELP_SECTIONS they pass in. See HelpOverlay.ts (this
 * directory's sibling, the Phaser-facing wrapper) for the actual
 * GameObjects, and idleGlow.ts for the "stuck?" nudge timer this
 * overlay's button uses (a separate pure module, reused rather than
 * re-implemented here, same as scrollPhysics.ts is reused by every
 * scrolling scene rather than each having its own copy).
 *
 * TWO DELIBERATE DEPARTURES FROM THE PC ORIGINAL, same spirit as
 * RulesLayout.ts's own header note on why a translation instead of a
 * literal port in these two spots:
 *
 * 1. PANEL/CLOSE-BUTTON SIZING IS PORTED LITERALLY (NOT scaled by this
 *    renderer's own continuous `scale`) -- `_layout()`'s
 *    `min(680, sw-80)` / `min(560, sh-80)` / `close_sz = round(32*cs)`
 *    formulas already derive their own sizing directly from the raw
 *    canvas pixel dimensions (`cs = clamp(sw/1280, 0.7, 1.4)`), the
 *    same way a real pygame surface's width/height ARE its own pixel
 *    count. This renderer's canvas is exactly as real-pixel as that
 *    (Scale.RESIZE, no letterboxing -- see scale.ts's own header), so
 *    the same literal formulas apply directly to `viewport.width`/
 *    `viewport.height` here with no extra `scale` multiplication
 *    layered on top, same as the PC values apply directly to `sw`/
 *    `sh` there. The one addition: PC's minimum supported window is
 *    1024x640 (constants.py's RESOLUTIONS), so `sw-80`/`sh-80` never
 *    gets close to collapsing there; this renderer supports much
 *    narrower phone viewports, so a modest floor
 *    (MIN_PANEL_WIDTH/MIN_PANEL_HEIGHT below) is added purely as a
 *    safety net for viewports narrower than the PC ever had to handle
 *    -- it does not change the formula's behavior anywhere PC's own
 *    supported range already covers.
 * 2. THE "?" BUTTON'S OWN POSITION per screen is NOT ported at all --
 *    make_help_button()'s docstring says it matches "AudioControls'
 *    sfx/music toggle styling" and each of the five scenes.py call
 *    sites hand-places its `rect` next to that screen's own icon row.
 *    This web client has no AudioControls icon row anywhere (grepped:
 *    none of the five target scenes have one), so there is no
 *    existing anchor to slot next to. computeHelpButtonRect() below
 *    instead establishes ONE consistent anchor -- top-right corner of
 *    the screen's safe content rect -- used identically by all five
 *    scenes, which is what "port the shared widget, not the absence
 *    of a landmark that doesn't exist yet" comes down to in practice.
 *
 * PAD/HEADING_GAP/PARA_GAP/LINE_GAP below ARE scaled by `scale`, same
 * treatment RulesLayout.ts gives PC's own literal small pixel gaps
 * (its BASE_PAD_OUTER/BASE_CARD_GAP/etc.) -- these size real body-text
 * spacing, which does need to track this renderer's own font ladder
 * as `scale` changes, unlike the panel's own outer envelope above.
 *
 * IMAGE SECTIONS: PC's HelpOverlay accepts `('image', surface,
 * caption)` tuples inside a section's item list (see MAX_IMAGE_H
 * below, kept as a ported constant even though nothing uses it yet).
 * Two of the five real screens (Chuo, Gameplay) reference one each
 * (help_msomi_attach.png, help_drag_multicard.png). This pass does
 * NOT port image sections -- see HELP_CONTENT.ts's own header for why
 * (no image-asset pipeline exists anywhere in web-client yet) -- so
 * HelpSection.paragraphs below is plain `string[]`, not the PC's
 * mixed string/image-tuple list. Re-adding image support later is a
 * layout-module change (a new 'image' flow-item kind here) plus an
 * actual asset pipeline; it does not require touching this pass's
 * five wiring sites again.
 */
import type { Viewport } from './scale.js';
import { computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import type { RectLayout } from './InternetLobbyLayout.js';
import { estimateTextWidth, wrapText } from './RulesLayout.js';

/** A single screen's help content -- ported verbatim per-screen in
 * HELP_CONTENT.ts, not authored here. `paragraphs` is plain body text
 * only this pass (see this file's header on image sections). */
export interface HelpSection {
  heading: string;
  paragraphs: string[];
}

export interface HelpContent {
  title: string;
  sections: HelpSection[];
}

export interface HelpTextLine {
  x: number;
  y: number;
  fontPx: number;
  text: string;
}

export interface HelpSectionLayout {
  heading: HelpTextLine;
  bodyLines: HelpTextLine[];
}

export interface HelpOverlayFlow {
  panelRect: RectLayout;
  titleLine: HelpTextLine;
  closeButton: RectLayout;
  /** Absolute (screen-space) y where the scrollable body begins,
   * below the fixed title/close row -- mirrors `_layout()`'s implicit
   * `viewport.top` (`panel.top + 64` in draw()). */
  viewportTop: number;
  viewportHeight: number;
  sections: HelpSectionLayout[];
  /** Mirrors `_content_height` -- total stacked height of every
   * section, independent of scroll. */
  contentHeight: number;
  /** Mirrors `_max_scroll()`. */
  maxScroll: number;
  /** Null when everything fits (mirrors PC's own `if max_s > 0:`
   * guard around drawing a scrollbar at all). */
  scrollbarTrack: RectLayout | null;
  scrollbarThumb: RectLayout | null;
}

// ── ported verbatim from HelpOverlay's own class constants ──────────
const PAD = 26;
const HEADING_GAP = 14;
const PARA_GAP = 10;
const LINE_GAP = 4;
/** Ported but unused this pass -- see this file's header on image
 * sections not being ported yet. */
export const MAX_IMAGE_H = 260;

// ── panel/close-button geometry, literal port of `_layout()` -- see
// this file's header note #1 on why these are NOT `scale`-multiplied.
const PANEL_MAX_WIDTH = 680;
const PANEL_MAX_HEIGHT = 560;
const PANEL_MARGIN = 80;
/** Safety floor for viewports narrower than PC's own minimum
 * supported resolution ever required -- see this file's header. */
const MIN_PANEL_WIDTH = 260;
const MIN_PANEL_HEIGHT = 220;
const CLOSE_BUTTON_BASE = 32;
const CLOSE_BUTTON_INSET = 14;
const CLOSE_SCALE_MIN = 0.7;
const CLOSE_SCALE_MAX = 1.4;
const CLOSE_SCALE_REFERENCE_WIDTH = 1280;

/** `panel.top + 64` and `panel.height - 90` from draw()/`_max_scroll()`
 * -- the fixed title/close row height and bottom padding the
 * scrollable viewport band sits between. */
const VIEWPORT_TOP_OFFSET = 64;
const VIEWPORT_BOTTOM_RESERVE = 90;

const SCROLLBAR_WIDTH = 6;
const SCROLLBAR_RIGHT_INSET = 12;
const MIN_SCROLLBAR_THUMB = 24;

/** Wheel-notch / click-scroll step, ported from `_handle_event()`'s
 * literal `40` (both the mouse-wheel branch and the button-4/5
 * fallback branch use the same step). */
export const HELP_SCROLL_STEP = 40;

// ── the "?" button's own anchor -- see this file's header note #2 on
// why this is a fresh choice rather than a per-screen port.
const BASE_HELP_BUTTON_SIZE = 40;
const BASE_HELP_BUTTON_MARGIN = 12;

function lineHeight(fontPxValue: number): number {
  return Math.round(fontPxValue * 1.2);
}

/**
 * Where the "?" button sits -- top-right corner of the screen's own
 * safe content rect, consistent across all five screens (see this
 * file's header note #2). `contentRect` is passed in by the caller
 * (each scene already computes its own via getSafeContentRect() for
 * its main layout; passing it in here avoids computing it twice).
 */
export function computeHelpButtonRect(
  viewport: Viewport,
  contentRect: { x: number; y: number; width: number },
): RectLayout {
  const scale = computeLayoutScale(viewport);
  const size = enforceMinTouchTarget({
    width: BASE_HELP_BUTTON_SIZE * scale,
    height: BASE_HELP_BUTTON_SIZE * scale,
  });
  const margin = BASE_HELP_BUTTON_MARGIN * scale;
  return {
    x: contentRect.x + contentRect.width - size.width - margin,
    y: contentRect.y + margin,
    width: size.width,
    height: size.height,
  };
}

/**
 * Full popup flow: panel, title, close button, wrapped sections, and
 * scrollbar -- direct translation of `_layout()` + `_flow()` +
 * `_max_scroll()`, called together the same way draw()/handle_event()
 * both call `_layout()` fresh on every use, and HelpOverlay.ts's own
 * render() recomputes this on every scroll-offset change and resize
 * (same single-source-of-truth pattern as every other scene here).
 */
export function computeHelpOverlayFlow(
  viewport: Viewport,
  content: HelpContent,
  scrollOffset: number,
): HelpOverlayFlow {
  const scale = computeLayoutScale(viewport);
  const sw = viewport.width;
  const sh = viewport.height;

  const panelWidth = Math.max(MIN_PANEL_WIDTH, Math.min(PANEL_MAX_WIDTH, sw - PANEL_MARGIN));
  const panelHeight = Math.max(MIN_PANEL_HEIGHT, Math.min(PANEL_MAX_HEIGHT, sh - PANEL_MARGIN));
  const panelRect: RectLayout = {
    x: (sw - panelWidth) / 2,
    y: (sh - panelHeight) / 2,
    width: panelWidth,
    height: panelHeight,
  };

  const titleFontPx = fontPx('ui_large', scale);
  const titleLine: HelpTextLine = {
    x: panelRect.x + PAD * scale,
    y: panelRect.y + 16 * scale,
    fontPx: titleFontPx,
    text: content.title,
  };

  const cs = Math.min(CLOSE_SCALE_MAX, Math.max(CLOSE_SCALE_MIN, sw / CLOSE_SCALE_REFERENCE_WIDTH));
  const closeBase = Math.round(CLOSE_BUTTON_BASE * cs);
  const closeSize = enforceMinTouchTarget({ width: closeBase, height: closeBase });
  const closeButton: RectLayout = {
    x: panelRect.x + panelRect.width - closeSize.width - CLOSE_BUTTON_INSET * scale,
    y: panelRect.y + CLOSE_BUTTON_INSET * scale,
    width: closeSize.width,
    height: closeSize.height,
  };

  const viewportTop = panelRect.y + VIEWPORT_TOP_OFFSET * scale;
  const viewportHeight = Math.max(0, panelRect.height - VIEWPORT_BOTTOM_RESERVE * scale);

  const pad = PAD * scale;
  const headingGap = HEADING_GAP * scale;
  const paraGap = PARA_GAP * scale;
  const lineGap = LINE_GAP * scale;

  const headingFontPx = fontPx('ui_medium', scale);
  const bodyFontPx = fontPx('ui_normal', scale);
  const headingLineH = lineHeight(headingFontPx);
  const bodyLineH = lineHeight(bodyFontPx);

  const textWidth = panelRect.width - 2 * pad;
  const baseX = panelRect.x + pad;
  const top0 = viewportTop - scrollOffset;
  let y = top0;
  const sections: HelpSectionLayout[] = [];

  for (const section of content.sections) {
    const headingLine: HelpTextLine = { x: baseX, y, fontPx: headingFontPx, text: section.heading };
    y += headingLineH + headingGap;

    const bodyLines: HelpTextLine[] = [];
    for (const para of section.paragraphs) {
      const lines = wrapText(para, bodyFontPx, textWidth);
      for (const line of lines) {
        bodyLines.push({ x: baseX, y, fontPx: bodyFontPx, text: line });
        y += bodyLineH + lineGap;
      }
      y += paraGap;
    }
    sections.push({ heading: headingLine, bodyLines });
  }

  const contentHeight = y - top0;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  let scrollbarTrack: RectLayout | null = null;
  let scrollbarThumb: RectLayout | null = null;
  if (maxScroll > 0) {
    const trackWidth = SCROLLBAR_WIDTH * scale;
    scrollbarTrack = {
      x: panelRect.x + panelRect.width - SCROLLBAR_RIGHT_INSET * scale - trackWidth,
      y: viewportTop,
      width: trackWidth,
      height: viewportHeight,
    };
    const thumbHeight = Math.max(
      MIN_SCROLLBAR_THUMB * scale,
      (viewportHeight * viewportHeight) / contentHeight,
    );
    const clampedScroll = Math.max(0, Math.min(maxScroll, scrollOffset));
    const thumbY = scrollbarTrack.y + (viewportHeight - thumbHeight) * (clampedScroll / maxScroll);
    scrollbarThumb = { x: scrollbarTrack.x, y: thumbY, width: trackWidth, height: thumbHeight };
  }

  return {
    panelRect,
    titleLine,
    closeButton,
    viewportTop,
    viewportHeight,
    sections,
    contentHeight,
    maxScroll,
    scrollbarTrack,
    scrollbarThumb,
  };
}

/** Re-exported so HELP_CONTENT.ts and tests can measure/wrap content
 * without importing RulesLayout.ts directly for a HelpOverlay-specific
 * reason. */
export { estimateTextWidth, wrapText };
