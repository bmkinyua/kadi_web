/**
 * KADI web-client — SettingsScene's layout, as pure data.
 *
 * Ported from scenes.SettingsScene's own `_flow()` (scenes.py, class
 * starts at line 2435, `_flow()` at line 2634) — same single-source-
 * of-truth discipline as RulesLayout.ts's own `_flow()` port: one
 * function builds every widget's absolute rect for the CURRENT scroll
 * offset, called fresh by both the scene's render pass and its input
 * handling, so hit-testing can never drift from what's on screen.
 *
 * SCOPE (see next_task_prompt3.md's Part B discussion — the brief's
 * own 4-card summary undercounted this scene; verified directly
 * against `_flow()` line-by-line): eight sections in this exact
 * order, matching the PC original --
 *   1. Timers            2. Deck & Logging   3. Rules (7 toggles)
 *   4. Player Assistance 5. Display          6. Audio
 *   7. Credits           8. Back / Reset buttons
 * The PC's "Advertising (Dev)" card is correctly NOT ported — it was
 * already removed from the PC's own Settings UI (see scenes.py's own
 * comment on `_ads_toggle_key`), so there is nothing to port there.
 * The PC's resolution dropdown (part of card 5, Display) is also NOT
 * ported — obsolete per §6a's continuous scale system, which replaces
 * per-resolution pickers entirely; Display here is Credits-adjacent
 * placement only (no dead placeholder left in its spot).
 *
 * THINGS THIS FILE DELIBERATELY DOES NOT INHERIT FROM THE PC SIDE
 * (same two reasons RulesLayout.ts's header already documents for
 * itself — restated here because they apply again, not copied
 * blindly): card width is a continuous function of `scale`
 * (computeCardWidth below), not `get_ui_scale()`'s per-resolution
 * lookup table; note/paragraph wrapping uses RulesLayout.ts's own
 * `wrapText`/`estimateTextWidth` (imported, not reimplemented) rather
 * than real glyph measurement, for the same "no canvas in a pure
 * module" reason.
 *
 * WIDGET GEOMETRY CONSTANTS below reuse the PC's own baseline pixel
 * values (130x36 number boxes, 220x48 buttons, etc.) directly as this
 * renderer's BASE_* constants, exactly as RulesLayout.ts already did
 * for its own back button (BASE_BACK_BUTTON_WIDTH/HEIGHT = 220/48,
 * copied verbatim from scenes.py) — these are absolute, legible
 * control sizes, not resolution-relative chrome, so reusing the same
 * numbers at this renderer's own scale=1 baseline keeps both ported
 * scrollable screens visually consistent with each other, not just
 * each independently "close enough" to the PC.
 *
 * WIDGET *STATE* (current values, focus, drag) is NOT part of this
 * file, same as NumberBox/Slider/Button's mutable state lives outside
 * `_flow()` on the PC side — this module only computes WHERE things
 * go. SettingsScene.ts owns the actual SettingsValues and edits them
 * in response to input. Every row's geometry below is independent of
 * the current values (verified against `_flow()`: no branch there
 * sizes or positions anything from a live value, only from fixed
 * label/unit strings and font metrics) — so, unlike a naive port,
 * `computeSettingsFlow()` doesn't need the current SettingsValues at
 * all, only the viewport/insets/scrollOffset RulesLayout.ts's own
 * `computeRulesFlow()` already takes.
 *
 * SCROLL PHYSICS come from ./scrollPhysics.ts, not this file — see
 * that module's own header for why it's shared rather than
 * RulesScene- or SettingsScene-specific.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { RectLayout } from './InternetLobbyLayout.js';
import { estimateTextWidth, wrapText } from './RulesLayout.js';

// ── Field keys — the vocabulary SettingsScene.ts and this file share
// so a row can say WHICH value it's for without this file needing to
// know anything about SettingsValues itself beyond the key names. ──

export type NumberFieldKey =
  | 'turnTimerSecs'
  | 'postPlayDelaySecs'
  | 'counterWindowSecs'
  | 'hintThresholdPct'
  | 'maxLogPairs';

/** The 7 "Rules" card toggles plus the 3 toggles that live in other
 * cards (Player Assistance's hint toggle, Audio's music/sfx toggles)
 * — one flat union since every toggle is drawn identically (see
 * `_toggle_btns` on the PC side, which is like this: one dict for
 * every non-ads toggle regardless of which card it's drawn in). */
