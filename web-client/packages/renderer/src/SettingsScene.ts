/**
 * KADI web-client — SettingsScene.
 *
 * Reached from MainMenuScene's "Settings" button (now enabled -- see
 * MainMenuLayout.ts). All 8 cards from scenes.SettingsScene (scenes.py,
 * line 2435) are ported here -- see layout/SettingsLayout.ts's own
 * header for the exact card list, what's deliberately NOT ported
 * (the resolution dropdown -- obsolete per §6a), and why this scene
 * needed no SettingsValues-dependent geometry (every row's position
 * is fixed; only its drawn CONTENT depends on the live value, which
 * lives entirely in this file, not in the layout module).
 *
 * SCROLLING: identical pattern to RulesScene.ts -- wheel + touch-drag,
 * both feeding layout/scrollPhysics.ts's shared bounded-overshoot/
 * eased-settle physics, clipped to the viewport band with a Container
 * + Graphics geometry mask. See that file's header for why touch-drag
 * is a genuine (non-PC) addition.
 *
 * PERSISTENCE (Part C): loaded once in create() via
 * `adapter.getSettings()`, merged over DEFAULT_SETTINGS (so a fresh
 * install, or a settings blob predating a newly-added field, both
 * fall back safely per-field rather than needing an all-or-nothing
 * migration). Saved via `adapter.saveSettings()` -- on every commit
 * (numbox commit, toggle/button click, slider release), on a 2-second
 * autosave tick while sitting on this screen (mirrors
 * SettingsScene.update()'s own `_autosave_timer`), and once more on
 * scene shutdown (mirrors `on_exit()`'s own always-save-on-the-way-out,
 * including committing any still-focused numbox first).
 *
 * INTERACTION MODEL -- the first genuinely interactive (not just
 * read-and-scroll) scene in this codebase, so a few things are new
 * here rather than carried over from RulesScene.ts:
 *   - Every row's GameObjects are destroyed and rebuilt on every
 *     render() call, same throwaway-and-recreate discipline
 *     RulesScene.ts already uses for its (non-interactive) panels --
 *     simpler than diffing/patching individual widgets, and cheap
 *     enough at this scene's object count (a few dozen small
 *     rectangles/text objects) to redo on every value change, scroll
 *     tick, or resize.
 *   - NumberBox click-to-focus + digit keyboard entry (mirrors
 *     scenes.py's NumberBox.handle_event) is implemented directly
 *     against Phaser's keyboard input while a `focusedNumberField` is
 *     set, since there is no real DOM <input> anywhere in this
 *     canvas-only renderer (§6).
 *   - The +/- steppers support hold-to-repeat with the same
 *     accelerating-interval curve as NumberBox.update() (start at
 *     0.45s between repeats, multiply by 0.8 down to a 0.035s floor).
 */
import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  DEFAULT_SETTINGS,
  NUMBER_FIELD_LABELS,
  NUMBER_FIELD_RANGES,
  TOGGLE_FIELD_LABELS,
  computeSettingsFlow,
  computeSettingsTitleLayout,
  type JokerCount,
  type LogLevel,
  type NumberBoxRowLayout,
  type NumberFieldKey,
  type SettingsFlow,
  type SettingsValues,
  type SliderFieldKey,
  type ToggleFieldKey,
  type ToggleRowLayout,
} from './layout/SettingsLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';

/** Per-numbox interaction state -- the direct analogue of NumberBox's
 * own mutable fields (scenes.py) that don't belong in the pure layout
 * module (see SettingsLayout.ts's header on why). */
interface NumberBoxState {
  focused: boolean;
  text: string;
  holdDir: number;
  holdElapsed: number;
  holdInterval: number;
}

const HOLD_INITIAL_DELAY_MS = 450;
const HOLD_MIN_INTERVAL_MS = 35;
const HOLD_ACCELERATION = 0.8;
const AUTOSAVE_INTERVAL_MS = 2000;
const RESET_CONFIRM_DURATION_MS = 2000;

