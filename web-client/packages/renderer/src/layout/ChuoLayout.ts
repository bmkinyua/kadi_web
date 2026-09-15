/**
 * KADI web-client — Chuo (MSOMI train-your-own-AI) scene layout, as
 * pure data. Ported from scenes.ChuoScene (scenes.py) — see that
 * class's own docstring: four tabs left to right (Data, Features,
 * Model, Train & Results), everything reading/writing local
 * logs/models, nothing touching a game in progress.
 *
 * ONE UNIFIED ROW LIST, NOT FOUR BESPOKE TAB LAYOUTS: the PC scene
 * pins its per-tab action buttons (Select All/None, Load, Browse,
 * Train, Save) above a separately-scrolling list. This module instead
 * puts everything for the active tab — action buttons included — into
 * one ordered `rows` array that scrolls together, the same
 * simplification SettingsLayout.ts already made for its own
 * stacked-cards-of-controls shape (see that file's own comments on
 * why a phone-width column doesn't need pinned headers the way a
 * desktop window with room to spare does). ChuoScene.ts is
 * responsible for building the right `rows` array for whichever tab
 * is active; this module only knows how to lay out whatever list it's
 * given.
 *
 * ROW_H / LIST_VISIBLE_ROWS below are copied from ChuoScene's own
 * class constants (`ROW_H = 40`, `LIST_VISIBLE_ROWS = 8`) — genuine
 * parity, not a coincidence.
 *
 * SCROLL PHYSICS come from ./scrollPhysics.ts, shared with Settings/
 * Rules/GameTable, same as scenes.py's own module-level scroll-bounce
 * helpers are shared across ChuoScene there.
 *
 * HELP OVERLAY: ported in a later pass (this delivery), closing the
 * scope cut noted below when this file was first written. See
 * HelpOverlay.ts/layout/HelpOverlayLayout.ts/layout/HELP_CONTENT.ts
 * (CHUO_HELP) and this scene's own header. NOT included: the MSOMI-
 * attach illustration splice (`help_msomi_attach.png`) -- flagged,
 * not silently dropped, in HELP_CONTENT.ts's own header (no image-
 * asset pipeline exists anywhere in this web client yet).
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { RectLayout } from './InternetLobbyLayout.js';
import { estimateTextWidth, wrapText, type RulesTextLine } from './RulesLayout.js';

export type ChuoTabId = 'data' | 'features' | 'model' | 'results';

export const CHUO_TABS: { id: ChuoTabId; label: string }[] = [
  { id: 'data', label: 'Data' },
  { id: 'features', label: 'Features' },
  { id: 'model', label: 'Model' },
  { id: 'results', label: 'Train & Results' },
];

export interface ChuoTabButton {
  id: ChuoTabId;
  label: string;
  rect: RectLayout;
  active: boolean;
}

/** A row the active tab wants rendered, in order — ChuoScene.ts builds
 * this list from its own state (log/feature/model selection, training
 * status); this module only lays whatever it's given out top-to-bottom. */
export type ChuoRowInput =
  | { kind: 'checkbox'; key: string; label: string; sublabel?: string; checked: boolean }
  | { kind: 'button'; key: string; label: string; enabled: boolean; variant?: 'primary' | 'danger' | 'default' }
  | { kind: 'number'; key: string; label: string; value: number; unit: string }
  | { kind: 'tier'; key: string; label: string; selected: boolean; enabled: boolean }
  | { kind: 'text'; key: string; text: string }
  | { kind: 'model'; key: string; label: string };

interface BaseRow {
  input: ChuoRowInput;
  rowRect: RectLayout;
  labelPos: TextLayout;
}

export interface ChuoCheckboxRow extends BaseRow {
  kind: 'checkbox';
  input: Extract<ChuoRowInput, { kind: 'checkbox' }>;
  checkboxRect: RectLayout;
  sublabelPos: TextLayout | null;
}

export interface ChuoButtonRow extends BaseRow {
  kind: 'button';
  input: Extract<ChuoRowInput, { kind: 'button' }>;
}

export interface ChuoNumberRow extends BaseRow {
  kind: 'number';
  input: Extract<ChuoRowInput, { kind: 'number' }>;
  decrementRect: RectLayout;
  incrementRect: RectLayout;
  valuePos: TextLayout;
}

export interface ChuoTierRow extends BaseRow {
  kind: 'tier';
  input: Extract<ChuoRowInput, { kind: 'tier' }>;
}

export interface ChuoTextRow extends BaseRow {
  kind: 'text';
  input: Extract<ChuoRowInput, { kind: 'text' }>;
  lines: RulesTextLine[];
}

export interface ChuoModelRow extends BaseRow {
  kind: 'model';
  input: Extract<ChuoRowInput, { kind: 'model' }>;
  loadButton: RectLayout;
  deleteButton: RectLayout;
}

export type ChuoPositionedRow =
  | ChuoCheckboxRow
  | ChuoButtonRow
  | ChuoNumberRow
  | ChuoTierRow
  | ChuoTextRow
  | ChuoModelRow;

