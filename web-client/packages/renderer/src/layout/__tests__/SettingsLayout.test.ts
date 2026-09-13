import { describe, expect, it } from 'vitest';
import {
  CREDITS_LINES,
  DEFAULT_SETTINGS,
  NUMBER_FIELD_RANGES,
  TOGGLE_FIELD_LABELS,
  computeSettingsFlow,
  computeSettingsTitleLayout,
  type NoteRowLayout,
  type NumberBoxRowLayout,
  type SettingsCardLayout,
  type SettingsRowLayout,
  type SliderRowLayout,
  type ToggleRowLayout,
} from '../SettingsLayout.js';
import { MIN_TOUCH_TARGET_PX } from '../scale.js';

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

const NARROW_PHONE_PORTRAIT = { width: 360, height: 780 };
const MID_TABLET_PANEL = { width: 1024, height: 768 };
const WIDE_DESKTOP = { width: 2560, height: 1440 };

const EXPECTED_CARD_TITLES = [
  'Timers',
  'Deck & Logging',
  'Rules',
  'Player Assistance',
  'Display',
  'Audio',
  'Credits',
];

function findRows<T extends SettingsRowLayout>(card: SettingsCardLayout, kind: T['kind']): T[] {
  return card.rows.filter((r): r is T => r.kind === kind);
}

describe('DEFAULT_SETTINGS', () => {
  it('mirrors core/settings_store.py DEFAULTS values for every ported field', () => {
    // Spot-check the numeric defaults against the PC source of truth
    // (core/settings_store.py) rather than re-deriving them here.
    expect(DEFAULT_SETTINGS.turnTimerSecs).toBe(150);
    expect(DEFAULT_SETTINGS.postPlayDelaySecs).toBe(60);
    expect(DEFAULT_SETTINGS.counterWindowSecs).toBe(60);
    expect(DEFAULT_SETTINGS.jokerCount).toBe(2);
    expect(DEFAULT_SETTINGS.logLevel).toBe('HIGH');
    expect(DEFAULT_SETTINGS.maxLogPairs).toBe(0);
    expect(DEFAULT_SETTINGS.timersEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.suitChangeAfterShield).toBe(false);
    expect(DEFAULT_SETTINGS.aceSuitIntegrity).toBe(false);
    expect(DEFAULT_SETTINGS.pickupShieldQkAllowed).toBe(true);
    expect(DEFAULT_SETTINGS.aceFinisherEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.jumpMultiCardEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.cardAnimationsEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.hintsEnabled).toBe(false);
    expect(DEFAULT_SETTINGS.hintThresholdPct).toBe(50);
    expect(DEFAULT_SETTINGS.musicEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.sfxEnabled).toBe(true);
    expect(DEFAULT_SETTINGS.musicVolume).toBe(0.5);
    expect(DEFAULT_SETTINGS.sfxVolume).toBe(0.5);
  });

  it('every default value falls inside its own field range, where a range applies', () => {
    for (const [key, range] of Object.entries(NUMBER_FIELD_RANGES)) {
      const value = DEFAULT_SETTINGS[key as keyof typeof DEFAULT_SETTINGS] as number;
      expect(value).toBeGreaterThanOrEqual(range.min);
      expect(value).toBeLessThanOrEqual(range.max);
    }
  });
});

describe('CREDITS_LINES', () => {
  it('has the three expected credits entries, verbatim from asset_loader.py MUSIC_CREDITS', () => {
    expect(CREDITS_LINES).toEqual([
      'Menu Theme: "Jazzy blues" by LushoGames (CC0)',
      'Gameplay Ambient: "Heavenly Loop" by isaiah658 (CC0)',
      'Chuo Drums: "Djembe Loop 08 - 120 BPM" by Ancient.Sounds (CC0)',
    ]);
  });
});

