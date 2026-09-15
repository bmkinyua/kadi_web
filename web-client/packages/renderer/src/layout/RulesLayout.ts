/**
 * KADI web-client — RulesScene's ("How to Play") layout, as pure data.
 *
 * Ported from scenes.RulesScene's own `_flow()` (scenes.py): stacked
 * panel cards, each a title plus wrapped paragraph blocks, laid out
 * top-to-bottom with a running `y` -- same single-source-of-truth
 * pattern `_flow()`'s own docstring describes (called identically for
 * drawing and for hit-testing/scroll-limit math on the PC side; here,
 * the one call site is RulesScene.ts's render(), called on every
 * scroll-offset change AND every genuine resize, same as every other
 * scene's currentLayout()).
 *
 * TWO THINGS THIS FILE DELIBERATELY DOES NOT INHERIT FROM THE PC SIDE:
 *
 * 1. get_ui_scale()'s `menu_w` is a per-resolution lookup table
 *    (constants.py's UI_SCALE_PROFILES), tuned for the 8 fixed
 *    resolutions a PC player explicitly picks from. This renderer has
 *    no such picker (see scale.ts's own header) -- card width here is
 *    instead a continuous function of `scale`, capped so it neither
 *    hugs the very edges of a wide desktop window nor collapses too
 *    narrow on the smallest supported phone. Not a literal port, a
 *    reasonable translation of the same intent (a comfortably-wide,
 *    centered reading column) onto a system with no fixed lookup
 *    table to draw from.
 * 2. wrap_text() (rendering/widgets.py) measures real glyph widths via
 *    `pygame.font.Font.size()`. A pure, Phaser-free layout module has
 *    no canvas/DOM to ask for real text metrics (this file must stay
 *    unit-testable without a live Scene -- see this file's own tests),
 *    so `estimateTextWidth()` below is a deliberate approximation
 *    (average glyph width as a fraction of font size) rather than a
 *    real measurement. It's tuned to overestimate width slightly, so
 *    wrapping breaks a little EARLY rather than a genuine rendered
 *    line ever overflowing its panel -- the safer of the two possible
 *    approximation errors. `wrapText()` itself is otherwise a direct
 *    port of `wrap_text()`'s greedy algorithm, including the
 *    character-boundary binary-search fallback for a single word
 *    still too wide for its own line (this content's SECTIONS never
 *    actually needs that fallback, but it's ported for the same
 *    reason the PC original added it: a future paragraph shouldn't
 *    silently overflow just because nobody had a reason to test it
 *    with the one input that trips a text-wrapping edge case, an
 *    unbreakable long "word").
 *
 * SCROLL PHYSICS (bounded overshoot, eased settle) come from
 * ./scrollPhysics.ts, NOT from this file -- that module is shared
 * with any future scrolling scene (Settings), same as scenes.py's own
 * module-level `_scroll_wheel_delta`/`_settle_scroll` are shared
 * across SettingsScene/RulesScene/ChuoScene there.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { RectLayout } from './InternetLobbyLayout.js';

/** A single positioned line of already-wrapped text -- both a
 * section's title and each line of its wrapped body paragraphs use
 * this same shape; RulesScene.ts tells them apart by which array
 * (`title` vs `bodyLines`) they came from, styling each accordingly. */
export interface RulesTextLine {
  x: number;
  y: number;
  fontPx: number;
  text: string;
}

export interface RulesSectionLayout {
  /** Absolute position for THIS render (already offset by the current
   * scrollOffset) -- panels above the viewport or below it are still
   * included here; RulesScene.ts is expected to skip drawing (and,
   * ideally, skip creating GameObjects for) any panelRect that falls
   * entirely outside [viewportTop, viewportTop + viewportHeight],
   * mirroring `_flow()`'s own caller (`draw()`) doing the same
   * bounds check before blitting each card. */
  panelRect: RectLayout;
  title: RulesTextLine;
  bodyLines: RulesTextLine[];
}

export interface RulesFlow {
  scale: number;
  contentRect: ContentRect;
  /** Y coordinate where the scrollable viewport begins -- below the
   * fixed "How to Play" title, mirroring `_viewport_top` on the PC
   * side (there, derived from the title's actual rendered height;
   * here, from `fontPx('ui_large', scale)` plus the same estimated
   * line-height ratio used throughout this file, since no live text
   * metrics exist in a pure module). */
  viewportTop: number;
  /** How tall the visible scrolling area is -- content between
   * viewportTop and viewportTop + viewportHeight is what's actually
   * on screen at any given scrollOffset. */
  viewportHeight: number;
  cardWidth: number;
  sections: RulesSectionLayout[];
  backButton: RectLayout;
  /** Total stacked height of every section + the back button,
   * independent of the current scrollOffset (mirrors `_flow()`'s own
   * `_content_height`, which cancels the scrollOffset it was built
   * from -- see this file's computeRulesFlow() for the same
   * cancellation). This is what maxScroll below is computed from. */
  contentHeight: number;
  /** How far scrollOffset can go before hitting the bottom -- mirrors
   * `_max_scroll()`. 0 if all content already fits in the viewport. */
  maxScroll: number;
}