export type ToggleFieldKey =
  | 'timersEnabled'
  | 'suitChangeAfterShield'
  | 'aceSuitIntegrity'
  | 'pickupShieldQkAllowed'
  | 'aceFinisherEnabled'
  | 'jumpMultiCardEnabled'
  | 'cardAnimationsEnabled'
  | 'hintsEnabled'
  | 'musicEnabled'
  | 'sfxEnabled';

export type SliderFieldKey = 'musicVolume' | 'sfxVolume';

export type JokerCount = 2 | 4;
export type LogLevel = 'OFF' | 'LOW' | 'HIGH';

/** Every SettingsScene field this web pass actually persists/edits.
 * Deliberately excludes `resolution` and `skip_startup_resolution_
 * picker` (obsolete here — §6a) and `ads_enabled` (already pulled
 * from the PC's own Settings UI, see this file's header) from
 * core/settings_store.py's DEFAULTS — every other key there has a
 * camelCase counterpart here. */
export interface SettingsValues {
  turnTimerSecs: number;
  postPlayDelaySecs: number;
  counterWindowSecs: number;
  jokerCount: JokerCount;
  logLevel: LogLevel;
  maxLogPairs: number;
  timersEnabled: boolean;
  suitChangeAfterShield: boolean;
  aceSuitIntegrity: boolean;
  pickupShieldQkAllowed: boolean;
  aceFinisherEnabled: boolean;
  jumpMultiCardEnabled: boolean;
  cardAnimationsEnabled: boolean;
  hintsEnabled: boolean;
  hintThresholdPct: number;
  musicEnabled: boolean;
  sfxEnabled: boolean;
  musicVolume: number;
  sfxVolume: number;
}

/** Mirrors core/settings_store.py's DEFAULTS exactly (same numeric
 * values), minus the three excluded keys noted above. Used both as
 * SettingsScene.ts's fallback when nothing is persisted yet, and by
 * "Reset to Defaults" (mirrors `reset_to_defaults()`'s own
 * `apply_settings_dict(gm, DEFAULTS)`). */
export const DEFAULT_SETTINGS: SettingsValues = {
  turnTimerSecs: 150,
  postPlayDelaySecs: 60,
  counterWindowSecs: 60,
  jokerCount: 2,
  logLevel: 'HIGH',
  maxLogPairs: 0,
  timersEnabled: true,
  suitChangeAfterShield: false,
  aceSuitIntegrity: false,
  pickupShieldQkAllowed: true,
  aceFinisherEnabled: true,
  jumpMultiCardEnabled: true,
  cardAnimationsEnabled: true,
  hintsEnabled: false,
  hintThresholdPct: 50,
  musicEnabled: true,
  sfxEnabled: true,
  musicVolume: 0.5,
  sfxVolume: 0.5,
};

/** Per-field min/max/step, mirroring each NumberBox's own constructor
 * args in `on_enter()` (scenes.py lines 2459-2468). */
export const NUMBER_FIELD_RANGES: Record<NumberFieldKey, { min: number; max: number; step: number }> = {
  turnTimerSecs: { min: 0, max: 300, step: 5 },
  postPlayDelaySecs: { min: 0, max: 120, step: 1 },
  counterWindowSecs: { min: 0, max: 120, step: 1 },
  hintThresholdPct: { min: 0, max: 100, step: 5 },
  maxLogPairs: { min: 0, max: 999, step: 10 },
};

export const NUMBER_FIELD_LABELS: Record<NumberFieldKey, string> = {
  turnTimerSecs: 'Turn timer',
  postPlayDelaySecs: 'Next-player delay / KADI check',
  counterWindowSecs: 'J counter window',
  hintThresholdPct: 'Hint delay (% of turn timer)',
  maxLogPairs: 'Max saved log files',
};

