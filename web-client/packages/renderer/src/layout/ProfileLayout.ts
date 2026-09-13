/**
 * KADI web-client — ProfileScene's layout, as pure data.
 *
 * Ported from scenes.ProfileScene (scenes.py, class at line 1061,
 * `draw()` starting at line 1203) — same "one pure function computes
 * every widget's rect for the current scroll offset" discipline
 * SettingsLayout.ts/RulesLayout.ts already established (see this
 * project's §6a and those files' own headers).
 *
 * SCOPE, read directly against the PC class rather than trusted from
 * the handoff prompt's own summary (same discrepancy this project has
 * caught before — see SettingsLayout.ts's header on the Settings
 * task's undercounted card list): the handoff brief for THIS task
 * named "four real sections" (Stats, Badges, Card Backs, Felt
 * Themes). Reading `draw()` line-by-line found a FIFTH: a
 * "Leaderboard — Your Best Modes" panel (scenes.py lines 1263-1310)
 * sitting between Stats and Badges — the player's own per-mode
 * win-rate ranking, framed as "your best modes" rather than a
 * competitive ranking (see that panel's own PC-side comment: there's
 * nothing else in profile.json to rank against; the server-backed,
 * other-players ranking lives in InternetLobbyScene's separate Global
 * Leaderboard tab, already ported, unrelated to this screen). Ported
 * here as a fifth section, in the same position, for the same reason.
 * Five sections, in this order: Stats, Leaderboard, Badges, Cosmetics
 * — Card Backs, Cosmetics — Table Felt Themes.
 *
 * THINGS THIS FILE DELIBERATELY DOES NOT PORT (see profileData.ts's
 * own header for the data-layer side of the same scope cuts):
 * - The PC's per-badge Share button opens a small per-platform picker
 *   row (Twitter/etc., `social_share.SHARE_UI_OPTIONS`) that then
 *   renders a PNG card and calls `webbrowser.open()` — see
 *   core/social_share.py / rendering/share_card.py. On web there is
 *   no OS browser to hand off to; this renderer IS already inside a
 *   browser, so `PlatformAdapter.shareResult()` (native share sheet,
 *   falling back to clipboard — see WebAdapter.ts) already does the
 *   platform-appropriate thing directly. So each earned badge here
 *   gets exactly ONE "Share" button (`BadgeRowLayout.shareButton`),
 *   not a picker row — ProfileScene.ts wires its click straight to
 *   `adapter.shareResult()`. No PNG generation, no platform-picker
 *   geometry, is ported.
 * - Card-back swatches show a flat two-color gradient (`colorA`/
 *   `colorB` from profileData.ts's CARD_BACK_STYLES), not the PC's
 *   real procedural pattern (diagonal/crosshatch/dots/etc. — see
 *   AssetLoader's card-back generator) — this web client has no
 *   card-art rendering pipeline at all yet (GameTableScene.ts's own
 *   header note), so there is no pattern renderer to reuse here
 *   either. The `pattern` field is still carried in profileData.ts
 *   for a future pass; this layout only positions the swatch rect.
 *
 * WIDGET GEOMETRY reuses the PC's own baseline pixel values directly
 * (back button 120x40 at (20,16), matching scenes.py's on_enter()) as
 * this renderer's BASE_* constants — same "reuse the PC's absolute
 * legible sizes at this renderer's own scale=1 baseline" reasoning
 * SettingsLayout.ts's header already documents for its own back
 * button.
 *
 * TEXT WRAPPING reuses RulesLayout.ts's estimateTextWidth()/
 * wrapText() (imported, not reimplemented) for the same "no canvas in
 * a pure module" reason already documented there and in
 * SettingsLayout.ts.
 *
 * SCROLL PHYSICS come from ./scrollPhysics.ts, shared with
 * RulesScene/SettingsScene — see that module's own header.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { RectLayout } from './InternetLobbyLayout.js';
import { wrapText } from './RulesLayout.js';
import {
  BADGE_CATEGORIES,
  BADGE_DEFS,
  CARD_BACK_STYLES,
  FELT_THEMES,
  cosmeticUnlockHint,
  totalGamesPlayed,
  UNDO_TOKENS_MAX,
  type ProfileData,
} from '../profileData.js';

// ── baseline constants (scale=1 == this renderer's BASE_WIDTH x
// BASE_HEIGHT design canvas, same as every other layout module). ──
const BASE_TITLE_Y = 18;
const BASE_TITLE_GAP = 20;
const BASE_TOP_INSET = 8;
const BASE_BOTTOM_INSET = 24;
const BASE_BOTTOM_MARGIN = 16;
const BASE_PAD_OUTER = 20;
const BASE_LINE_H = 17; // wrap_text line pitch at ui_tiny-ish body text
const BASE_SECTION_GAP = 22;
const BASE_HEADER_GAP = 10;
const BASE_BADGE_ROW_GAP = 8;
const BASE_BADGE_DOT_R = 5;
const BASE_SHARE_BTN_W = 64;
const BASE_SHARE_BTN_H = 24;
const BASE_SWATCH_W = 90;
const BASE_SWATCH_H = 60;
const BASE_SWATCH_GAP = 12;
const BASE_SWATCH_ROW_GAP = 40; // vertical gap when swatches wrap to a new row
const BASE_EQUIP_BTN_H = 24;
const BASE_EQUIP_BTN_GAP = 22;
const BASE_SWATCH_LABEL_GAP = 18; // "Equipped"/"Locked" caption offset below swatch

const BASE_BACK_BUTTON_X = 20;
const BASE_BACK_BUTTON_Y = 16;
const BASE_BACK_BUTTON_WIDTH = 120;
const BASE_BACK_BUTTON_HEIGHT = 40;

const BASE_CARD_WIDTH = 420;
const BASE_MIN_CARD_WIDTH = 300;
const BASE_CARD_SIDE_MARGIN = 24;

function lineHeight(fontPxValue: number): number {
  return Math.round(fontPxValue * 1.2);
}

function computeCardWidth(contentRect: ContentRect, scale: number): number {
  const natural = BASE_CARD_WIDTH * scale;
  const capped = Math.min(natural, contentRect.width - 2 * BASE_CARD_SIDE_MARGIN * scale);
  return Math.max(BASE_MIN_CARD_WIDTH * scale, capped);
}

// ── Row/section shapes ──────────────────────────────────────────────

export interface TextRowLayout {
  text: string;
  x: number;
  y: number;
  fontPx: number;
}

export interface SectionHeaderLayout {
  text: string;
  x: number;
  y: number;
  fontPx: number;
}

export interface BadgeRowLayout {
  id: string;
  name: string;
  desc: string;
  category: string;
  earned: boolean;
  lines: TextRowLayout[];
  dot: { x: number; y: number; r: number };
  /** Present only for an EARNED badge — see this file's header on
   * why there is exactly one, not a per-platform picker. */
  shareButton: RectLayout | null;
  rowHeight: number;
}