// ── baseline constants, all scaled by `scale` like every other layout
// module here -- direct analogues of RulesScene's own PAD_OUTER/
// CARD_GAP/LINE_GAP/PARA_GAP class constants (scenes.py), expressed at
// this renderer's own baseline (scale.ts's BASE_WIDTH/BASE_HEIGHT)
// rather than the PC's per-resolution chrome_scale.
const BASE_TITLE_Y = 18;
const BASE_TITLE_GAP = 20;
const BASE_TOP_INSET = 16;
const BASE_BOTTOM_INSET = 16;
const BASE_PAD_OUTER = 22;
const BASE_CARD_GAP = 16;
const BASE_LINE_GAP = 6;
const BASE_PARA_GAP = 12;
const BASE_HEADER_GAP = 8;
const BASE_BOTTOM_MARGIN = 16;
const BASE_BACK_BUTTON_WIDTH = 220;
const BASE_BACK_BUTTON_HEIGHT = 48;

/** Natural (uncapped) card width at scale 1 -- deliberately close to
 * this renderer's own BASE_WIDTH (480, scale.ts) so a baseline phone
 * viewport gets a card that fills most of its width with a small
 * margin either side, the same "one comfortably-wide column" reading
 * shape scenes.py's own card achieves at its OWN baseline. */
const BASE_CARD_WIDTH = 420;
/** Never shrinks the reading column below this (scaled) width even on
 * the narrowest supported viewport -- analogous to `_flow()`'s own
 * `max(380, ...)` floor, just expressed relative to this renderer's
 * own scale rather than a fixed pixel value tuned for desktop. */
const BASE_MIN_CARD_WIDTH = 300;
/** Minimum breathing room either side of the card on a very wide
 * desktop viewport -- analogous to `_flow()`'s own `sw - 80` ceiling. */
const BASE_CARD_SIDE_MARGIN = 24;

/** Section content, verbatim from scenes.RulesScene.SECTIONS -- this
 * IS the actual copy (see next_task_prompt2.md's Part B), not
 * rewritten wording. Kept as plain data here (not re-exported from
 * the Scene) so the layout module and its own tests can wrap/measure
 * it without needing a live Scene either. */
