/**
 * KADI web-client — GameConfigScene's layout, as pure data.
 *
 * Ported from scenes.ModeSelectScene's own `_relayout()` (scenes.py,
 * class at line 1542) — the real per-game configuration screen this
 * codebase's own ModeSelectScene.ts previously skipped (see §9's
 * "Mode Select" row, and MultiplayerMenuLayout.ts's header for what
 * took over ModeSelectScene.ts's old "which mode" job). Same
 * single-source-of-truth discipline as SettingsLayout.ts's
 * `computeSettingsFlow()`/RulesLayout.ts's `_flow()` port: one
 * function builds every widget's absolute rect for the CURRENT
 * scroll offset AND the current `vsAi`/opponent-count/elimination
 * state, since — unlike Settings/Rules — this screen's geometry
 * genuinely depends on live values (hot-seat name field count grows
 * with opponent count; the AI-only-continue row only exists once
 * Elimination Mode is on), exactly as `_relayout()` itself does on
 * the PC side.
 *
 * ONE SHARED SCREEN, TWO MODES (mirrors `ModeSelectScene(vs_ai: bool)`
 * exactly): `vsAi=true` (reached directly from Main Menu's "Play vs
 * AI") shows AI Difficulty + MSOMI attach + the AI-only-continue
 * sub-toggle; `vsAi=false` (reached from MultiplayerMenuScene's
 * "Local Multiplayer") shows up to 5 hot-seat opponent-name fields
 * instead. Elimination Mode itself is offered either way, matching
 * `_relayout()`'s own "even in single player" comment.
 *
 * OPPONENT COUNT IS 1–5, NOT 0–5 — a deliberate correction versus an
 * earlier draft of this task's own brief, which described a
 * "0 opponents = AI Spectator Mode" setup option. Checked directly
 * against `scenes.py`'s `_opp_buttons` loop
 * (`for i, n in enumerate([1,2,3,4,5])`, line ~1706) and
 * `GameManager.is_ai_spectator_mode` (core/game_manager.py) — the
 * button list only ever offers 1–5, and `is_ai_spectator_mode` is a
 * MID-GAME property (true once every human has finished in
 * Elimination Mode, not a setup-time choice). Built against the real
 * PC source, not the brief's inaccurate paraphrase of it.
 *
 * WIDGET GEOMETRY reuses SettingsLayout.ts's/RulesLayout.ts's own
 * baseline pixel constants where the widget kind matches (toggle,
 * choice-button, back button) for the same "visually consistent with
 * the rest of this scrollable-screen family" reason those two files
 * already established.
 *
 * TEXT FIELDS ("Your Name", hot-seat names) are a genuine addition —
 * no other web scene needed free-text entry before this one
 * (SettingsScene.ts's NumberBox is digits-only). GameConfigScene.ts
 * owns the click-to-focus + keyboard-entry state machine; this file
 * only computes each field's box geometry.
 *
 * SCROLL PHYSICS come from ./scrollPhysics.ts, same as every other
 * scrollable screen — see that module's header.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { RectLayout } from './InternetLobbyLayout.js';
import { estimateTextWidth, wrapText } from './RulesLayout.js';

export type AiDifficulty = 'EASY' | 'MEDIUM' | 'HARD';

export const MAX_OPPONENTS = 5;
export const MIN_OPPONENTS = 1;

// ── Row shapes — one discriminated union, geometry only (no live
// values baked in beyond what's needed to know a row exists at all —
// e.g. the local-name rows array length IS the current opponent
// count, same as SettingsLayout.ts's cards depend on nothing but
// scenes.py's own toggle list). ──

export interface TextFieldRowLayout {
  kind: 'textfield';
  /** 'playerName' for the single "Your Name" field, or 'local:<i>'
   * (i = 0..MAX_OPPONENTS-1) for a hot-seat opponent name field —
   * GameConfigScene.ts keys its own text-state map by this id. */
  id: string;
  label: TextLayout & { value: string };
  box: RectLayout;
}

export interface OpponentCountRowLayout {
  kind: 'opponentCount';
  label: TextLayout & { value: string };
  buttons: { n: number; rect: RectLayout }[];
}