export interface BadgeCategorySection {
  header: SectionHeaderLayout;
  rows: BadgeRowLayout[];
}

export interface CosmeticSwatchLayout {
  kind: 'card_back' | 'felt_theme';
  key: string;
  label: string;
  colorA: number;
  colorB: number;
  owned: boolean;
  equipped: boolean;
  /** Unlock requirement (locked) or which badge granted it (owned) —
   * null for the always-owned 'default' style, matching
   * cosmeticUnlockHint()'s own null case. */
  hint: string | null;
  rect: RectLayout;
  labelPos: TextLayout;
  statusPos: TextLayout; // "Equipped" / "Locked" caption position
  equipButton: RectLayout | null; // present only when owned && !equipped
}

export interface ProfileFlow {
  scale: number;
  contentRect: ContentRect;
  viewportTop: number;
  viewportHeight: number;
  cardWidth: number;
  cardLeft: number;
  backButton: RectLayout;

  statsHeader: SectionHeaderLayout;
  statsLines: TextRowLayout[];

  leaderboardHeader: SectionHeaderLayout;
  leaderboardLines: TextRowLayout[];

  badgesHeader: SectionHeaderLayout;
  badgeCategories: BadgeCategorySection[];

  cardBacksHeader: SectionHeaderLayout;
  cardBackSwatches: CosmeticSwatchLayout[];

  feltThemesHeader: SectionHeaderLayout;
  feltSwatches: CosmeticSwatchLayout[];

  contentHeight: number;
  maxScroll: number;
}

/** Pre-formats every text-only line this screen shows, given a
 * profile — kept OUT of the pure layout function's own body only in
 * the sense that it's a separate exported helper (so it's separately
 * testable), not because content depends on anything layout-ish; it
 * is genuinely just string formatting, mirroring scenes.py draw()'s
 * own inline f-string list for Stats (lines 1237-1254) and the
 * Leaderboard's mode_rows computation (lines 1271-1297). */