export const RULES_SECTIONS: [string, string[]][] = [
  ['The Basics', [
    'KADI is played with a standard 52-card deck across 4 suits ' +
    '(Spades, Love, Dice, Flowers), plus 2 or 4 Jokers depending on ' +
    'the Jokers per Deck setting.',
    'Each player starts with 4 cards. The discard pile always opens ' +
    'on a plain Finishing card (4, 5, 6, 7, 9, or 10).',
    'On your turn, play a card (or a valid multi-card combo) that ' +
    "matches the suit or rank of the top discard card, or draw a " +
    "card if you can't or don't want to play.",
  ]],
  ['Card Effects', [
    '4, 5, 6, 7, 9, 10 - Finishing: plain cards with no special ' +
    'effect. You can only end your hand on one of these.',
    '8 and Q - Question: must be followed in the same play by a ' +
    'connecting answer card (any Finishing, pick-up, J, K, or ACE). ' +
    'Play Questions with no answer and you draw 1 penalty card.',
    "J - Jump: skips the next player's turn. Several Js played " +
    'together skip that many players (in a 2-player game this ' +
    'instead grants you an extra turn). The player about to be ' +
    'jumped can counter by playing a J of their own within the ' +
    "counter window (see Settings) - if they don't, they're " +
    'jumped. J is the only card that can counter a J.',
    'K - Kickback: reverses the direction of play. An odd number ' +
    'of Ks must be played alone. Play an even number of Ks ' +
    'together and the reversal cancels out, returning the turn ' +
    'to you instead - you may then bundle any valid answer card ' +
    'onto that same play.',
    'ACE (A): lets you declare a new current suit, or shields you ' +
    'from an active pick-up chain instead of drawing.',
    '2: forces the next player to pick up 2 cards or counter. ' +
    '3: forces the next player to pick up 3 cards or counter.',
    'Joker: wild pick-up-5 card. Always playable and always ' +
    'counters a pick-up chain, regardless of suit.',
  ]],
  ['Pick-up Chains', [
    'When a 2, 3, or Joker is played, the next player must either ' +
    'play another pick-up card to stack the total, or draw the full ' +
    'accumulated total.',
    'Cards of the same rank always stack (e.g. 2 then 2). Mixing 2s ' +
    'and 3s requires matching the suit of the previous card in the ' +
    'chain.',
    'A Joker resets the suit requirement - any pick-up card can ' +
    'follow a Joker, regardless of suit.',
    'An ACE can shield (cancel) an active pick-up chain entirely ' +
    'instead of being drawn against.',
  ]],
  ['Playing Multiple Cards', [
    'Cards of the same rank can always be played together as a set ' +
    '(e.g. three 7s).',
    'Question cards (8/Q) can be chained together as long as each ' +
    'links to the one before it by suit or rank, then must be ' +
    'followed by a connecting answer.',
    'J and K chains work the same way - any number of them played ' +
    'together, optionally followed by a connecting answer card.',
    'An ACE can answer any of these chains, and connects to ' +
    'anything.',
  ]],
  ['Declaring KADI & Winning', [
    'Before the play that would empty your hand, you must declare ' +
    'KADI. You can only declare it if your hand will be left with ' +
    'only Finishing cards - or, if other cards remain, you must ' +
    'also hold a Question card among them.',
    'If you declare KADI but then draw a card, get forced to pick ' +
    "up, or fail to finish with a Finishing card, the declaration " +
    "is cancelled and you'll need to declare again later.",
    "Going cardless without having declared KADI doesn't win the " +
    'game - play continues and you draw 1 card on your next turn.',
    'If you legitimately KADI out and no other player is currently ' +
    'cardless at that moment, you win immediately - there is no ' +
    'way to counter a KADI finish itself. The only thing that can ' +
    'stop a KADI win is another player being cardless when your ' +
    'turn comes around.',
  ]],
  ['Settings That Change The Rules', [
    'Jokers per Deck (2 or 4): more Jokers means bigger possible ' +
    'pick-up chains can build up.',
    'ACE (A) Card Suit Integrity (OFF by default): when ON, ACE ' +
    'cards must also match the current suit or rank to be played or ' +
    'to shield a pick-up chain - the same restriction already ' +
    'placed on Q/J/K.',
    'J Counter Window: how long the jumped player has to play a ' +
    'J in response before the jump takes effect.',
  ]],
];

/** Rough average-glyph-width ratio for this renderer's sans-serif UI
 * font, as a fraction of font size in px -- see this file's header
 * note on why an estimate is used instead of real text metrics.
 * Tuned generously wide on purpose (real sans-serif lowercase-heavy
 * body text usually measures narrower than this) so a wrap decision
 * errs toward breaking a line slightly early rather than a real
 * rendered line overflowing its panel. */
const AVG_CHAR_WIDTH_RATIO = 0.56;

export function estimateTextWidth(text: string, fontPxValue: number): number {
  return text.length * fontPxValue * AVG_CHAR_WIDTH_RATIO;
}

/** Rendered line height (ascent+descent, roughly) for a given font
 * size -- another estimate for the same reason estimateTextWidth() is
 * one; 1.2x is a standard-enough approximation for sans-serif body
 * text that every named font tier in scale.ts's FONT_LADDER can share
 * it rather than each needing its own tuned ratio. */
function lineHeight(fontPxValue: number): number {
  return Math.round(fontPxValue * 1.2);
}

/**
 * Greedy word-wrap, returning lines that each fit `maxWidth` at
 * `fontPxValue` per estimateTextWidth() above. Direct port of
 * rendering/widgets.py's `wrap_text()`, including its character-
 * boundary binary-search fallback for a single word that's still too
 * wide for an entire fresh line on its own (see that function's own
 * docstring for why: an unbroken long word with no spaces to break on
 * used to just overflow silently before that fallback existed).
 */
