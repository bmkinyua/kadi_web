/**
 * KADI web-client — InternetLobbyScene's layout, as pure data.
 *
 * Same discipline as LobbyLayout.ts/ModeSelectLayout.ts: no Phaser,
 * no DOM, fully unit-testable. This is the real browse/host/join/
 * waiting-room flow (KADI_web_port_implementation_plan.md §9's
 * "Internet Multiplayer -- real join/browse flow" row), replacing the
 * "not started" status that row previously carried.
 *
 * Ported from scenes.InternetLobbyScene's own layout math (see that
 * class's on_enter()), but reshaped from its two-column desktop
 * layout into a SINGLE vertical column -- this renderer's baseline
 * canvas (scale.ts's BASE_WIDTH/BASE_HEIGHT, 480x640) is portrait/
 * phone-first, where a 340px-wide left column plus a games list to
 * its right (the PC's actual layout) would not fit at any reasonable
 * scale. A single stacked column reads top-to-bottom at every
 * viewport this renderer targets (phone portrait through desktop),
 * the same choice LobbyScene/ModeSelectScene already made.
 *
 * Two independent layouts are exported, one per InternetLobbyScene
 * state group:
 *   - computeInternetLobbyBrowseLayout(): the 'browse' state -- host
 *     form (name field + host button), search field, and the open
 *     games list (each row capped to maxVisibleRows, same row-capping
 *     pattern LobbyLayout.ts's leaderboard rows use).
 *   - computeInternetLobbyRosterLayout(): the 'lobby' (waiting-room)
 *     state -- title/subtitle, player roster rows, Start button.
 * Both share a Back button and the same scale/contentRect math.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';

export interface RectLayout {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A single row in the open-games list -- the row's own clickable
 * area (for search-result hit-testing / visual bounds) plus its
 * nested Join button, mirroring scenes.InternetLobbyScene's
 * _game_row_rect()/_join_btn_rect() pair. */
export interface GameRowLayout extends RectLayout {
  fontPx: number;
  joinButton: RectLayout;
}

export interface InternetLobbyBrowseLayout {
  scale: number;
  contentRect: ContentRect;
  title: TextLayout;
  hostLabel: TextLayout;
  gameNameField: RectLayout;
  hostButton: RectLayout & { label: string };
  searchField: RectLayout;
  listHeader: TextLayout;
  /** How many game rows fit below the search field at this viewport
   * -- InternetLobbyScene should slice its filtered list to at most
   * this many, same "cap, don't overflow" rule LobbyLayout.ts's
   * maxVisibleRows documents. */
  maxVisibleRows: number;
  rows: GameRowLayout[];
  backButton: RectLayout;
}

export interface InternetLobbyRosterLayout {
  scale: number;
  contentRect: ContentRect;
  title: TextLayout;
  subtitle: TextLayout;
  rosterHeader: TextLayout;
  rowHeight: number;
  maxVisibleRows: number;
  rows: TextLayout[];
  startButton: RectLayout;
  backButton: RectLayout;
}

const BASE_TITLE_Y = 20;
const BASE_HOST_LABEL_Y = 56;
const BASE_FIELD_Y = 78;
const BASE_FIELD_WIDTH = 400;
const BASE_FIELD_HEIGHT = 32;
const BASE_HOST_BUTTON_Y = 118;
const BASE_HOST_BUTTON_WIDTH = 200;
const BASE_HOST_BUTTON_HEIGHT = 36;
const BASE_SEARCH_Y = 166;
const BASE_LIST_HEADER_Y = 206;
const BASE_LIST_START_Y = 228;
// Tall enough that even at MIN_SCALE (scale.ts's 0.7 floor) a
// touch-target-enforced 44px Join button still fits centered inside
// the row without poking out above/below it (46px was not enough --
// 46 * 0.7 = 32.2px, shorter than the 44px minimum button itself).
const BASE_ROW_HEIGHT = 68;
const BASE_JOIN_BUTTON_WIDTH = 64;
const BASE_JOIN_BUTTON_HEIGHT = 28;
const BASE_BACK_BUTTON_WIDTH = 140;
const BASE_BACK_BUTTON_HEIGHT = 40;
const BASE_BOTTOM_MARGIN = 16;
/** Same reasoning as LobbyLayout.ts's BASE_CONTENT_WIDTH -- caps how
 * wide this single column grows on a very wide desktop viewport,
 * centering it instead of stretching every field edge-to-edge. */
const BASE_CONTENT_WIDTH = 440;

function centeredMarginX(contentRect: ContentRect, scale: number): number {
  const natural = contentRect.x;
  const centered = contentRect.x + (contentRect.width - BASE_CONTENT_WIDTH * scale) / 2;
  return Math.max(natural, centered);
}