export const TOGGLE_FIELD_LABELS: Record<ToggleFieldKey, string> = {
  timersEnabled: 'Turn Timers Enabled',
  suitChangeAfterShield: 'Suit Change After Shield',
  aceSuitIntegrity: 'ACE (A) Card Suit Integrity',
  pickupShieldQkAllowed: 'Question/Kickback+ACE Can Shield Pick-up',
  aceFinisherEnabled: 'ACE Multi-Card Finish',
  jumpMultiCardEnabled: 'Jump Multi-Card Play',
  cardAnimationsEnabled: 'Card Animations',
  hintsEnabled: 'Card Play Hints',
  musicEnabled: 'Background Music',
  sfxEnabled: 'Sound Effects',
};

/** Verbatim from rendering/asset_loader.py's MUSIC_CREDITS — this IS
 * the actual copy (same "not rewritten wording" rule RulesLayout.ts's
 * RULES_SECTIONS follows), formatted the same way `_flow()`'s Credits
 * card formats each entry: `{slot}: "{title}" by {author} ({license})`. */
export const CREDITS_LINES: string[] = [
  'Menu Theme: "Jazzy blues" by LushoGames (CC0)',
  'Gameplay Ambient: "Heavenly Loop" by isaiah658 (CC0)',
  'Chuo Drums: "Djembe Loop 08 - 120 BPM" by Ancient.Sounds (CC0)',
];

// ── Row shapes — one discriminated union covering every widget kind
// `_flow()` emits, restated as pre-positioned geometry only. ──

export interface NumberBoxRowLayout {
  kind: 'numbox';
  key: NumberFieldKey;
  label: TextLayout;
  maxLabel: TextLayout;
  box: RectLayout;
  minus: RectLayout;
  plus: RectLayout;
  /** True only for maxLogPairs — its label/max-label pair is drawn
   * differently ("(0 = unlimited)" instead of "(max Ns)"), mirroring
   * `_flow()`/draw()'s separate 'logcap' row kind. Kept as a flag on
   * the same 'numbox' kind rather than a wholly separate row kind
   * since geometry-wise they're identical — only the max-label TEXT
   * differs, which SettingsScene.ts can derive from this flag plus
   * NUMBER_FIELD_RANGES without this file needing two near-duplicate
   * row shapes. */
  isLogCap: boolean;
}

export interface LabelRowLayout {
  kind: 'label';
  text: TextLayout & { value: string };
}

export interface NoteRowLayout {
  kind: 'note';
  lines: (TextLayout & { text: string })[];
}

export interface JokerRowLayout {
  kind: 'joker';
  two: RectLayout;
  four: RectLayout;
}

export interface LogLevelRowLayout {
  kind: 'logLevel';
  off: RectLayout;
  low: RectLayout;
  high: RectLayout;
}

export interface ToggleRowLayout {
  kind: 'toggle';
  key: ToggleFieldKey;
  label: TextLayout & { value: string };
  button: RectLayout;
}

export interface SliderRowLayout {
  kind: 'slider';
  key: SliderFieldKey;
  label: string;
  track: RectLayout;
}

export type SettingsRowLayout =
  | NumberBoxRowLayout
  | LabelRowLayout
  | NoteRowLayout
  | JokerRowLayout
  | LogLevelRowLayout
  | ToggleRowLayout
  | SliderRowLayout;

export interface SettingsCardLayout {
  panelRect: RectLayout;
  title: TextLayout & { text: string };
  rows: SettingsRowLayout[];
}

export interface SettingsFlow {
  scale: number;
  contentRect: ContentRect;
  viewportTop: number;
  viewportHeight: number;
  cardWidth: number;
  cards: SettingsCardLayout[];
  backButton: RectLayout;
  resetButton: RectLayout;
  contentHeight: number;
  maxScroll: number;
}