export interface ChuoFlow {
  scale: number;
  contentRect: ContentRect;
  tabButtons: ChuoTabButton[];
  backButton: RectLayout;
  backendLabelPos: TextLayout;
  viewportTop: number;
  viewportHeight: number;
  rows: ChuoPositionedRow[];
  contentHeight: number;
  maxScroll: number;
}

// ── baseline constants — direct analogues of ChuoScene's own class
// constants and construction-block button sizes (scenes.py), at this
// renderer's own baseline scale rather than the PC's chrome_scale.
const BASE_TITLE_Y = 18;
const BASE_TAB_GAP = 8;
const BASE_TAB_ROW_GAP = 16;
const BASE_TOP_INSET = 8;
const BASE_BOTTOM_INSET = 16;
const BASE_ROW_H = 40; // ChuoScene.ROW_H
const BASE_ROW_GAP = 6;
const BASE_PAD_SIDE = 20;
const BASE_CHECKBOX_SIZE = 24;
const BASE_BACK_BUTTON_WIDTH = 140;
const BASE_BACK_BUTTON_HEIGHT = 44;
const BASE_MODEL_ACTION_WIDTH = 64;
const BASE_MODEL_ACTION_GAP = 8;
const BASE_NUMBER_STEP_SIZE = 32;
const BASE_TEXT_LINE_GAP = 4;

/** Natural content column width, same "one comfortably-wide column"
 * shape as RulesLayout's own BASE_CARD_WIDTH — Chuo's rows are lists
 * of controls, not prose, so this is a little wider than Rules' by
 * default (more room for a checkbox + label + sublabel on one line
 * without wrapping on a typical phone width). */
const BASE_CONTENT_WIDTH = 440;
const BASE_MIN_CONTENT_WIDTH = 320;
const BASE_CONTENT_SIDE_MARGIN = 20;

function computeContentWidth(contentRect: ContentRect, scale: number): number {
  const natural = BASE_CONTENT_WIDTH * scale;
  const capped = Math.min(natural, contentRect.width - 2 * BASE_CONTENT_SIDE_MARGIN * scale);
  return Math.max(BASE_MIN_CONTENT_WIDTH * scale, capped);
}

export function computeChuoTitleLayout(rawViewport: Viewport, insets: SafeAreaInsets): TextLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  return {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
}

/**
 * The one function ChuoScene.ts calls for every position/size, given
 * the active tab, that tab's row list, and the current scroll offset
 * — direct analogue of RulesLayout's computeRulesFlow() /
 * SettingsLayout's computeSettingsFlow(), same single-source-of-truth
 * discipline (called fresh on every scroll change and genuine resize).
 */