export function wrapText(text: string, fontPxValue: number, maxWidth: number): string[] {
  const words = text.split(' ');
  const lines: string[] = [];
  let cur = '';
  for (const word of words) {
    const trial = (cur + ' ' + word).trim();
    if (estimateTextWidth(trial, fontPxValue) <= maxWidth) {
      cur = trial;
      continue;
    }
    if (!cur) {
      // The word itself doesn't fit even alone on a fresh line --
      // break IT at a character boundary rather than emitting an
      // overflowing line.
      let remaining = word;
      while (estimateTextWidth(remaining, fontPxValue) > maxWidth && remaining.length > 1) {
        let lo = 1;
        let hi = remaining.length;
        let fit = 1;
        while (lo <= hi) {
          const mid = Math.floor((lo + hi) / 2);
          if (estimateTextWidth(remaining.slice(0, mid), fontPxValue) <= maxWidth) {
            fit = mid;
            lo = mid + 1;
          } else {
            hi = mid - 1;
          }
        }
        lines.push(remaining.slice(0, fit));
        remaining = remaining.slice(fit);
      }
      cur = remaining;
    } else {
      lines.push(cur);
      cur = word;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

function computeCardWidth(contentRect: ContentRect, scale: number): number {
  const natural = BASE_CARD_WIDTH * scale;
  const capped = Math.min(natural, contentRect.width - 2 * BASE_CARD_SIDE_MARGIN * scale);
  return Math.max(BASE_MIN_CARD_WIDTH * scale, capped);
}

/**
 * The one function RulesScene.ts calls for every position/size, given
 * the current scroll offset -- direct analogue of `_flow()`, called
 * fresh on every scroll change and every genuine resize (same
 * single-source-of-truth discipline as every other scene here).
 *
 * `scrollOffset` is folded into every returned y-coordinate exactly
 * as `_flow()`'s own `top0 = self._viewport_top - int(self.scroll_
 * offset) + 16` does -- and, as in that function, `contentHeight` on
 * the returned object stays independent of `scrollOffset` (it cancels
 * out algebraically: every position is `top0 + <fixed accumulated
 * offset>`, and `contentHeight` is derived from the accumulated
 * offset alone, not from any absolute y value).
 */
export function computeRulesFlow(
  rawViewport: Viewport,
  insets: SafeAreaInsets,
  scrollOffset: number,
): RulesFlow {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const titleFontPx = fontPx('ui_large', scale);
  const viewportTop = contentRect.y + BASE_TITLE_Y * scale + lineHeight(titleFontPx) + BASE_TITLE_GAP * scale;
  const viewportHeight = Math.max(
    0,
    contentRect.y + contentRect.height - viewportTop - BASE_BOTTOM_MARGIN * scale,
  );

  const padOuter = BASE_PAD_OUTER * scale;
  const cardGap = BASE_CARD_GAP * scale;
  const lineGap = BASE_LINE_GAP * scale;
  const paraGap = BASE_PARA_GAP * scale;
  const headerGap = BASE_HEADER_GAP * scale;

  const cardWidth = computeCardWidth(contentRect, scale);
  const cardLeft = centerX - cardWidth / 2;
  const textWidth = cardWidth - 2 * padOuter;

  const sectionTitleFontPx = fontPx('ui_medium', scale);
  const bodyFontPx = fontPx('ui_normal', scale);
  const sectionTitleLineH = lineHeight(sectionTitleFontPx);
  const bodyLineH = lineHeight(bodyFontPx);

  const top0 = viewportTop - scrollOffset + BASE_TOP_INSET * scale;
  let y = top0;
  const sections: RulesSectionLayout[] = [];

  for (const [title, paragraphs] of RULES_SECTIONS) {
    const cardTop = y;
    y += padOuter;

    const titleLine: RulesTextLine = { x: cardLeft + padOuter, y, fontPx: sectionTitleFontPx, text: title };
    y += sectionTitleLineH + headerGap;

    const bodyLines: RulesTextLine[] = [];
    for (const para of paragraphs) {
      const lines = wrapText(para, bodyFontPx, textWidth);
      for (const line of lines) {
        bodyLines.push({ x: cardLeft + padOuter, y, fontPx: bodyFontPx, text: line });
        y += bodyLineH + lineGap;
      }
      y += paraGap;
    }
    y += padOuter - paraGap;

    const panelRect: RectLayout = { x: cardLeft, y: cardTop, width: cardWidth, height: y - cardTop };
    sections.push({ panelRect, title: titleLine, bodyLines });
    y += cardGap;
  }

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const backButton: RectLayout = {
    x: centerX - backSize.width / 2,
    y,
    width: backSize.width,
    height: backSize.height,
  };
  y += backSize.height + BASE_BOTTOM_MARGIN * scale;

  const contentHeight = y - top0 + BASE_BOTTOM_INSET * scale;
  const maxScroll = Math.max(0, contentHeight - viewportHeight);

  return {
    scale,
    contentRect,
    viewportTop,
    viewportHeight,
    cardWidth,
    sections,
    backButton,
    contentHeight,
    maxScroll,
  };
}

// Re-exported so RulesScene.ts can build its fixed title TextLayout
// (positioned above viewportTop, outside the scrollable flow above)
// from the same scale the rest of this module already computed,
// without RulesScene.ts needing its own separate call into scale.ts
// just for that one text element.
export function computeRulesTitleLayout(rawViewport: Viewport, insets: SafeAreaInsets): TextLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  return {
    x: contentRect.x + contentRect.width / 2,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
}