// ── baseline constants -- see this file's header on why these reuse
// the PC's own pixel values directly rather than re-tuning them. ──
const BASE_TITLE_Y = 18;
const BASE_TITLE_GAP = 20;
const BASE_TOP_INSET = 16;
const BASE_BOTTOM_INSET = 16;
const BASE_PAD_OUTER = 24; // scenes.SettingsScene.PAD_OUTER
const BASE_CARD_GAP = 18; // scenes.SettingsScene.CARD_GAP
const BASE_ROW_H = 56; // scenes.SettingsScene.ROW_H
const BASE_BOTTOM_MARGIN = 16;
const BASE_LINE_H = 20; // matches `_wrap_note`'s own `s(20) * len(lines)` line pitch
const BASE_NUMBOX_W = 130;
const BASE_NUMBOX_H = 36;
const BASE_STEP_W = 28;
const BASE_STEP_GAP = 6;
const BASE_LOGCAP_W = 150;
const BASE_JOKER_BTN_W = 90;
const BASE_JOKER_BTN_H = 40;
const BASE_JOKER_GAP = 14;
const BASE_LOGLEVEL_BTN_W = 110;
const BASE_LOGLEVEL_BTN_H = 40;
const BASE_LOGLEVEL_GAP = 12;
const BASE_TOGGLE_LABEL_GAP = 28;
const BASE_TOGGLE_BTN_W = 110;
const BASE_TOGGLE_BTN_H = 38;
const BASE_TOGGLE_ROW_GAP = 16; // gap after a Rules-card toggle row
const BASE_SLIDER_H = 14;
const BASE_BACK_BUTTON_WIDTH = 220; // matches RulesLayout.ts's own back button size verbatim
const BASE_BACK_BUTTON_HEIGHT = 48;
const BASE_BACK_RESET_GAP = 16;
const BASE_RESET_BOTTOM_GAP = 24;

const BASE_CARD_WIDTH = 420; // matches RulesLayout.ts's own BASE_CARD_WIDTH
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

/** Word-wraps `text` against this card's text column width, returning
 * positioned lines starting at `startY` — the shared tail end of
 * every 'note' row's layout math (mirrors `_wrap_note()` plus the
 * `y += s(20) * len(lines)` advance every note-producing branch in
 * `_flow()` repeats). Centered on `centerX`, matching `_flow()`'s own
 * notes (drawn via `cx - ns.get_width() // 2`, i.e. center-aligned,
 * unlike every other row kind here which is left-aligned). */
function layoutNote(
  text: string,
  centerX: number,
  y: number,
  textWidth: number,
  fontPxValue: number,
  lineH: number,
): { row: NoteRowLayout; nextY: number } {
  const wrapped = wrapText(text, fontPxValue, textWidth);
  const lines = wrapped.map((line, i) => ({
    x: centerX,
    y: y + i * lineH,
    fontPx: fontPxValue,
    text: line,
  }));
  return { row: { kind: 'note', lines }, nextY: y + wrapped.length * lineH };
}

/**
 * The one function SettingsScene.ts calls for every position/size,
 * given the current scroll offset — direct analogue of `_flow()`.
 * See this file's header on why, unlike a naive port, this needs no
 * SettingsValues argument (row geometry never depends on a live
 * value on the PC side either).
 */