describe('computeSettingsFlow', () => {
  it('produces the 7 titled panel cards in the expected order (Back/Reset are separate, not cards)', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(flow.cards.map((c) => c.title.text)).toEqual(EXPECTED_CARD_TITLES);
  });

  it('stacks cards strictly top-to-bottom with no overlap', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    for (let i = 1; i < flow.cards.length; i++) {
      const prev = flow.cards[i - 1].panelRect;
      const cur = flow.cards[i].panelRect;
      expect(cur.y).toBeGreaterThanOrEqual(prev.y + prev.height);
    }
  });

  it('places the back button below the last card, and the reset button below the back button', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const last = flow.cards[flow.cards.length - 1].panelRect;
    expect(flow.backButton.y).toBeGreaterThanOrEqual(last.y + last.height);
    expect(flow.resetButton.y).toBeGreaterThanOrEqual(flow.backButton.y + flow.backButton.height);
  });

  it('the Timers card has exactly 3 numbox rows, for turnTimerSecs/postPlayDelaySecs/counterWindowSecs in that order', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const timers = flow.cards[0];
    const numboxes = findRows<NumberBoxRowLayout>(timers, 'numbox');
    expect(numboxes.map((n) => n.key)).toEqual(['turnTimerSecs', 'postPlayDelaySecs', 'counterWindowSecs']);
    for (const nb of numboxes) expect(nb.isLogCap).toBe(false);
  });

  it('the Deck & Logging card has one joker row, one logLevel row, and the maxLogPairs numbox flagged isLogCap', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const deckLogging = flow.cards[1];
    expect(findRows(deckLogging, 'joker')).toHaveLength(1);
    expect(findRows(deckLogging, 'logLevel')).toHaveLength(1);
    const numboxes = findRows<NumberBoxRowLayout>(deckLogging, 'numbox');
    expect(numboxes).toHaveLength(1);
    expect(numboxes[0].key).toBe('maxLogPairs');
    expect(numboxes[0].isLogCap).toBe(true);
  });

  it('the Rules card has exactly the 7 gameplay toggles, in the PC order', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const rules = flow.cards[2];
    const toggles = findRows<ToggleRowLayout>(rules, 'toggle');
    expect(toggles.map((t) => t.key)).toEqual([
      'timersEnabled',
      'suitChangeAfterShield',
      'aceSuitIntegrity',
      'pickupShieldQkAllowed',
      'aceFinisherEnabled',
      'jumpMultiCardEnabled',
      'cardAnimationsEnabled',
    ]);
  });

  it('the Player Assistance card has the hint toggle and the hintThresholdPct numbox', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const playerAssist = flow.cards[3];
    const toggles = findRows<ToggleRowLayout>(playerAssist, 'toggle');
    expect(toggles.map((t) => t.key)).toEqual(['hintsEnabled']);
    const numboxes = findRows<NumberBoxRowLayout>(playerAssist, 'numbox');
    expect(numboxes.map((n) => n.key)).toEqual(['hintThresholdPct']);
  });

  it('the Display card has no resolution row of any kind -- the dropdown is deliberately not ported', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const display = flow.cards[4];
    for (const row of display.rows) {
      expect(row.kind).not.toBe('res');
    }
    // Only a note row explaining the auto-fit behavior should remain.
    expect(display.rows.every((r) => r.kind === 'note')).toBe(true);
  });

  it('the Audio card has music+sfx toggles and exactly 2 sliders, for musicVolume then sfxVolume', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const audio = flow.cards[5];
    const toggles = findRows<ToggleRowLayout>(audio, 'toggle');
    expect(toggles.map((t) => t.key)).toEqual(['musicEnabled', 'sfxEnabled']);
    const sliders = findRows<SliderRowLayout>(audio, 'slider');
    expect(sliders.map((s) => s.key)).toEqual(['musicVolume', 'sfxVolume']);
  });

  it('the Credits card has exactly one note row per CREDITS_LINES entry', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const credits = flow.cards[6];
    const notes = findRows<NoteRowLayout>(credits, 'note');
    expect(notes).toHaveLength(CREDITS_LINES.length);
    // Each credits line fits on one wrapped line at this viewport width.
    expect(notes.map((n) => n.lines.map((l) => l.text).join(' '))).toEqual(CREDITS_LINES);
  });

  it('every toggle row label matches TOGGLE_FIELD_LABELS for its key', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    for (const card of flow.cards) {
      for (const toggle of findRows<ToggleRowLayout>(card, 'toggle')) {
        expect(toggle.label.value).toBe(`${TOGGLE_FIELD_LABELS[toggle.key]}:`);
      }
    }
  });

  it('every numbox row has its box positioned to the right of its minus/plus steppers', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    for (const card of flow.cards) {
      for (const nb of findRows<NumberBoxRowLayout>(card, 'numbox')) {
        expect(nb.minus.x + nb.minus.width).toBeLessThanOrEqual(nb.box.x);
        expect(nb.plus.x).toBeGreaterThanOrEqual(nb.box.x + nb.box.width);
      }
    }
  });

  it('shifts every card/back/reset y position by exactly the scroll delta, leaving contentHeight/maxScroll unchanged', () => {
    const flowA = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const flowB = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 120);

    expect(flowB.contentHeight).toBeCloseTo(flowA.contentHeight, 5);
    expect(flowB.maxScroll).toBeCloseTo(flowA.maxScroll, 5);

    for (let i = 0; i < flowA.cards.length; i++) {
      expect(flowB.cards[i].panelRect.y).toBeCloseTo(flowA.cards[i].panelRect.y - 120, 5);
    }
    expect(flowB.backButton.y).toBeCloseTo(flowA.backButton.y - 120, 5);
    expect(flowB.resetButton.y).toBeCloseTo(flowA.resetButton.y - 120, 5);
  });

  it('scrollOffset never changes row composition (same keys/kinds per card regardless of scroll)', () => {
    const flowA = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const flowB = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 500);
    for (let i = 0; i < flowA.cards.length; i++) {
      expect(flowB.cards[i].rows.map((r) => r.kind)).toEqual(flowA.cards[i].rows.map((r) => r.kind));
    }
  });

  it('maxScroll is 0 when all content already fits inside a very tall viewport', () => {
    const flow = computeSettingsFlow({ width: 1024, height: 20000 }, ZERO_INSETS, 0);
    expect(flow.maxScroll).toBe(0);
  });

  it('maxScroll is positive when content overflows a short viewport', () => {
    const flow = computeSettingsFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    expect(flow.maxScroll).toBeGreaterThan(0);
  });

  it('maxScroll equals contentHeight - viewportHeight whenever content overflows', () => {
    const flow = computeSettingsFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    if (flow.contentHeight > flow.viewportHeight) {
      expect(flow.maxScroll).toBeCloseTo(flow.contentHeight - flow.viewportHeight, 5);
    }
  });

  it('grows font sizes and card width when the viewport grows', () => {
    const phone = computeSettingsFlow(NARROW_PHONE_PORTRAIT, ZERO_INSETS, 0);
    const tablet = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(tablet.scale).toBeGreaterThan(phone.scale);
    expect(tablet.cards[0].title.fontPx).toBeGreaterThan(phone.cards[0].title.fontPx);
    expect(tablet.cardWidth).toBeGreaterThan(phone.cardWidth);
  });

  it('caps card width well short of the full viewport on a very wide desktop', () => {
    const flow = computeSettingsFlow(WIDE_DESKTOP, ZERO_INSETS, 0);
    expect(flow.cardWidth).toBeLessThan(flow.contentRect.width * 0.8);
  });

  it('keeps every card centered horizontally at every viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const flow = computeSettingsFlow(viewport, ZERO_INSETS, 0);
      const contentCenter = flow.contentRect.x + flow.contentRect.width / 2;
      for (const card of flow.cards) {
        const cardCenter = card.panelRect.x + card.panelRect.width / 2;
        expect(cardCenter).toBeCloseTo(contentCenter, 1);
      }
    }
  });

  it('the back and reset buttons meet the minimum touch-target size at every viewport', () => {
    for (const viewport of [NARROW_PHONE_PORTRAIT, MID_TABLET_PANEL, WIDE_DESKTOP]) {
      const flow = computeSettingsFlow(viewport, ZERO_INSETS, 0);
      expect(flow.backButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(flow.backButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(flow.resetButton.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
      expect(flow.resetButton.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    }
  });

  it('respects safe-area insets by shifting contentRect and viewportTop inward', () => {
    const insets = { top: 40, right: 10, bottom: 20, left: 10 };
    const withInsets = computeSettingsFlow(MID_TABLET_PANEL, insets, 0);
    const without = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    expect(withInsets.contentRect.y).toBe(40);
    expect(withInsets.viewportTop).toBeGreaterThan(without.viewportTop);
  });

  it('viewportTop sits below the fixed title (computeSettingsTitleLayout)', () => {
    const flow = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 0);
    const title = computeSettingsTitleLayout(MID_TABLET_PANEL, ZERO_INSETS);
    expect(flow.viewportTop).toBeGreaterThan(title.y + title.fontPx);
  });

  it('every row position is independent of the current SettingsValues (geometry never varies with live values)', () => {
    // computeSettingsFlow deliberately takes no SettingsValues argument
    // at all (see this module's header) -- this test exists to catch
    // a future regression where someone adds value-dependent sizing
    // without also widening the function signature; as written today,
    // two calls with identical viewport/insets/scrollOffset must be
    // byte-for-byte identical.
    const flowA = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 42);
    const flowB = computeSettingsFlow(MID_TABLET_PANEL, ZERO_INSETS, 42);
    expect(flowB).toEqual(flowA);
  });
});