function clampNumberField(key: NumberFieldKey, value: number): number {
  const { min, max } = NUMBER_FIELD_RANGES[key];
  return Math.max(min, Math.min(max, value));
}

export class SettingsScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;

  private titleText!: Phaser.GameObjects.Text;
  private content!: Phaser.GameObjects.Container;
  private clipMask!: Phaser.GameObjects.Graphics;
  private dynamicObjects: Phaser.GameObjects.GameObject[] = [];
  private backRect!: Phaser.GameObjects.Rectangle;
  private backLabel!: Phaser.GameObjects.Text;
  private resetRect!: Phaser.GameObjects.Rectangle;
  private resetLabel!: Phaser.GameObjects.Text;
  private resetConfirmText!: Phaser.GameObjects.Text;

  private values: SettingsValues = { ...DEFAULT_SETTINGS };
  private numberBoxState: Record<NumberFieldKey, NumberBoxState> = this.freshNumberBoxState();
  private focusedNumberField: NumberFieldKey | null = null;
  private draggingSlider: SliderFieldKey | null = null;

  private scrollOffset = 0;
  private scrollBounce: ScrollBounce | null = null;
  private currentFlow!: SettingsFlow;

  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  private autosaveElapsedMs = 0;
  private resetConfirmElapsedMs = 0;

  constructor() {
    super('SettingsScene');
  }

  private freshNumberBoxState(): Record<NumberFieldKey, NumberBoxState> {
    const keys: NumberFieldKey[] = [
      'turnTimerSecs',
      'postPlayDelaySecs',
      'counterWindowSecs',
      'hintThresholdPct',
      'maxLogPairs',
    ];
    const state = {} as Record<NumberFieldKey, NumberBoxState>;
    for (const key of keys) {
      state[key] = { focused: false, text: '', holdDir: 0, holdElapsed: 0, holdInterval: 0 };
    }
    return state;
  }

  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
    // Fresh scroll/interaction state on every entry -- same reasoning
    // as RulesScene.ts's own init() reset (this Scene instance is
    // reused across repeated scene.start() calls).
    this.scrollOffset = 0;
    this.scrollBounce = null;
    this.dragging = false;
    this.dragPointerId = null;
    this.focusedNumberField = null;
    this.draggingSlider = null;
    this.numberBoxState = this.freshNumberBoxState();
    this.autosaveElapsedMs = 0;
    this.resetConfirmElapsedMs = 0;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    // Load persisted settings (Part C) -- merge over DEFAULT_SETTINGS
    // field-by-field so a partial/older blob never leaves a field
    // `undefined` (see PlatformAdapter.ts's own docstring on why
    // getSettings() returns a loose bag rather than a typed one).
    this.values = { ...DEFAULT_SETTINGS };
    void this.adapter.getSettings().then((stored) => {
      if (stored) {
        this.values = { ...DEFAULT_SETTINGS, ...(stored as Partial<SettingsValues>) };
      }
      this.render();
    });

    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeSettingsTitleLayout(this.viewport(), insets);

    this.titleText = this.add
      .text(titleLayout.x, titleLayout.y, 'Settings', {
        fontFamily: 'sans-serif',
        fontSize: `${titleLayout.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5, 0);

    this.content = this.add.container(0, 0);
    this.clipMask = this.make.graphics(undefined, false);
    this.content.setMask(this.clipMask.createGeometryMask());

    this.render();

    this.input.on(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
    this.input.on(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.input.on(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.on(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.input.keyboard?.on(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.handleShutdown, this);
  }

  private handleShutdown(): void {
    this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.input.off(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
    this.input.off(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.input.off(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.off(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.input.keyboard?.off(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);
    // Mirrors on_exit(): commit any still-focused numbox, then save --
    // a player who navigates away mid-edit shouldn't lose that edit.
    if (this.focusedNumberField) this.commitNumberField(this.focusedNumberField);
    void this.adapter.saveSettings({ ...this.values });
  }

  update(_time: number, delta: number): void {
    let needsRender = false;

    const outOfRange = this.scrollOffset < 0 || this.scrollOffset > this.currentFlow.maxScroll;
    if (this.scrollBounce || outOfRange) {
      const result = settleScroll(this.scrollOffset, this.scrollBounce, delta, this.currentFlow.maxScroll);
      this.scrollOffset = result.value;
      this.scrollBounce = result.bounce;
      needsRender = true;
    }

    for (const key of Object.keys(this.numberBoxState) as NumberFieldKey[]) {
      const state = this.numberBoxState[key];
      if (state.holdDir === 0) continue;
      state.holdElapsed += delta;
      if (state.holdElapsed >= state.holdInterval) {
        state.holdElapsed = 0;
        state.holdInterval = Math.max(HOLD_MIN_INTERVAL_MS, state.holdInterval * HOLD_ACCELERATION);
        this.nudgeNumberField(key, state.holdDir * this.stepFor(key));
        needsRender = true;
      }
    }

    if (this.resetConfirmElapsedMs > 0) {
      this.resetConfirmElapsedMs = Math.max(0, this.resetConfirmElapsedMs - delta);
      if (this.resetConfirmText) this.resetConfirmText.setVisible(this.resetConfirmElapsedMs > 0);
    }

    this.autosaveElapsedMs += delta;
    if (this.autosaveElapsedMs >= AUTOSAVE_INTERVAL_MS) {
      this.autosaveElapsedMs = 0;
      void this.adapter.saveSettings({ ...this.values });
    }

    if (needsRender) this.render();
  }

  private viewport(): { width: number; height: number } {
    return { width: this.scale.width, height: this.scale.height };
  }

  private stepFor(key: NumberFieldKey): number {
    return NUMBER_FIELD_RANGES[key].step;
  }

  // ── Scroll input (identical pattern to RulesScene.ts) ────────────

  private handleWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (this.dragging || this.draggingSlider || this.currentFlow == null) return;
    pointer.event?.preventDefault();
    this.scrollBounce = null;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, dy, this.currentFlow.maxScroll);
    this.render();
  }

  private isWithinViewportBand(pointer: Phaser.Input.Pointer): boolean {
    const flow = this.currentFlow;
    return pointer.y >= flow.viewportTop && pointer.y <= flow.viewportTop + flow.viewportHeight;
  }

  private handleDragStart(pointer: Phaser.Input.Pointer): void {
    // A slider/numbox/button under the pointer handles its own
    // pointerdown via its own listener (see buildRow* methods) and
    // stops event propagation there isn't a concept of in Phaser's
    // flat listener list -- instead, those handlers set
    // draggingSlider/consume the interaction directly, and this
    // scroll-drag-start only arms itself when nothing else claimed
    // the pointer this same tick (checked via draggingSlider/
    // focusedNumberField timing: interactive objects are on top and
    // fire first since they're added to `content` after being
    // created in top-to-bottom row order, matching Phaser's
    // top-of-display-list-first hit-testing).
    if (this.draggingSlider) return;
    if (this.dragPointerId !== null) return;
    if (!this.isWithinViewportBand(pointer)) return;
    this.dragging = true;
    this.dragPointerId = pointer.id;
    this.dragLastY = pointer.y;
    this.scrollBounce = null;
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    if (this.draggingSlider) {
      this.updateSliderFromPointer(this.draggingSlider, pointer.x);
      return;
    }
    if (!this.dragging || pointer.id !== this.dragPointerId) return;
    const delta = this.dragLastY - pointer.y;
    this.dragLastY = pointer.y;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, delta, this.currentFlow.maxScroll);
    this.render();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (this.draggingSlider) {
      this.draggingSlider = null;
      void this.adapter.saveSettings({ ...this.values });
      return;
    }
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
  }

  // ── Number field editing (click-to-focus + keyboard digits) ─────

  private commitNumberField(key: NumberFieldKey): void {
    const state = this.numberBoxState[key];
    const parsed = state.text.trim() === '' ? NUMBER_FIELD_RANGES[key].min : parseInt(state.text, 10);
    const value = Number.isFinite(parsed) ? clampNumberField(key, parsed) : this.values[key];
    this.values = { ...this.values, [key]: value };
    state.focused = false;
    state.text = String(value);
    if (this.focusedNumberField === key) this.focusedNumberField = null;
    void this.adapter.saveSettings({ ...this.values });
  }

  private focusNumberField(key: NumberFieldKey): void {
    if (this.focusedNumberField && this.focusedNumberField !== key) {
      this.commitNumberField(this.focusedNumberField);
    }
    this.focusedNumberField = key;
    const state = this.numberBoxState[key];
    state.focused = true;
    state.text = String(this.values[key]);
    this.render();
  }

  private nudgeNumberField(key: NumberFieldKey, delta: number): void {
    const state = this.numberBoxState[key];
    if (state.focused) this.commitNumberField(key);
    const value = clampNumberField(key, this.values[key] + delta);
    this.values = { ...this.values, [key]: value };
    state.text = String(value);
    void this.adapter.saveSettings({ ...this.values });
  }

  private handleKeyDown(event: KeyboardEvent): void {
    const key = this.focusedNumberField;
    if (!key) return;
    const state = this.numberBoxState[key];
    if (event.key === 'Enter' || event.key === 'Escape' || event.key === 'Tab') {
      this.commitNumberField(key);
      this.render();
      return;
    }
    if (event.key === 'Backspace') {
      state.text = state.text.slice(0, -1);
      this.render();
      return;
    }
    if (/^[0-9]$/.test(event.key) && state.text.length < 3) {
      state.text += event.key;
      this.render();
    }
  }

  // ── Slider dragging ───────────────────────────────────────────────

  private updateSliderFromPointer(key: SliderFieldKey, pointerX: number): void {
    const row = this.findSliderRow(key);
    if (!row) return;
    const t = Math.max(0, Math.min(1, (pointerX - row.track.x) / row.track.width));
    const value = Math.round((t / 0.05)) * 0.05;
    const clamped = Math.max(0, Math.min(1, value));
    this.values = { ...this.values, [key]: clamped };
    this.render();
  }

  private findSliderRow(key: SliderFieldKey): { track: RectLayout } | null {
    for (const card of this.currentFlow.cards) {
      for (const row of card.rows) {
        if (row.kind === 'slider' && row.key === key) return row;
      }
    }
    return null;
  }

  // ── Reset to Defaults ─────────────────────────────────────────────

  private onResetDefaults(): void {
    this.values = { ...DEFAULT_SETTINGS };
    this.numberBoxState = this.freshNumberBoxState();
    this.focusedNumberField = null;
    this.resetConfirmElapsedMs = RESET_CONFIRM_DURATION_MS;
    void this.adapter.saveSettings({ ...this.values });
    this.render();
  }

  // ── Resize ─────────────────────────────────────────────────────────

  private handleResize(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeSettingsTitleLayout(this.viewport(), insets);
    this.titleText.setPosition(titleLayout.x, titleLayout.y);
    this.titleText.setFontSize(titleLayout.fontPx);
    this.render();
  }

  private isOffscreen(rect: RectLayout, flow: SettingsFlow): boolean {
    return rect.y + rect.height < flow.viewportTop || rect.y > flow.viewportTop + flow.viewportHeight;
  }

  // ── Render ─────────────────────────────────────────────────────────

  private render(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const flow = computeSettingsFlow(this.viewport(), insets, this.scrollOffset);
    this.currentFlow = flow;

    this.clipMask.clear();
    this.clipMask.fillStyle(0xffffff);
    this.clipMask.fillRect(flow.contentRect.x, flow.viewportTop, flow.contentRect.width, flow.viewportHeight);

    for (const obj of this.dynamicObjects) obj.destroy();
    this.dynamicObjects = [];

    const theme = this.adapter.getTheme();

    for (const card of flow.cards) {
      if (this.isOffscreen(card.panelRect, flow)) continue;

      const panel = this.add
        .rectangle(
          card.panelRect.x + card.panelRect.width / 2,
          card.panelRect.y + card.panelRect.height / 2,
          card.panelRect.width,
          card.panelRect.height,
          0x1e1e1e,
          0.9,
        )
        .setStrokeStyle(1, 0xffffff, 0.15);
      const title = this.add.text(card.title.x, card.title.y, card.title.text, {
        fontFamily: 'sans-serif',
        fontSize: `${card.title.fontPx}px`,
        color: theme.accent,
        fontStyle: 'bold',
      });
      this.content.add([panel, title]);
      this.dynamicObjects.push(panel, title);

      for (const row of card.rows) {
        this.renderRow(row, theme);
      }
    }

    this.renderBackAndReset(flow, theme);
  }

  private track<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.content.add(obj);
    this.dynamicObjects.push(obj);
    return obj;
  }

  private renderRow(row: SettingsFlow['cards'][number]['rows'][number], theme: ReturnType<PlatformAdapter['getTheme']>): void {
    switch (row.kind) {
      case 'numbox':
        this.renderNumberBox(row);
        break;
      case 'label':
        this.track(
          this.add
            .text(row.text.x, row.text.y, row.text.value, {
              fontFamily: 'sans-serif',
              fontSize: `${row.text.fontPx}px`,
              color: theme.text,
            })
            .setOrigin(0.5, 0),
        );
        break;
      case 'note':
        for (const line of row.lines) {
          this.track(
            this.add
              .text(line.x, line.y, line.text, {
                fontFamily: 'sans-serif',
                fontSize: `${line.fontPx}px`,
                color: '#a0a89e',
              })
              .setOrigin(0.5, 0),
          );
        }
        break;
      case 'joker':
        this.renderChoiceButton(row.two, '2', this.values.jokerCount === 2, () => this.setJokerCount(2));
        this.renderChoiceButton(row.four, '4', this.values.jokerCount === 4, () => this.setJokerCount(4));
        break;
      case 'logLevel':
        this.renderChoiceButton(row.off, 'OFF', this.values.logLevel === 'OFF', () => this.setLogLevel('OFF'));
        this.renderChoiceButton(row.low, 'LOW', this.values.logLevel === 'LOW', () => this.setLogLevel('LOW'));
        this.renderChoiceButton(row.high, 'HIGH', this.values.logLevel === 'HIGH', () => this.setLogLevel('HIGH'));
        break;
      case 'toggle':
        this.renderToggle(row);
        break;
      case 'slider':
        this.renderSlider(row.key, row.label, row.track);
        break;
    }
  }

  private renderNumberBox(row: NumberBoxRowLayout): void {
    const state = this.numberBoxState[row.key];
    const range = NUMBER_FIELD_RANGES[row.key];
    const value = this.values[row.key];

    this.track(
      this.add
        .text(row.label.x, row.label.y, NUMBER_FIELD_LABELS[row.key], {
          fontFamily: 'sans-serif',
          fontSize: `${row.label.fontPx}px`,
          color: '#dce0d8',
        }),
    );
    const maxText = row.isLogCap ? '(0 = unlimited)' : `(max ${range.max}${row.key === 'hintThresholdPct' ? '%' : 's'})`;
    this.track(
      this.add.text(row.maxLabel.x, row.maxLabel.y, maxText, {
        fontFamily: 'sans-serif',
        fontSize: `${row.maxLabel.fontPx}px`,
        color: '#96a094',
      }),
    );

    const focusedColor = state.focused ? 0xf0d878 : 0x82a087;
    const box = this.track(
      this.add
        .rectangle(
          row.box.x + row.box.width / 2,
          row.box.y + row.box.height / 2,
          row.box.width,
          row.box.height,
          0x182e20,
        )
        .setStrokeStyle(2, focusedColor)
        .setInteractive({ useHandCursor: true }),
    );
    box.on('pointerdown', () => this.focusNumberField(row.key));

    let displayText: string;
    if (state.focused) {
      displayText = state.text || '0';
    } else if (value > 0 || row.key === 'hintThresholdPct') {
      displayText = `${value}${row.key === 'hintThresholdPct' ? '%' : 's'}`;
    } else {
      displayText = row.isLogCap ? 'Unlimited' : 'Off';
    }
    this.track(
      this.add
        .text(row.box.x + row.box.width / 2, row.box.y + row.box.height / 2, displayText, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(row.box.height * 0.45)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );

    this.renderStepper(row.minus, '-', () => this.startHold(row.key, -1));
    this.renderStepper(row.plus, '+', () => this.startHold(row.key, 1));
  }

  private startHold(key: NumberFieldKey, direction: number): void {
    this.nudgeNumberField(key, direction * this.stepFor(key));
    const state = this.numberBoxState[key];
    state.holdDir = direction;
    state.holdElapsed = 0;
    state.holdInterval = HOLD_INITIAL_DELAY_MS;
    // Stop the hold on release anywhere -- one-shot listeners tied to
    // this specific press, mirroring NumberBox.update()'s own
    // direction-drops-to-0-when-not-held behavior.
    const stop = () => {
      if (this.numberBoxState[key].holdDir === direction) this.numberBoxState[key].holdDir = 0;
    };
    this.input.once(Phaser.Input.Events.POINTER_UP, stop);
    this.input.once(Phaser.Input.Events.POINTER_UP_OUTSIDE, stop);
    this.render();
  }

  private renderStepper(rect: RectLayout, symbol: string, onClick: () => void): void {
    const btn = this.track(
      this.add
        .rectangle(rect.x + rect.width / 2, rect.y + rect.height / 2, rect.width, rect.height, 0x284630)
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', onClick);
    this.track(
      this.add
        .text(rect.x + rect.width / 2, rect.y + rect.height / 2, symbol, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(rect.height * 0.5)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderChoiceButton(rect: RectLayout, label: string, selected: boolean, onClick: () => void): void {
    const btn = this.track(
      this.add
        .rectangle(
          rect.x + rect.width / 2,
          rect.y + rect.height / 2,
          rect.width,
          rect.height,
          selected ? 0xd9a441 : 0x325a3c,
        )
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', onClick);
    this.track(
      this.add
        .text(rect.x + rect.width / 2, rect.y + rect.height / 2, label, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(rect.height * 0.42)}px`,
          color: selected ? '#1a1a1a' : '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderToggle(row: ToggleRowLayout): void {
    this.track(
      this.add.text(row.label.x, row.label.y, row.label.value, {
        fontFamily: 'sans-serif',
        fontSize: `${row.label.fontPx}px`,
        color: '#ffffff',
      }).setOrigin(0.5, 0),
    );
    const state = this.values[row.key];
    const btn = this.track(
      this.add
        .rectangle(
          row.button.x + row.button.width / 2,
          row.button.y + row.button.height / 2,
          row.button.width,
          row.button.height,
          state ? 0x288c32 : 0x642828,
        )
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', () => this.toggleField(row.key));
    this.track(
      this.add
        .text(row.button.x + row.button.width / 2, row.button.y + row.button.height / 2, state ? 'ON' : 'OFF', {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(row.button.height * 0.4)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderSlider(key: SliderFieldKey, label: string, track: RectLayout): void {
    const value = this.values[key];
    const t = value; // sliders here are always [0, 1]
    const fillWidth = track.width * t;

    this.track(
      this.add
        .rectangle(track.x + track.width / 2, track.y + track.height / 2, track.width, track.height, 0x32503a)
        .setStrokeStyle(1, 0xffffff, 0.3),
    );
    if (fillWidth > 0) {
      this.track(
        this.add.rectangle(
          track.x + fillWidth / 2,
          track.y + track.height / 2,
          fillWidth,
          track.height,
          0xd9a441,
        ),
      );
    }
    const knobX = track.x + fillWidth;
    const knob = this.track(
      this.add
        .circle(knobX, track.y + track.height / 2, track.height * 0.65, 0xffffff)
        .setInteractive({ useHandCursor: true, hitArea: new Phaser.Geom.Circle(0, 0, track.height * 1.5), hitAreaCallback: Phaser.Geom.Circle.Contains }),
    );
    knob.on('pointerdown', () => {
      this.draggingSlider = key;
    });
    // The track itself is also a grab target (inflated hit area,
    // mirroring Slider.handle_event's own `rect.inflate(0, 24)`), not
    // just the knob -- lets a player click anywhere on the bar to jump
    // there, same as the PC original.
    const grabZone = this.track(
      this.add
        .zone(track.x + track.width / 2, track.y + track.height / 2, track.width, track.height + 24)
        .setInteractive({ useHandCursor: true }),
    );
    grabZone.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      this.draggingSlider = key;
      this.updateSliderFromPointer(key, pointer.x);
    });

    this.track(
      this.add.text(track.x, track.y - Math.round(track.height * 1.6), `${label}: ${Math.round(value * 100)}%`, {
        fontFamily: 'sans-serif',
        fontSize: `${Math.round(track.height * 1.1)}px`,
        color: '#ffffff',
      }),
    );
  }

  private renderBackAndReset(flow: SettingsFlow, theme: ReturnType<PlatformAdapter['getTheme']>): void {
    const backCx = flow.backButton.x + flow.backButton.width / 2;
    const backCy = flow.backButton.y + flow.backButton.height / 2;
    const backOffscreen = this.isOffscreen(flow.backButton, flow);

    this.backRect = this.add
      .rectangle(backCx, backCy, flow.backButton.width, flow.backButton.height, 0x3c2864)
      .setStrokeStyle(1, 0xffffff, 0.6);
    this.backLabel = this.add
      .text(backCx, backCy, 'Back', { fontFamily: 'sans-serif', fontSize: '16px', color: theme.text })
      .setOrigin(0.5);
    if (!backOffscreen) {
      this.backRect.setInteractive({ useHandCursor: true });
      this.backRect.on('pointerdown', () => {
        void this.adapter.saveSettings({ ...this.values });
        this.scene.start('MainMenuScene', { adapter: this.adapter });
      });
    }
    this.content.add([this.backRect, this.backLabel]);
    this.dynamicObjects.push(this.backRect, this.backLabel);

    const resetCx = flow.resetButton.x + flow.resetButton.width / 2;
    const resetCy = flow.resetButton.y + flow.resetButton.height / 2;
    const resetOffscreen = this.isOffscreen(flow.resetButton, flow);

    this.resetRect = this.add
      .rectangle(resetCx, resetCy, flow.resetButton.width, flow.resetButton.height, 0x782828)
      .setStrokeStyle(1, 0xffffff, 0.6);
    this.resetLabel = this.add
      .text(resetCx, resetCy, 'Reset to Defaults', { fontFamily: 'sans-serif', fontSize: '14px', color: theme.text })
      .setOrigin(0.5);
    if (!resetOffscreen) {
      this.resetRect.setInteractive({ useHandCursor: true });
      this.resetRect.on('pointerdown', () => this.onResetDefaults());
    }
    this.resetConfirmText = this.add
      .text(resetCx, resetCy + flow.resetButton.height / 2 + 6, 'Settings reset to defaults and saved', {
        fontFamily: 'sans-serif',
        fontSize: '12px',
        color: '#8cdc96',
      })
      .setOrigin(0.5, 0)
      .setVisible(this.resetConfirmElapsedMs > 0);
    this.content.add([this.resetRect, this.resetLabel, this.resetConfirmText]);
    this.dynamicObjects.push(this.resetRect, this.resetLabel, this.resetConfirmText);
  }

  // ── Value setters (each saves immediately -- these are discrete
  // choices, not a continuous drag like the sliders, so there is no
  // "commit on release" step to wait for). ──

  private setJokerCount(count: JokerCount): void {
    this.values = { ...this.values, jokerCount: count };
    void this.adapter.saveSettings({ ...this.values });
    this.render();
  }

  private setLogLevel(level: LogLevel): void {
    this.values = { ...this.values, logLevel: level };
    void this.adapter.saveSettings({ ...this.values });
    this.render();
  }

  private toggleField(key: ToggleFieldKey): void {
    this.values = { ...this.values, [key]: !this.values[key] };
    void this.adapter.saveSettings({ ...this.values });
    this.render();
  }
}
