/**
 * KADI web-client — LobbyScene's layout, as pure data.
 *
 * This is the Part E retrofit: LobbyScene used to hard-code every
 * x/y/fontSize for a fixed 480x640 canvas (see git history of
 * LobbyScene.ts). Every one of those numbers now comes from this
 * function instead, so:
 *
 * 1. It's unit-testable without Phaser/a canvas at all — feed it a
 *    viewport + insets + entry count, assert on the numbers back.
 * 2. LobbyScene itself becomes "call this, apply the result to
 *    GameObjects," which is the shape every future scene should copy
 *    (see KADI_web_port_implementation_plan.md's new section) rather
 *    than each scene reinventing its own scaling math inline the way
 *    scenes.py's ~60 individual `get_chrome_scale(sw, sh)` call sites
 *    did on the Python side.
 *
 * NOTE ON TOUCH TARGETS (Part C, UPDATED for Part E): LobbyScene
 * previously had no tappable elements at all — connection status plus
 * a read-only leaderboard. This is the retrofit target that note
 * predicted: `quickPlayButton` below is the first real use of
 * enforceMinTouchTarget() outside its own dedicated tests, sized for
 * LobbyScene's new "Quick Play vs AI" button (see LobbyScene.ts's
 * Part E wiring) — the scene-transition entry point into
 * GameTableScene. Still no reconnect button, mode select, or a real
 * lobby-browse UI (join-by-list) — see packages/protocol/src/
 * messages.ts's GameSummary docstring for that explicit scope cut.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';

export interface TextLayout {
  x: number;
  y: number;
  fontPx: number;
}

export interface LobbyLayout {
  scale: number;
  contentRect: ContentRect;
  status: TextLayout;
  identity: TextLayout;
  rank: TextLayout;
  leaderboardHeader: TextLayout;
  /** Row height in px, already scaled — LobbyScene uses this to space
   * successive leaderboard lines and to decide (alongside
   * maxVisibleRows) how many entries fit before content would run
   * past the bottom of the safe content rect. */
  rowHeight: number;
  /** How many leaderboard rows fit inside the content rect below the
   * header, at this viewport/scale. LobbyScene should slice its
   * entries list to at most this many rather than rendering off the
   * bottom edge — the fixed-canvas version never had to consider this
   * because 640px of height and a max of 10 entries always fit. */
  maxVisibleRows: number;
  /** Pre-computed per-row positions for up to maxVisibleRows rows —
   * LobbyScene indexes into this rather than recomputing per row. */
  rows: TextLayout[];
  /** The Part E "Quick Play vs AI" button — top-right of the content
   * rect, clear of the leaderboard column entirely so it never
   * collides with a row regardless of maxVisibleRows at this
   * viewport. Touch-target-enforced like every other tappable element
   * from here on (see enforceMinTouchTarget in scale.ts). */
  quickPlayButton: { x: number; y: number; width: number; height: number };
}

/** Base (unscaled, at BASE_WIDTH x BASE_HEIGHT) layout constants —
 * the same numbers the original hard-coded LobbyScene used, now named
 * and fed through the scale system instead of being magic literals. */
const BASE_MARGIN_X = 24;
const BASE_STATUS_Y = 24;
const BASE_IDENTITY_Y = 56;
const BASE_RANK_Y = 84;
const BASE_HEADER_Y = 128;
const BASE_ROWS_START_Y = 160;
const BASE_ROW_HEIGHT = 22;
/** Rough natural width of this text block at BASE_WIDTH — not a real
 * measured text-metrics value (this module stays framework-agnostic,
 * no Phaser/canvas dependency, so it can't measure actual rendered
 * text width — see this file's own docstring on why that's a
 * deliberate constraint). Just enough to know "this content doesn't
 * need the full width of a wide desktop window," so a very wide
 * viewport centers the block instead of leaving it pinned to the left
 * edge with a large empty gap on the right. Deliberately conservative
 * (see computeLobbyLayout's use of Math.max below): on any viewport
 * narrow enough that this doesn't matter, behavior is IDENTICAL to
 * before this constant existed. */
const BASE_CONTENT_WIDTH = 400;

export function computeLobbyLayout(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  entryCount: number,
): LobbyLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);

  const naturalMarginX = contentRect.x + BASE_MARGIN_X * scale;
  // Center the block only once the content rect is wide enough that
  // centering would actually move it right of its natural left
  // margin -- on a narrow/phone viewport, centeredMarginX comes out
  // less than (or equal to) naturalMarginX, so Math.max just keeps
  // the original left-margin behavior, unchanged.
  const centeredMarginX = contentRect.x + (contentRect.width - BASE_CONTENT_WIDTH * scale) / 2;
  const marginX = Math.max(naturalMarginX, centeredMarginX);
  const rowHeight = BASE_ROW_HEIGHT * scale;

  const status: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_STATUS_Y * scale,
    fontPx: fontPx('ui_medium', scale),
  };
  const identity: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_IDENTITY_Y * scale,
    fontPx: fontPx('ui_normal', scale),
  };
  const rank: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_RANK_Y * scale,
    fontPx: fontPx('ui_normal', scale),
  };
  const leaderboardHeader: TextLayout = {
    x: marginX,
    y: contentRect.y + BASE_HEADER_Y * scale,
    fontPx: fontPx('ui_normal', scale),
  };

  const rowsStartY = contentRect.y + BASE_ROWS_START_Y * scale;
  const bottomLimit = contentRect.y + contentRect.height;
  const availableForRows = Math.max(0, bottomLimit - rowsStartY);
  const maxVisibleRows = rowHeight > 0 ? Math.max(0, Math.floor(availableForRows / rowHeight)) : 0;

  const rowCount = Math.min(entryCount, maxVisibleRows);
  const rows: TextLayout[] = [];
  for (let i = 0; i < rowCount; i++) {
    rows.push({
      x: marginX,
      y: rowsStartY + i * rowHeight,
      fontPx: fontPx('ui_small', scale),
    });
  }

  const quickPlaySize = enforceMinTouchTarget({ width: 160 * scale, height: 44 * scale });
  const quickPlayButton = {
    x: contentRect.x + contentRect.width - quickPlaySize.width - BASE_MARGIN_X * scale,
    y: contentRect.y + BASE_STATUS_Y * scale,
    width: quickPlaySize.width,
    height: quickPlaySize.height,
  };

  return {
    scale,
    contentRect,
    status,
    identity,
    rank,
    leaderboardHeader,
    rowHeight,
    maxVisibleRows,
    rows,
    quickPlayButton,
  };
}