export function computeSettingsFlow(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  scrollOffset: number,
): SettingsFlow {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const titleFontPx = fontPx('ui_large', scale);
  const headerFontPx = fontPx('ui_medium', scale);
  const bodyFontPx = fontPx('ui_normal', scale);
  const tinyFontPx = fontPx('ui_tiny', scale);

  const viewportTop = contentRect.y + BASE_TITLE_Y * scale + lineHeight(titleFontPx) + BASE_TITLE_GAP * scale;
  const viewportHeight = Math.max(
    0,
    contentRect.y + contentRect.height - viewportTop - BASE_BOTTOM_MARGIN * scale,
  );

  const padOuter = BASE_PAD_OUTER * scale;
  const cardGap = BASE_CARD_GAP * scale;
  const rowH = BASE_ROW_H * scale;
  const lineH = BASE_LINE_H * scale;
  const stepW = BASE_STEP_W * scale;
  const stepGap = BASE_STEP_GAP * scale;

  const cardWidth = computeCardWidth(contentRect, scale);
  const cardLeft = centerX - cardWidth / 2;
  const textWidth = cardWidth - 2 * padOuter;

  const top0 = viewportTop - scrollOffset + BASE_TOP_INSET * scale;
  let y = top0;
  const cards: SettingsCardLayout[] = [];

  function numberBoxRow(key: NumberFieldKey, rowY: number, isLogCap: boolean): NumberBoxRowLayout {
    const boxW = (isLogCap ? BASE_LOGCAP_W : BASE_NUMBOX_W) * scale;
    const boxH = BASE_NUMBOX_H * scale;
    const box: RectLayout = { x: cardLeft + cardWidth - padOuter - boxW, y: rowY, width: boxW, height: boxH };
    const minus: RectLayout = { x: box.x - stepW - stepGap, y: rowY, width: stepW, height: boxH };
    const plus: RectLayout = { x: box.x + boxW + stepGap, y: rowY, width: stepW, height: boxH };
    const label: TextLayout = { x: cardLeft + padOuter, y: rowY, fontPx: bodyFontPx };
    const maxLabel: TextLayout = { x: cardLeft + padOuter, y: rowY + lineHeight(bodyFontPx) + 1, fontPx: tinyFontPx };
    return { kind: 'numbox', key, label, maxLabel, box, minus, plus, isLogCap };
  }

  function toggleRow(key: ToggleFieldKey, rowY: number): { rows: ToggleRowLayout[]; nextY: number } {
    const label: TextLayout & { value: string } = {
      x: centerX,
      y: rowY,
      fontPx: bodyFontPx,
      value: `${TOGGLE_FIELD_LABELS[key]}:`,
    };
    const btnW = BASE_TOGGLE_BTN_W * scale;
    const btnH = BASE_TOGGLE_BTN_H * scale;
    const btnY = rowY + BASE_TOGGLE_LABEL_GAP * scale;
    const button: RectLayout = { x: centerX - btnW / 2, y: btnY, width: btnW, height: btnH };
    return { rows: [{ kind: 'toggle', key, label, button }], nextY: btnY + btnH };
  }

  function cardStart(): void {
    y += padOuter;
    y += 30 * scale; // header row height, matching card_start()'s own `y += s(30)`
  }

  // ── Card: Timers ─────────────────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    const timerKeys: NumberFieldKey[] = ['turnTimerSecs', 'postPlayDelaySecs', 'counterWindowSecs'];
    for (const key of timerKeys) {
      rows.push(numberBoxRow(key, y, false));
      y += rowH;
    }
    const note = layoutNote('Set to 0 to disable timers', centerX, y, textWidth, tinyFontPx, lineH);
    rows.push(note.row);
    y = note.nextY + 6 * scale;
    y += padOuter;
    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: { x: cardLeft + padOuter, y: cardTop + padOuter - 2 * scale, fontPx: headerFontPx, text: 'Timers' },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Deck & Logging ─────────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];

    rows.push({ kind: 'label', text: { x: centerX, y, fontPx: headerFontPx, value: 'Jokers per Deck:' } });
    y += 30 * scale;
    const jokerBw = BASE_JOKER_BTN_W * scale;
    const jokerGap = BASE_JOKER_GAP * scale;
    const jokerTotal = jokerBw * 2 + jokerGap;
    const jokerBx = cardLeft + (cardWidth - jokerTotal) / 2;
    const jokerH = BASE_JOKER_BTN_H * scale;
    rows.push({
      kind: 'joker',
      two: { x: jokerBx, y, width: jokerBw, height: jokerH },
      four: { x: jokerBx + jokerBw + jokerGap, y, width: jokerBw, height: jokerH },
    });
    y += jokerH + padOuter;

    rows.push({
      kind: 'label',
      text: { x: centerX, y, fontPx: headerFontPx, value: 'Logging (for bug reports):' },
    });
    y += 30 * scale;
    const logBw = BASE_LOGLEVEL_BTN_W * scale;
    const logGap = BASE_LOGLEVEL_GAP * scale;
    const logTotal = logBw * 3 + logGap * 2;
    const logBx = cardLeft + (cardWidth - logTotal) / 2;
    const logH = BASE_LOGLEVEL_BTN_H * scale;
    rows.push({
      kind: 'logLevel',
      off: { x: logBx, y, width: logBw, height: logH },
      low: { x: logBx + logBw + logGap, y, width: logBw, height: logH },
      high: { x: logBx + 2 * (logBw + logGap), y, width: logBw, height: logH },
    });
    y += logH + 6 * scale;
    const logNote = layoutNote(
      "HIGH writes a detailed log file to the 'logs' folder — share it when reporting bugs",
      centerX,
      y,
      textWidth,
      tinyFontPx,
      lineH,
    );
    rows.push(logNote.row);
    y = logNote.nextY + 6 * scale;
    y += padOuter;

    rows.push(numberBoxRow('maxLogPairs', y, true));
    const logcapTwoLineH = lineHeight(bodyFontPx) + 1 + lineHeight(tinyFontPx);
    y += Math.max(BASE_NUMBOX_H * scale, logcapTwoLineH) + 6 * scale;
    const capNote = layoutNote(
      "Deletes oldest saved logs beyond this count — they're also Chuo/MSOMI training data, so keep unlimited unless disk space is a concern",
      centerX,
      y,
      textWidth,
      tinyFontPx,
      lineH,
    );
    rows.push(capNote.row);
    y = capNote.nextY + 6 * scale;
    y += padOuter;

    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: {
        x: cardLeft + padOuter,
        y: cardTop + padOuter - 2 * scale,
        fontPx: headerFontPx,
        text: 'Deck & Logging',
      },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Rules ───────────────────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    const ruleKeys: ToggleFieldKey[] = [
      'timersEnabled',
      'suitChangeAfterShield',
      'aceSuitIntegrity',
      'pickupShieldQkAllowed',
      'aceFinisherEnabled',
      'jumpMultiCardEnabled',
      'cardAnimationsEnabled',
    ];
    for (const key of ruleKeys) {
      const { rows: toggleRows, nextY } = toggleRow(key, y);
      rows.push(...toggleRows);
      y = nextY + BASE_TOGGLE_ROW_GAP * scale;
    }
    y += padOuter - BASE_TOGGLE_ROW_GAP * scale;
    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: { x: cardLeft + padOuter, y: cardTop + padOuter - 2 * scale, fontPx: headerFontPx, text: 'Rules' },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Player Assistance ─────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    const { rows: hintToggleRows, nextY } = toggleRow('hintsEnabled', y);
    rows.push(...hintToggleRows);
    y = nextY + 18 * scale;

    rows.push(numberBoxRow('hintThresholdPct', y, false));
    y += rowH;
    const hintNote = layoutNote(
      "Highlights one legal card once you've used this % of your turn timer. Needs Turn Timers Enabled and a non-zero Turn Timer above. Not a strategy hint — just something you can legally play.",
      centerX,
      y,
      textWidth,
      tinyFontPx,
      lineH,
    );
    rows.push(hintNote.row);
    y = hintNote.nextY + 6 * scale;
    y += padOuter;

    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: {
        x: cardLeft + padOuter,
        y: cardTop + padOuter - 2 * scale,
        fontPx: headerFontPx,
        text: 'Player Assistance',
      },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Display ────────────────────────────────────────────────
  // Deliberately just the note -- the resolution dropdown itself is
  // NOT ported (see this file's header: obsolete per §6a). Kept as
  // its own titled card rather than removed entirely so a player who
  // remembers the PC's Display card isn't left wondering where
  // display-related settings went — the note explains directly.
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    const note = layoutNote(
      'This version automatically fits your window or device screen — there is no separate resolution setting to choose.',
      centerX,
      y,
      textWidth,
      tinyFontPx,
      lineH,
    );
    rows.push(note.row);
    y = note.nextY + 6 * scale;
    y += padOuter;
    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: { x: cardLeft + padOuter, y: cardTop + padOuter - 2 * scale, fontPx: headerFontPx, text: 'Display' },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Audio ──────────────────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    const sliderW = cardWidth - 2 * padOuter;
    const sliderH = BASE_SLIDER_H * scale;

    const { rows: musicToggleRows, nextY: afterMusicToggle } = toggleRow('musicEnabled', y);
    rows.push(...musicToggleRows);
    y = afterMusicToggle + 24 * scale;
    rows.push({
      kind: 'slider',
      key: 'musicVolume',
      label: 'Music Volume',
      track: { x: cardLeft + padOuter, y, width: sliderW, height: sliderH },
    });
    y += sliderH + 22 * scale;
    const musicNote = layoutNote(
      'Controls the menu/gameplay music and the Chuo drum layer together.',
      centerX,
      y,
      textWidth,
      tinyFontPx,
      lineH,
    );
    rows.push(musicNote.row);
    y = musicNote.nextY + 14 * scale;

    const { rows: sfxToggleRows, nextY: afterSfxToggle } = toggleRow('sfxEnabled', y);
    rows.push(...sfxToggleRows);
    y = afterSfxToggle + 24 * scale;
    rows.push({
      kind: 'slider',
      key: 'sfxVolume',
      label: 'Sound Effects Volume',
      track: { x: cardLeft + padOuter, y, width: sliderW, height: sliderH },
    });
    y += sliderH + 22 * scale;
    const sfxNote = layoutNote('Controls card-play and UI sound effects.', centerX, y, textWidth, tinyFontPx, lineH);
    rows.push(sfxNote.row);
    y = sfxNote.nextY + 6 * scale;
    y += padOuter;

    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: { x: cardLeft + padOuter, y: cardTop + padOuter - 2 * scale, fontPx: headerFontPx, text: 'Audio' },
      rows,
    });
    y += cardGap;
  }

  // ── Card: Credits ────────────────────────────────────────────────
  {
    const cardTop = y;
    cardStart();
    const rows: SettingsRowLayout[] = [];
    for (const line of CREDITS_LINES) {
      const note = layoutNote(line, centerX, y, textWidth, tinyFontPx, lineH);
      rows.push(note.row);
      y = note.nextY + 8 * scale;
    }
    y += padOuter - 8 * scale;
    cards.push({
      panelRect: { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop },
      title: { x: cardLeft + padOuter, y: cardTop + padOuter - 2 * scale, fontPx: headerFontPx, text: 'Credits' },
      rows,
    });
    y += cardGap;
  }

  // ── Back / Reset buttons ─────────────────────────────────────────
  const backSize = enforceMinTouchTarget({ width: BASE_BACK_BUTTON_WIDTH * scale, height: BASE_BACK_BUTTON_HEIGHT * scale });
  const backButton: RectLayout = { x: centerX - backSize.width / 2, y, width: backSize.width, height: backSize.height };
  y += backSize.height + BASE_BACK_RESET_GAP * scale;

  const resetSize = enforceMinTouchTarget({ width: BASE_BACK_BUTTON_WIDTH * scale, height: BASE_BACK_BUTTON_HEIGHT * scale });
  const resetButton: RectLayout = { x: centerX - resetSize.width / 2, y, width: resetSize.width, height: resetSize.height };
  y += resetSize.height + BASE_RESET_BOTTOM_GAP * scale;

  const contentHeight = y - top0 + BASE_BOTTOM_INSET * scale;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  return {
    scale,
    contentRect,
    viewportTop,
    viewportHeight,
    cardWidth,
    cards,
    backButton,
    resetButton,
    contentHeight,
    maxScroll,
  };
}

// Re-exported so SettingsScene.ts can build its fixed title TextLayout
// (positioned above viewportTop, outside the scrollable flow) from
// the same scale the rest of this module computed -- same pattern as
// RulesLayout.ts's own computeRulesTitleLayout().
export function computeSettingsTitleLayout(rawViewport: Viewport, insets: SafeAreaInsets): TextLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  return {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
}

// Re-exported for SettingsScene.ts's use when rendering numbox
// display text ("(max Ns)" / "(0 = unlimited)") without needing its
// own copy of these ranges.
export { estimateTextWidth, wrapText };