export function formatStatsLines(p: ProfileData): string[] {
  const gp = p.games_played;
  const gw = p.games_won;
  const lines = [
    `Single-player — Easy: ${gw.single_player.EASY}/${gp.single_player.EASY} won   ` +
      `Medium: ${gw.single_player.MEDIUM}/${gp.single_player.MEDIUM}   ` +
      `Hard: ${gw.single_player.HARD}/${gp.single_player.HARD}`,
    `Elimination Mode — Easy: ${gw.single_player_elimination.EASY}/${gp.single_player_elimination.EASY}   ` +
      `Medium: ${gw.single_player_elimination.MEDIUM}/${gp.single_player_elimination.MEDIUM}   ` +
      `Hard: ${gw.single_player_elimination.HARD}/${gp.single_player_elimination.HARD}`,
    `LAN: ${gw.lan}/${gp.lan} won     Internet: ${gw.internet}/${gp.internet} won     ` +
      `Hot-seat: ${gw.hot_seat}/${gp.hot_seat} won`,
    `Total games played: ${totalGamesPlayed(p)}`,
    'Multi-card finishes — ' +
      Object.entries(p.multi_card_finishes)
        .map(([k, v]) => `${titleCase(k)}: ${v}`)
        .join(', '),
    `MSOMI/Chuo — Models trained: ${p.msomi.models_trained}   ` +
      `Games vs MSOMI: ${p.msomi.games_played_with_msomi}   ` +
      `Won vs MSOMI: ${p.msomi.games_won_with_msomi}`,
    `Total time played: ${Math.floor(p.total_time_played_secs / 3600)}h ` +
      `${Math.floor((p.total_time_played_secs % 3600) / 60)}m`,
    `Undo tokens: ${p.undo_tokens} / ${UNDO_TOKENS_MAX}`,
  ];
  return lines;
}