export function computeInternetLobbyBrowseLayout(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  gameCount: number,
): InternetLobbyBrowseLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const marginX = centeredMarginX(contentRect, scale);
  const centerX = contentRect.x + contentRect.width / 2;
  const fieldWidth = Math.min(BASE_FIELD_WIDTH * scale, contentRect.width - 2 * (marginX - contentRect.x));

  const title: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_medium', scale),
  };
  const hostLabel: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_HOST_LABEL_Y * scale,
    fontPx: fontPx('ui_small', scale),
  };
  const gameNameField: RectLayout = {
    x: marginX,
    y: contentRect.y + BASE_FIELD_Y * scale,
    width: fieldWidth,
    height: BASE_FIELD_HEIGHT * scale,
  };
  const hostButtonSize = enforceMinTouchTarget({
    width: BASE_HOST_BUTTON_WIDTH * scale,
    height: BASE_HOST_BUTTON_HEIGHT * scale,
  });
  const hostButton = {
    x: marginX,
    y: contentRect.y + BASE_HOST_BUTTON_Y * scale,
    width: hostButtonSize.width,
    height: hostButtonSize.height,
    label: 'Host a New Game',
  };
  const searchField: RectLayout = {
    x: marginX,
    y: contentRect.y + BASE_SEARCH_Y * scale,
    width: fieldWidth,
    height: BASE_FIELD_HEIGHT * scale,
  };
  const listHeader: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_LIST_HEADER_Y * scale,
    fontPx: fontPx('ui_small', scale),
  };

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const backButton: RectLayout = {
    x: centerX - backSize.width / 2,
    y: contentRect.y + contentRect.height - backSize.height - BASE_BOTTOM_MARGIN * scale,
    width: backSize.width,
    height: backSize.height,
  };

  const listStartY = contentRect.y + BASE_LIST_START_Y * scale;
  const listBottomLimit = backButton.y - BASE_BOTTOM_MARGIN * scale;
  const rowHeight = BASE_ROW_HEIGHT * scale;
  const available = Math.max(0, listBottomLimit - listStartY);
  const maxVisibleRows = rowHeight > 0 ? Math.max(0, Math.floor(available / rowHeight)) : 0;

  const rowCount = Math.min(gameCount, maxVisibleRows);
  const rows: GameRowLayout[] = [];
  const joinSize = enforceMinTouchTarget({
    width: BASE_JOIN_BUTTON_WIDTH * scale,
    height: BASE_JOIN_BUTTON_HEIGHT * scale,
  });
  for (let i = 0; i < rowCount; i++) {
    const rowY = listStartY + i * rowHeight;
    const rowW = fieldWidth;
    // The Join button is centered within the row's full vertical
    // slot (rowHeight), not the slightly-shrunken visual rect below
    // (which just trims a hairline gap between rows) -- otherwise a
    // touch-target-enforced button taller than that shrunken rect
    // would be forced to poke out above the row on narrow viewports.
    rows.push({
      x: marginX,
      y: rowY,
      width: rowW,
      height: rowHeight - 4 * scale,
      fontPx: fontPx('ui_small', scale),
      joinButton: {
        x: marginX + rowW - joinSize.width - 8 * scale,
        y: rowY + (rowHeight - joinSize.height) / 2,
        width: joinSize.width,
        height: joinSize.height,
      },
    });
  }

  return {
    scale,
    contentRect,
    title,
    hostLabel,
    gameNameField,
    hostButton,
    searchField,
    listHeader,
    maxVisibleRows,
    rows,
    backButton,
  };
}

const BASE_ROSTER_TITLE_Y = 24;
const BASE_ROSTER_SUBTITLE_Y = 56;
const BASE_ROSTER_HEADER_Y = 92;
const BASE_ROSTER_ROWS_START_Y = 118;
const BASE_ROSTER_ROW_HEIGHT = 26;
const BASE_START_BUTTON_WIDTH = 220;
const BASE_START_BUTTON_HEIGHT = 48;

export function computeInternetLobbyRosterLayout(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  rosterCount: number,
): InternetLobbyRosterLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const marginX = centeredMarginX(contentRect, scale);
  const centerX = contentRect.x + contentRect.width / 2;

  const title: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_ROSTER_TITLE_Y * scale,
    fontPx: fontPx('ui_medium', scale),
  };
  const subtitle: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_ROSTER_SUBTITLE_Y * scale,
    fontPx: fontPx('ui_small', scale),
  };
  const rosterHeader: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_ROSTER_HEADER_Y * scale,
    fontPx: fontPx('ui_small', scale),
  };

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const backButton: RectLayout = {
    x: centerX - backSize.width / 2,
    y: contentRect.y + contentRect.height - backSize.height - BASE_BOTTOM_MARGIN * scale,
    width: backSize.width,
    height: backSize.height,
  };

  const startSize = enforceMinTouchTarget({
    width: BASE_START_BUTTON_WIDTH * scale,
    height: BASE_START_BUTTON_HEIGHT * scale,
  });
  const startButton: RectLayout = {
    x: centerX - startSize.width / 2,
    y: backButton.y - startSize.height - BASE_BOTTOM_MARGIN * scale,
    width: startSize.width,
    height: startSize.height,
  };

  const rowHeight = BASE_ROSTER_ROW_HEIGHT * scale;
  const rowsStartY = contentRect.y + BASE_ROSTER_ROWS_START_Y * scale;
  const bottomLimit = startButton.y - BASE_BOTTOM_MARGIN * scale;
  const available = Math.max(0, bottomLimit - rowsStartY);
  const maxVisibleRows = rowHeight > 0 ? Math.max(0, Math.floor(available / rowHeight)) : 0;

  const rowCount = Math.min(rosterCount, maxVisibleRows);
  const rows: TextLayout[] = [];
  for (let i = 0; i < rowCount; i++) {
    rows.push({
      x: marginX,
      y: rowsStartY + i * rowHeight,
      fontPx: fontPx('ui_small', scale),
    });
  }

  return {
    scale,
    contentRect,
    title,
    subtitle,
    rosterHeader,
    rowHeight,
    maxVisibleRows,
    rows,
    startButton,
    backButton,
  };
}