export function computeChuoFlow(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  activeTab: ChuoTabId,
  rowInputs: ChuoRowInput[],
  scrollOffset: number,
): ChuoFlow {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const titleFontPx = fontPx('ui_large', scale);
  const titleLineH = Math.round(titleFontPx * 1.2);
  const tabRowY = contentRect.y + BASE_TITLE_Y * scale + titleLineH + BASE_TAB_ROW_GAP * scale;
  const tabFontPx = fontPx('ui_normal', scale);
  const tabHeight = enforceMinTouchTarget({ width: 0, height: 40 * scale }).height;

  const tabGap = BASE_TAB_GAP * scale;
  const tabWidths = CHUO_TABS.map((t) => Math.max(70 * scale, estimateTextWidth(t.label, tabFontPx) + 24 * scale));
  const totalTabsWidth = tabWidths.reduce((a, b) => a + b, 0) + tabGap * (CHUO_TABS.length - 1);
  let tabX = centerX - totalTabsWidth / 2;
  const tabButtons: ChuoTabButton[] = CHUO_TABS.map((t, i) => {
    const rect: RectLayout = { x: tabX, y: tabRowY, width: tabWidths[i], height: tabHeight };
    tabX += tabWidths[i] + tabGap;
    return { id: t.id, label: t.label, rect, active: t.id === activeTab };
  });

  const viewportTop = tabRowY + tabHeight + BASE_TAB_ROW_GAP * scale;

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const bottomReserved = backSize.height + BASE_BOTTOM_INSET * scale * 2;
  const viewportHeight = Math.max(0, contentRect.y + contentRect.height - viewportTop - bottomReserved);

  const contentWidth = computeContentWidth(contentRect, scale);
  const contentLeft = centerX - contentWidth / 2;
  const padSide = BASE_PAD_SIDE * scale;
  const rowH = BASE_ROW_H * scale;
  const rowGap = BASE_ROW_GAP * scale;

  const labelFontPx = fontPx('ui_normal', scale);
  const sublabelFontPx = fontPx('ui_small', scale);

  const top0 = viewportTop - scrollOffset + BASE_TOP_INSET * scale;
  let y = top0;
  const rows: ChuoPositionedRow[] = [];

  for (const input of rowInputs) {
    if (input.kind === 'checkbox') {
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height: rowH };
      const checkboxRect: RectLayout = {
        x: contentLeft + padSide,
        y: y + (rowH - BASE_CHECKBOX_SIZE * scale) / 2,
        width: BASE_CHECKBOX_SIZE * scale,
        height: BASE_CHECKBOX_SIZE * scale,
      };
      const labelX = checkboxRect.x + checkboxRect.width + padSide * 0.6;
      const labelPos: TextLayout = { x: labelX, y: y + rowH / 2 - (input.sublabel ? 7 * scale : 0), fontPx: labelFontPx };
      const sublabelPos: TextLayout | null = input.sublabel
        ? { x: labelX, y: y + rowH / 2 + 9 * scale, fontPx: sublabelFontPx }
        : null;
      rows.push({ kind: 'checkbox', input, rowRect, labelPos, checkboxRect, sublabelPos });
      y += rowH + rowGap;
    } else if (input.kind === 'button') {
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height: rowH };
      const labelPos: TextLayout = { x: centerX, y: y + rowH / 2, fontPx: labelFontPx };
      rows.push({ kind: 'button', input, rowRect, labelPos });
      y += rowH + rowGap;
    } else if (input.kind === 'number') {
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height: rowH * 1.3 };
      const labelPos: TextLayout = { x: contentLeft + padSide, y: y + rowH * 0.35, fontPx: labelFontPx };
      const stepSize = BASE_NUMBER_STEP_SIZE * scale;
      const incrementRect: RectLayout = {
        x: contentLeft + contentWidth - padSide - stepSize,
        y: y + rowH * 0.55,
        width: stepSize,
        height: stepSize,
      };
      const decrementRect: RectLayout = {
        x: incrementRect.x - stepSize - 8 * scale,
        y: incrementRect.y,
        width: stepSize,
        height: stepSize,
      };
      const valuePos: TextLayout = {
        x: decrementRect.x - 12 * scale,
        y: incrementRect.y + stepSize / 2,
        fontPx: labelFontPx,
      };
      rows.push({ kind: 'number', input, rowRect, labelPos, decrementRect, incrementRect, valuePos });
      y += rowRect.height + rowGap;
    } else if (input.kind === 'tier') {
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height: rowH * 1.2 };
      const labelPos: TextLayout = { x: centerX, y: y + rowRect.height / 2, fontPx: labelFontPx };
      rows.push({ kind: 'tier', input, rowRect, labelPos });
      y += rowRect.height + rowGap;
    } else if (input.kind === 'text') {
      const textFontPx = fontPx('ui_small', scale);
      const textLineH = Math.round(textFontPx * 1.2);
      const wrapped = wrapText(input.text, textFontPx, contentWidth - 2 * padSide);
      const lines: RulesTextLine[] = wrapped.map((line, i) => ({
        x: contentLeft + padSide,
        y: y + i * (textLineH + BASE_TEXT_LINE_GAP * scale),
        fontPx: textFontPx,
        text: line,
      }));
      const height = Math.max(rowH, wrapped.length * (textLineH + BASE_TEXT_LINE_GAP * scale));
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height };
      const labelPos: TextLayout = { x: contentLeft + padSide, y, fontPx: textFontPx };
      rows.push({ kind: 'text', input, rowRect, labelPos, lines });
      y += height + rowGap;
    } else {
      // model
      const rowRect: RectLayout = { x: contentLeft, y, width: contentWidth, height: rowH };
      const actionW = BASE_MODEL_ACTION_WIDTH * scale;
      const actionGap = BASE_MODEL_ACTION_GAP * scale;
      const deleteButton: RectLayout = {
        x: contentLeft + contentWidth - padSide - actionW,
        y: y + (rowH - 28 * scale) / 2,
        width: actionW,
        height: 28 * scale,
      };
      const loadButton: RectLayout = {
        x: deleteButton.x - actionGap - actionW,
        y: deleteButton.y,
        width: actionW,
        height: 28 * scale,
      };
      const labelPos: TextLayout = { x: contentLeft + padSide, y: y + rowH / 2, fontPx: labelFontPx };
      rows.push({ kind: 'model', input, rowRect, labelPos, loadButton, deleteButton });
      y += rowH + rowGap;
    }
  }

  const contentHeight = y - top0 + BASE_BOTTOM_INSET * scale;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  const backButton: RectLayout = {
    x: contentRect.x + BASE_PAD_SIDE * scale,
    y: contentRect.y + contentRect.height - backSize.height - BASE_BOTTOM_INSET * scale,
    width: backSize.width,
    height: backSize.height,
  };
  const backendLabelPos: TextLayout = {
    x: contentRect.x + contentRect.width - BASE_PAD_SIDE * scale,
    y: backButton.y + backButton.height / 2,
    fontPx: fontPx('ui_small', scale),
  };

  return {
    scale,
    contentRect,
    tabButtons,
    backButton,
    backendLabelPos,
    viewportTop,
    viewportHeight,
    rows,
    contentHeight,
    maxScroll,
  };
}