function titleCase(snake: string): string {
  return snake
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export interface LeaderboardModeRow {
  label: string;
  wins: number;
  played: number;
  rate: number; // 0-100
}

/** Direct port of draw()'s `mode_rows` build + sort (lines 1271-1297,
 * minus the "Signature finish"/"Badges earned" trailer lines, which
 * formatStatsLines-adjacent callers append separately as plain
 * strings — see ProfileScene.ts). */
export function formatLeaderboardRows(p: ProfileData): LeaderboardModeRow[] {
  const rows: LeaderboardModeRow[] = [];
  const gw = p.games_won;
  const gp = p.games_played;
  for (const [key, label] of [
    ['lan', 'LAN'],
    ['internet', 'Internet'],
    ['hot_seat', 'Hot-seat'],
  ] as const) {
    const played = gp[key];
    if (played > 0) rows.push({ label, wins: gw[key], played, rate: (100 * gw[key]) / played });
  }
  for (const [baseKey, baseLabel] of [
    ['single_player', 'Single-Player'],
    ['single_player_elimination', 'Elimination'],
  ] as const) {
    for (const d of ['EASY', 'MEDIUM', 'HARD'] as const) {
      const played = gp[baseKey][d];
      if (played > 0) {
        const wins = gw[baseKey][d];
        rows.push({
          label: `${baseLabel} (${titleCase(d.toLowerCase())})`,
          wins,
          played,
          rate: (100 * wins) / played,
        });
      }
    }
  }
  rows.sort((a, b) => b.rate - a.rate || b.played - a.played);
  return rows;
}

export function formatLeaderboardLines(p: ProfileData): string[] {
  const rows = formatLeaderboardRows(p);
  const lines: string[] =
    rows.length === 0
      ? ['Play a game in any mode to start building your record.']
      : rows.map(
          (r, i) => `${i + 1}. ${r.label} — ${r.wins}/${r.played} won (${Math.round(r.rate)}%)`,
        );
  const finishEntries = Object.entries(p.multi_card_finishes);
  const best = finishEntries.reduce<[string, number] | null>(
    (acc, cur) => (acc === null || cur[1] > acc[1] ? cur : acc),
    null,
  );
  if (best && best[1] > 0) {
    lines.push(`Signature finish: ${titleCase(best[0])} (${best[1]} time${best[1] !== 1 ? 's' : ''})`);
  }
  lines.push(`Badges earned: ${Object.keys(p.badges).length} / ${Object.keys(BADGE_DEFS).length}`);
  return lines;
}

/**
 * The one function ProfileScene.ts calls for every position/size,
 * given the current scroll offset and the profile to display — direct
 * analogue of `draw()`.
 */
export function computeProfileFlow(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  scrollOffset: number,
  profile: ProfileData,
): ProfileFlow {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const titleFontPx = fontPx('ui_large', scale);
  const headerFontPx = fontPx('ui_medium', scale);
  const bodyFontPx = fontPx('ui_normal', scale);
  const tinyFontPx = fontPx('ui_tiny', scale);

  const viewportTop = contentRect.y + BASE_TITLE_Y * scale + lineHeight(titleFontPx) + BASE_TITLE_GAP * scale;
  const viewportHeight = Math.max(0, contentRect.y + contentRect.height - viewportTop - BASE_BOTTOM_MARGIN * scale);

  const padOuter = BASE_PAD_OUTER * scale;
  const lineH = BASE_LINE_H * scale;
  const sectionGap = BASE_SECTION_GAP * scale;
  const headerGap = BASE_HEADER_GAP * scale;

  const cardWidth = computeCardWidth(contentRect, scale);
  const cardLeft = centerX - cardWidth / 2;
  const textWidth = cardWidth - 2 * padOuter;

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const backButton: RectLayout = {
    x: contentRect.x + BASE_BACK_BUTTON_X * scale,
    y: contentRect.y + BASE_BACK_BUTTON_Y * scale,
    width: backSize.width,
    height: backSize.height,
  };

  let y = viewportTop - scrollOffset + BASE_TOP_INSET * scale;
  const top0 = y;

  function header(text: string): SectionHeaderLayout {
    const h: SectionHeaderLayout = { text, x: cardLeft, y, fontPx: headerFontPx };
    y += lineHeight(headerFontPx) + headerGap;
    return h;
  }

  function textLines(lines: string[]): TextRowLayout[] {
    const out: TextRowLayout[] = [];
    for (const line of lines) {
      for (const wrapped of wrapText(line, tinyFontPx, textWidth)) {
        out.push({ text: wrapped, x: cardLeft, y, fontPx: tinyFontPx });
        y += lineHeight(tinyFontPx);
      }
    }
    return out;
  }

  // ── Stats ──────────────────────────────────────────────────────
  const statsHeader = header('Stats');
  const statsLines = textLines(formatStatsLines(profile));
  y += sectionGap;

  // ── Leaderboard — Your Best Modes ────────────────────────────────
  const leaderboardHeader = header('Leaderboard — Your Best Modes');
  const leaderboardLines = textLines(formatLeaderboardLines(profile));
  y += sectionGap;

  // ── Badges ─────────────────────────────────────────────────────
  const badgesHeader = header('Badges');
  const badgeCategories: BadgeCategorySection[] = [];
  for (const category of BADGE_CATEGORIES) {
    const ids = Object.values(BADGE_DEFS)
      .filter((b) => b.category === category)
      .map((b) => b.id);
    if (ids.length === 0) continue;
    const catHeader: SectionHeaderLayout = { text: category, x: cardLeft, y, fontPx: bodyFontPx };
    y += lineHeight(bodyFontPx) + 4 * scale;
    const rows: BadgeRowLayout[] = [];
    for (const id of ids) {
      const info = BADGE_DEFS[id];
      const earned = Boolean(profile.badges[id]);
      const shareW = BASE_SHARE_BTN_W * scale;
      const shareH = BASE_SHARE_BTN_H * scale;
      const textMaxW = textWidth - 26 * scale - (earned ? shareW + 12 * scale : 0);
      const combined = `${info.name} — ${info.desc}`;
      const wrapped = wrapText(combined, tinyFontPx, textMaxW);
      const lines: TextRowLayout[] = wrapped.map((line, i) => ({
        text: line,
        x: cardLeft + 26 * scale,
        y: y + i * lineHeight(tinyFontPx),
        fontPx: tinyFontPx,
      }));
      const textH = wrapped.length * lineHeight(tinyFontPx);
      const dot = { x: cardLeft + 12 * scale + BASE_BADGE_DOT_R * scale, y: y + BASE_BADGE_DOT_R * scale + 2 * scale, r: BASE_BADGE_DOT_R * scale };
      let rowHeight = Math.max(textH, dot.r * 2);
      let shareButton: RectLayout | null = null;
      if (earned) {
        shareButton = { x: cardLeft + cardWidth - shareW, y: y - 2 * scale, width: shareW, height: shareH };
        rowHeight = Math.max(rowHeight, shareH);
      }
      rows.push({ id, name: info.name, desc: info.desc, category, earned, lines, dot, shareButton, rowHeight });
      y += rowHeight + BASE_BADGE_ROW_GAP * scale;
    }
    badgeCategories.push({ header: catHeader, rows });
    y += 10 * scale;
  }
  y += sectionGap - 10 * scale;

  // ── Cosmetics ──────────────────────────────────────────────────
  function swatchRow(
    kind: 'card_back' | 'felt_theme',
    owned: string[],
    equipped: string,
    styleDefs: Record<string, { colorA?: number; colorB?: number; felt?: number; label: string }>,
  ): CosmeticSwatchLayout[] {
    const swatchW = BASE_SWATCH_W * scale;
    const swatchH = BASE_SWATCH_H * scale;
    const gap = BASE_SWATCH_GAP * scale;
    let x = cardLeft;
    const out: CosmeticSwatchLayout[] = [];
    for (const [key, style] of Object.entries(styleDefs)) {
      if (x + swatchW > cardLeft + cardWidth) {
        x = cardLeft;
        y += swatchH + BASE_SWATCH_ROW_GAP * scale;
      }
      const isOwned = owned.includes(key);
      const isEquipped = key === equipped;
      const rect: RectLayout = { x, y, width: swatchW, height: swatchH };
      const labelPos: TextLayout = { x: rect.x + swatchW / 2, y: rect.y + swatchH + 2 * scale, fontPx: tinyFontPx };
      const statusPos: TextLayout = { x: rect.x + swatchW / 2, y: rect.y + swatchH + BASE_SWATCH_LABEL_GAP * scale, fontPx: tinyFontPx };
      let equipButton: RectLayout | null = null;
      if (isOwned && !isEquipped) {
        equipButton = {
          x: rect.x,
          y: rect.y + swatchH + BASE_EQUIP_BTN_GAP * scale,
          width: swatchW,
          height: BASE_EQUIP_BTN_H * scale,
        };
      }
      const colorA = 'colorA' in style && style.colorA !== undefined ? style.colorA : (style.felt as number);
      const colorB = 'colorB' in style && style.colorB !== undefined ? style.colorB : (style.felt as number);
      out.push({
        kind,
        key,
        label: style.label,
        colorA,
        colorB,
        owned: isOwned,
        equipped: isEquipped,
        hint: cosmeticUnlockHint(kind, key),
        rect,
        labelPos,
        statusPos,
        equipButton,
      });
      x += swatchW + gap;
    }
    y += swatchH + BASE_SWATCH_ROW_GAP * scale;
    return out;
  }

  const cardBacksHeader = header('Cosmetics — Card Backs');
  const cardBackSwatches = swatchRow(
    'card_back',
    profile.cosmetics.owned_card_backs,
    profile.cosmetics.equipped_card_back,
    CARD_BACK_STYLES,
  );
  y += 16 * scale;

  const feltThemesHeader = header('Cosmetics — Table Felt Themes');
  const feltSwatches = swatchRow(
    'felt_theme',
    profile.cosmetics.owned_felt_themes,
    profile.cosmetics.equipped_felt_theme,
    FELT_THEMES,
  );
  y += 30 * scale;

  const contentHeight = y - top0 + BASE_BOTTOM_INSET * scale;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  return {
    scale,
    contentRect,
    viewportTop,
    viewportHeight,
    cardWidth,
    cardLeft,
    backButton,
    statsHeader,
    statsLines,
    leaderboardHeader,
    leaderboardLines,
    badgesHeader,
    badgeCategories,
    cardBacksHeader,
    cardBackSwatches,
    feltThemesHeader,
    feltSwatches,
    contentHeight,
    maxScroll,
  };
}

/** Re-exported so ProfileScene.ts can build its fixed title TextLayout
 * (positioned above viewportTop, outside the scrollable flow) from
 * the same scale this module computed — same pattern as
 * RulesLayout.ts's/SettingsLayout.ts's own computeXTitleLayout(). */
export function computeProfileTitleLayout(rawViewport: Viewport, insets: SafeAreaInsets): TextLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  return {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
}