export interface DifficultyRowLayout {
  kind: 'difficulty';
  label: TextLayout & { value: string };
  buttons: { value: AiDifficulty; rect: RectLayout }[];
}

export interface MsomiRowLayout {
  kind: 'msomi';
  label: TextLayout & { value: string };
  toggle: RectLayout;
  attach: RectLayout;
}

export interface GameConfigToggleRowLayout {
  kind: 'toggle';
  id: 'eliminationMode' | 'eliminationAiOnlyContinue';
  label: TextLayout & { value: string };
  button: RectLayout;
}

export interface GameConfigNoteRowLayout {
  kind: 'note';
  lines: (TextLayout & { text: string })[];
}

export type GameConfigRowLayout =
  | TextFieldRowLayout
  | OpponentCountRowLayout
  | DifficultyRowLayout
  | MsomiRowLayout
  | GameConfigToggleRowLayout
  | GameConfigNoteRowLayout;

export interface GameConfigFlow {
  scale: number;
  contentRect: ContentRect;
  viewportTop: number;
  viewportHeight: number;
  rows: GameConfigRowLayout[];
  startButton: RectLayout;
  backButton: RectLayout;
  contentHeight: number;
  maxScroll: number;
}

// ── baseline constants — reused verbatim from SettingsLayout.ts/
// RulesLayout.ts where the widget kind matches. ──
const BASE_TITLE_Y = 18;
const BASE_TITLE_GAP = 20;
const BASE_TOP_INSET = 16;
const BASE_BOTTOM_INSET = 16;
const BASE_BOTTOM_MARGIN = 16;
const BASE_ROW_GAP = 40; // vertical gap between one row block and the next
const BASE_FIELD_W = 300;
const BASE_FIELD_H = 45;
const BASE_LABEL_GAP = 26;
const BASE_COUNT_BTN_W = 60;
const BASE_COUNT_BTN_H = 40;
const BASE_COUNT_BTN_GAP = 8;
const BASE_DIFF_BTN_W = 120;
const BASE_DIFF_BTN_H = 40;
const BASE_DIFF_BTN_GAP = 10;
const BASE_MSOMI_TOGGLE_W = 170;
const BASE_MSOMI_ATTACH_W = 184;
const BASE_MSOMI_BTN_H = 40;
const BASE_MSOMI_GAP = 4;
const BASE_TOGGLE_BTN_W = 180;
const BASE_TOGGLE_BTN_H = 40;
const BASE_LINE_H = 18;
const BASE_START_BUTTON_WIDTH = 260;
const BASE_START_BUTTON_HEIGHT = 52;
const BASE_BACK_BUTTON_WIDTH = 260;
const BASE_BACK_BUTTON_HEIGHT = 48;
const BASE_BUTTON_GAP = 12;
const BASE_CONTENT_WIDTH = 360; // matches RulesLayout.ts's text-wrap column baseline

function lineHeight(fontPxValue: number): number {
  return Math.round(fontPxValue * 1.2);
}

function layoutNote(
  text: string,
  centerX: number,
  y: number,
  textWidth: number,
  fontPxValue: number,
  lineH: number,
): { row: GameConfigNoteRowLayout; nextY: number } {
  const wrapped = wrapText(text, fontPxValue, textWidth);
  const lines = wrapped.map((line, i) => ({ x: centerX, y: y + i * lineH, fontPx: fontPxValue, text: line }));
  return { row: { kind: 'note', lines }, nextY: y + wrapped.length * lineH };
}

export interface GameConfigFlowOptions {
  vsAi: boolean;
  /** Current opponent count (1–MAX_OPPONENTS) — drives how many
   * hot-seat name fields exist when `vsAi` is false, same as
   * `_relayout()`'s own `range(self._n_opponents)` loop. */
  opponentCount: number;
  eliminationMode: boolean;
}

/**
 * The one function GameConfigScene.ts calls for every position/size,
 * given the current scroll offset and live setup state — direct
 * analogue of `_relayout()`.
 */
export function computeGameConfigFlow(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  scrollOffset: number,
  options: GameConfigFlowOptions,
): GameConfigFlow {
  const { vsAi, eliminationMode } = options;
  const opponentCount = Math.max(MIN_OPPONENTS, Math.min(MAX_OPPONENTS, Math.round(options.opponentCount)));

  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const titleFontPx = fontPx('ui_large', scale);
  const bodyFontPx = fontPx('ui_normal', scale);
  const tinyFontPx = fontPx('ui_tiny', scale);

  const viewportTop = contentRect.y + BASE_TITLE_Y * scale + lineHeight(titleFontPx) + BASE_TITLE_GAP * scale;
  const viewportHeight = Math.max(0, contentRect.y + contentRect.height - viewportTop - BASE_BOTTOM_MARGIN * scale);

  const fieldW = BASE_FIELD_W * scale;
  const fieldH = BASE_FIELD_H * scale;
  const lineH = BASE_LINE_H * scale;
  const textWidth = Math.min(BASE_CONTENT_WIDTH * scale, contentRect.width - 32 * scale);

  const top0 = viewportTop - scrollOffset + BASE_TOP_INSET * scale;
  let y = top0;
  const rows: GameConfigRowLayout[] = [];

  // ── Your Name ──────────────────────────────────────────────────
  rows.push({
    kind: 'textfield',
    id: 'playerName',
    label: { x: centerX - fieldW / 2, y: y - BASE_LABEL_GAP * scale, fontPx: bodyFontPx, value: 'Your Name:' },
    box: { x: centerX - fieldW / 2, y, width: fieldW, height: fieldH },
  });
  y += fieldH + BASE_ROW_GAP * scale;

  // ── Opponent count ────────────────────────────────────────────
  const countBtnW = BASE_COUNT_BTN_W * scale;
  const countBtnH = BASE_COUNT_BTN_H * scale;
  const countGap = BASE_COUNT_BTN_GAP * scale;
  const countTotal = countBtnW * MAX_OPPONENTS + countGap * (MAX_OPPONENTS - 1);
  const countLeft = centerX - countTotal / 2;
  const countButtons = Array.from({ length: MAX_OPPONENTS }, (_, i) => ({
    n: i + 1,
    rect: { x: countLeft + i * (countBtnW + countGap), y, width: countBtnW, height: countBtnH },
  }));
  rows.push({
    kind: 'opponentCount',
    label: {
      x: centerX,
      y: y - BASE_LABEL_GAP * scale,
      fontPx: bodyFontPx,
      value: vsAi ? 'Number of Opponents:' : 'Number of Other Players:',
    },
    buttons: countButtons,
  });
  y += countBtnH + BASE_ROW_GAP * scale;

  // ── Local Multiplayer: one hot-seat name field per other player ─
  if (!vsAi) {
    for (let i = 0; i < opponentCount; i++) {
      rows.push({
        kind: 'textfield',
        id: `local:${i}`,
        label: {
          x: centerX - fieldW / 2,
          y: y - BASE_LABEL_GAP * scale,
          fontPx: bodyFontPx,
          value: `Player ${i + 2} Name:`,
        },
        box: { x: centerX - fieldW / 2, y, width: fieldW, height: fieldH },
      });
      y += fieldH + 32 * scale;
    }
    y += BASE_ROW_GAP * scale - 32 * scale + 6 * scale;
  }

  // ── Play vs AI: Difficulty + MSOMI ───────────────────────────────
  if (vsAi) {
    const diffBtnW = BASE_DIFF_BTN_W * scale;
    const diffBtnH = BASE_DIFF_BTN_H * scale;
    const diffGap = BASE_DIFF_BTN_GAP * scale;
    const diffTotal = diffBtnW * 3 + diffGap * 2;
    const diffLeft = centerX - diffTotal / 2;
    const difficulties: AiDifficulty[] = ['EASY', 'MEDIUM', 'HARD'];
    rows.push({
      kind: 'difficulty',
      label: { x: centerX, y: y - BASE_LABEL_GAP * scale, fontPx: bodyFontPx, value: 'AI Difficulty:' },
      buttons: difficulties.map((value, i) => ({
        value,
        rect: { x: diffLeft + i * (diffBtnW + diffGap), y, width: diffBtnW, height: diffBtnH },
      })),
    });
    y += diffBtnH + BASE_ROW_GAP * scale;

    const msomiToggleW = BASE_MSOMI_TOGGLE_W * scale;
    const msomiAttachW = BASE_MSOMI_ATTACH_W * scale;
    const msomiGap = BASE_MSOMI_GAP * scale;
    const msomiH = BASE_MSOMI_BTN_H * scale;
    const msomiTotal = msomiToggleW + msomiGap + msomiAttachW;
    const msomiLeft = centerX - msomiTotal / 2;
    rows.push({
      kind: 'msomi',
      label: { x: msomiLeft, y: y - BASE_LABEL_GAP * scale, fontPx: bodyFontPx, value: 'MSOMI:' },
      toggle: { x: msomiLeft, y, width: msomiToggleW, height: msomiH },
      attach: { x: msomiLeft + msomiToggleW + msomiGap, y, width: msomiAttachW, height: msomiH },
    });
    y += msomiH + BASE_ROW_GAP * scale;
  }

  // ── Elimination Mode (both modes) ─────────────────────────────────
  const toggleBtnW = BASE_TOGGLE_BTN_W * scale;
  const toggleBtnH = BASE_TOGGLE_BTN_H * scale;
  rows.push({
    kind: 'toggle',
    id: 'eliminationMode',
    label: { x: centerX, y: y - BASE_LABEL_GAP * scale, fontPx: bodyFontPx, value: 'Elimination Mode:' },
    button: { x: centerX - toggleBtnW / 2, y, width: toggleBtnW, height: toggleBtnH },
  });
  y += toggleBtnH + 6 * scale;
  const elimNote = layoutNote(
    'Winners are set aside as they finish — last one holding cards loses',
    centerX,
    y,
    textWidth,
    tinyFontPx,
    lineH,
  );
  rows.push(elimNote.row);
  y = elimNote.nextY + BASE_ROW_GAP * scale;

  // ── AI-only-continue sub-toggle — vs-AI + Elimination Mode only ──
  if (vsAi && eliminationMode) {
    rows.push({
      kind: 'toggle',
      id: 'eliminationAiOnlyContinue',
      label: { x: centerX, y: y - BASE_LABEL_GAP * scale, fontPx: bodyFontPx, value: 'When all humans finish:' },
      button: { x: centerX - toggleBtnW / 2, y, width: toggleBtnW, height: toggleBtnH },
    });
    y += toggleBtnH + BASE_ROW_GAP * scale;
  }

  // ── Start / Back buttons ───────────────────────────────────────
  const startSize = enforceMinTouchTarget({
    width: BASE_START_BUTTON_WIDTH * scale,
    height: BASE_START_BUTTON_HEIGHT * scale,
  });
  const startButton: RectLayout = { x: centerX - startSize.width / 2, y, width: startSize.width, height: startSize.height };
  y += startSize.height + BASE_BUTTON_GAP * scale;

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const backButton: RectLayout = { x: centerX - backSize.width / 2, y, width: backSize.width, height: backSize.height };
  y += backSize.height + BASE_BOTTOM_INSET * scale;

  const contentHeight = y - top0;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  return { scale, contentRect, viewportTop, viewportHeight, rows, startButton, backButton, contentHeight, maxScroll };
}

/** Fixed title TextLayout (positioned above viewportTop, outside the
 * scrollable flow) — same pattern as RulesLayout.ts's/
 * SettingsLayout.ts's own computeXTitleLayout(). Text itself ("Play
 * vs AI" / "Local Multiplayer") is GameConfigScene.ts's call, mirroring
 * `_relayout()`'s own `mode_str = "Play vs AI" if self.vs_ai else
 * "Local Multiplayer"`. */
export function computeGameConfigTitleLayout(rawViewport: Viewport, insets: SafeAreaInsets): TextLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  return {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
}

export { estimateTextWidth, wrapText };
