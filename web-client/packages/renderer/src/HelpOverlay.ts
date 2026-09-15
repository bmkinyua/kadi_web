/**
 * KADI web-client — the shared Help Overlay: a "?" button plus a
 * scrollable modal popup, with a "stuck?" idle-glow nudge on the
 * button itself.
 *
 * Ported from rendering/widgets.py's `HelpOverlay` class + its own
 * PC-side five call sites (Main Menu, GameConfigScene, ChuoScene,
 * MultiplayerMenuScene, GameTableScene's equivalent). This one class
 * IS the widget for all five screens -- each host scene just
 * constructs one with its own HELP_CONTENT.ts content and wires the
 * handful of lifecycle calls documented on each method below, the
 * same way scenes.py's own five call sites all construct a
 * HelpOverlay + make_help_button() identically and differ only in
 * which HELP_SECTIONS/title they pass in.
 *
 * See layout/HelpOverlayLayout.ts for the pure position/wrap math
 * this class turns into GameObjects (that file's own header covers
 * the two deliberate departures from the PC original: literal
 * unscaled panel/close-button geometry, and a fresh top-right anchor
 * for the "?" button in place of the PC's per-screen AudioControls-
 * relative placement, which this web client has no equivalent of).
 * See idleGlow.ts for the pure idle-glow timer state machine this
 * class owns one instance of.
 *
 * SCROLL INPUT -- same genuine web-side addition as RulesScene.ts's
 * own header describes for its content: the PC original is mouse-
 * wheel-only; this class adds touch-drag scrolling within the panel's
 * viewport band on top of that, reusing the exact same shared physics
 * (layout/scrollPhysics.ts) RulesScene/SettingsScene/ChuoScene already
 * share, so the feel is consistent everywhere content scrolls in this
 * client.
 *
 * MODAL INPUT: while open, a full-screen dim rectangle sits above
 * everything else added so far and closes on an outside click (same
 * modal convention this codebase already uses for GameConfigScene's
 * own MSOMI picker -- see that scene's `dim` rectangle). Phaser's
 * default topOnly input mode keeps a dim rect like this from also
 * triggering whatever object happens to be underneath it for a
 * pointerdown -- but that guarantee does NOT extend to a host scene's
 * own *global* `this.input.on(POINTER_WHEEL / POINTER_DOWN, ...)`
 * listeners (RulesScene/GameConfigScene/GameTableScene/ChuoScene all
 * have one for their own scrolling or drag-to-reorder), which fire
 * regardless of what's on top. Exactly like GameConfigScene's own
 * pre-existing `msomiPickerOpen` guard on its handlers, each of this
 * overlay's five host scenes is expected to check `helpOverlay.isOpen`
 * at the top of any such global handler and bail out while true --
 * see this file's own header on HELP_CONTENT.ts / the five Scene
 * files for where that guard was added.
 */
import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeHelpButtonRect,
  computeHelpOverlayFlow,
  HELP_SCROLL_STEP,
  type HelpContent,
  type HelpOverlayFlow,
} from './layout/HelpOverlayLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { getSafeContentRect } from './layout/safeArea.js';
import type { Viewport } from './layout/scale.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';
import { IdleGlowTimer } from './idleGlow.js';

const GOLD_LIGHT = 0xd4af37;
const PANEL_COLOR = 0x181e2a;
const DIM_ALPHA = 0.65; // ~165/255, matching HelpOverlay.draw()'s dim.fill((0,0,0,165))
const BUTTON_IDLE_COLOR = 0x323c32; // (50,70,50)
const BUTTON_HOVER_COLOR = 0x466446; // (70,100,70)

export class HelpOverlay {
  private readonly scene: Phaser.Scene;
  private readonly adapter: PlatformAdapter;
  private readonly content: HelpContent;
  private readonly idleTimer = new IdleGlowTimer();

  private open = false;
  private scrollOffset = 0;
  private scrollBounce: ScrollBounce | null = null;
  private currentFlow: HelpOverlayFlow | null = null;
  private enabled = true; // see setEnabled() -- fully hidden/inert while a competing modal is open

  // Touch/mouse drag-to-scroll state, same shape as RulesScene's own.
  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  // "?" button
  private buttonRect!: RectLayout;
  private buttonBg!: Phaser.GameObjects.Rectangle;
  private buttonLabel!: Phaser.GameObjects.Text;
  private glowGfx!: Phaser.GameObjects.Graphics;

  // Modal panel (created lazily on first open(), destroyed on close())
  private modal: {
    dim: Phaser.GameObjects.Rectangle;
    panel: Phaser.GameObjects.Rectangle;
    title: Phaser.GameObjects.Text;
    closeRect: Phaser.GameObjects.Rectangle;
    closeLabel: Phaser.GameObjects.Text;
    content: Phaser.GameObjects.Container;
    clipMask: Phaser.GameObjects.Graphics;
    scrollTrack: Phaser.GameObjects.Rectangle | null;
    scrollThumb: Phaser.GameObjects.Rectangle | null;
    sectionObjects: { heading: Phaser.GameObjects.Text; bodyLines: Phaser.GameObjects.Text[] }[];
  } | null = null;

  constructor(scene: Phaser.Scene, adapter: PlatformAdapter, content: HelpContent) {
    this.scene = scene;
    this.adapter = adapter;
    this.content = content;
  }

  /** Call once from the host scene's create(). */
  create(): void {
    const theme = this.adapter.getTheme();
    this.buttonRect = this.computeButtonRect();

    this.glowGfx = this.scene.add.graphics();
    this.buttonBg = this.scene.add
      .rectangle(0, 0, this.buttonRect.width, this.buttonRect.height, BUTTON_IDLE_COLOR)
      .setStrokeStyle(1, GOLD_LIGHT, 0.6)
      .setInteractive({ useHandCursor: true });
    this.buttonLabel = this.scene.add
      .text(0, 0, '?', { fontFamily: 'sans-serif', fontSize: '18px', color: '#d4af37', fontStyle: 'bold' })
      .setOrigin(0.5);

    this.buttonBg.on('pointerover', () => this.buttonBg.setFillStyle(BUTTON_HOVER_COLOR));
    this.buttonBg.on('pointerout', () => this.buttonBg.setFillStyle(BUTTON_IDLE_COLOR));
    this.buttonBg.on('pointerdown', () => this.toggle());

    this.positionButton();

    // "Any real input event" activity detection -- global, independent
    // of which specific widget was hit, matching notice_activity()'s
    // own literal trigger (mouse motion, click, keypress -- see this
    // class's header). Bound once here, removed in destroy().
    this.scene.input.on(Phaser.Input.Events.POINTER_DOWN, this.handleActivity, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_MOVE, this.handleActivity, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_WHEEL, this.handleActivity, this);
    this.scene.input.keyboard?.on(Phaser.Input.Keyboard.Events.ANY_KEY_DOWN, this.handleActivity, this);

    this.scene.input.on(Phaser.Input.Events.POINTER_WHEEL, this.handleModalWheel, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_MOVE, this.handleDragMove, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.scene.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.scene.input.keyboard?.on(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);

    void theme; // reserved: dim/panel colors are fixed to match the PC's own GOLD_LIGHT/panel palette regardless of theme
  }

  /** Call from the host scene's Scale RESIZE handler AND after any
   * change that could move the safe content rect (e.g. a device
   * safe-area change) -- repositions the button and, if open,
   * re-renders the panel at the new viewport size. */
  layout(): void {
    this.buttonRect = this.computeButtonRect();
    this.positionButton();
    if (this.open) this.renderModal();
  }

  /** Call once per frame from the host scene's update(time, delta).
   *
   * `shouldAccrueIdle` defaults to true (the "always call
   * update_idle_glow every frame" pattern every help-enabled screen
   * but Gameplay uses -- see this class's header). GameTableScene
   * passes `false` while it isn't actually the human's turn (or the
   * game is paused), matching GameplayScene.update()'s own one
   * deviation: idle time shouldn't accrue while the player is just
   * waiting on the AI, which isn't "stuck." */
  update(deltaMs: number, shouldAccrueIdle = true): void {
    if (shouldAccrueIdle) {
      this.idleTimer.update(deltaMs, this.open);
    } else {
      this.idleTimer.noticeActivity();
    }
    this.renderGlow();

    if (!this.open || !this.currentFlow) return;
    const outOfRange = this.scrollOffset < 0 || this.scrollOffset > this.currentFlow.maxScroll;
    if (!this.scrollBounce && !outOfRange) return;
    const result = settleScroll(this.scrollOffset, this.scrollBounce, deltaMs, this.currentFlow.maxScroll);
    this.scrollOffset = result.value;
    this.scrollBounce = result.bounce;
    this.renderModal();
  }

  get isOpen(): boolean {
    return this.open;
  }

  toggle(): void {
    if (this.open) this.close();
    else this.doOpen();
  }

  /** Suppresses the whole overlay (button hidden/uninteractive, panel
   * force-closed if it was open) -- for a screen with a competing
   * modal of its own (GameConfigScene's MSOMI picker is the one real
   * case on the PC side: two floating popups at once would conflict,
   * so PC's own _layout_help_btn/draw simply don't run while that
   * picker is up). Call with `false` when the competing modal opens,
   * `true` when it closes. */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    if (!enabled && this.open) this.close();
    this.buttonBg.setVisible(enabled);
    this.buttonLabel.setVisible(enabled);
    this.glowGfx.setVisible(enabled);
    if (this.buttonBg.input) this.buttonBg.input.enabled = enabled;
  }

  /** Call from the host scene's SHUTDOWN handler. */
  destroy(): void {
    this.scene.input.off(Phaser.Input.Events.POINTER_DOWN, this.handleActivity, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_MOVE, this.handleActivity, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_WHEEL, this.handleActivity, this);
    this.scene.input.keyboard?.off(Phaser.Input.Keyboard.Events.ANY_KEY_DOWN, this.handleActivity, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_WHEEL, this.handleModalWheel, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_MOVE, this.handleDragMove, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.scene.input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.scene.input.keyboard?.off(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);
    this.destroyModal();
    this.buttonBg.destroy();
    this.buttonLabel.destroy();
    this.glowGfx.destroy();
  }

  // ── internals ───────────────────────────────────────────────────

  private viewport(): Viewport {
    return { width: this.scene.scale.width, height: this.scene.scale.height };
  }

  private computeButtonRect(): RectLayout {
    const viewport = this.viewport();
    const insets = this.adapter.getSafeAreaInsets();
    const contentRect = getSafeContentRect(viewport, insets);
    return computeHelpButtonRect(viewport, contentRect);
  }

  private positionButton(): void {
    const cx = this.buttonRect.x + this.buttonRect.width / 2;
    const cy = this.buttonRect.y + this.buttonRect.height / 2;
    this.buttonBg.setPosition(cx, cy).setSize(this.buttonRect.width, this.buttonRect.height);
    if (this.buttonBg.input) {
      this.buttonBg.input.hitArea.width = this.buttonRect.width;
      this.buttonBg.input.hitArea.height = this.buttonRect.height;
    }
    this.buttonLabel.setPosition(cx, cy);
  }

  private renderGlow(): void {
    this.glowGfx.clear();
    const pulse = this.idleTimer.pulse;
    if (!pulse || !this.enabled) return;
    const cx = this.buttonRect.x + this.buttonRect.width / 2;
    const cy = this.buttonRect.y + this.buttonRect.height / 2;
    const radius = this.buttonRect.width / 2 + pulse.radiusExtra;
    this.glowGfx.lineStyle(3, GOLD_LIGHT, Math.min(1, pulse.alpha / 255));
    this.glowGfx.strokeCircle(cx, cy, radius);
  }

  private handleActivity(): void {
    this.idleTimer.noticeActivity();
  }

  private doOpen(): void {
    if (!this.enabled) return;
    this.open = true;
    this.scrollOffset = 0;
    this.scrollBounce = null;
    this.idleTimer.noticeActivity();
    this.buildModal();
    this.renderModal();
  }

  private close(): void {
    this.open = false;
    this.destroyModal();
  }

  private handleKeyDown(event: KeyboardEvent): void {
    if (this.open && event.key === 'Escape') this.close();
  }

  private isWithinPanel(x: number, y: number): boolean {
    const flow = this.currentFlow;
    if (!flow) return false;
    return (
      x >= flow.panelRect.x &&
      x <= flow.panelRect.x + flow.panelRect.width &&
      y >= flow.panelRect.y &&
      y <= flow.panelRect.y + flow.panelRect.height
    );
  }

  private isWithinViewportBand(x: number, y: number): boolean {
    const flow = this.currentFlow;
    if (!flow) return false;
    return (
      this.isWithinPanel(x, y) && y >= flow.viewportTop && y <= flow.viewportTop + flow.viewportHeight
    );
  }

  private handleModalWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (!this.open || !this.currentFlow || this.dragging) return;
    if (!this.isWithinPanel(pointer.x, pointer.y)) return;
    pointer.event?.preventDefault();
    this.scrollBounce = null;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, dy, this.currentFlow.maxScroll);
    this.renderModal();
  }

  private handleDragStart(pointer: Phaser.Input.Pointer): void {
    if (!this.open || this.dragPointerId !== null) return;
    if (!this.isWithinViewportBand(pointer.x, pointer.y)) return;
    this.dragging = true;
    this.dragPointerId = pointer.id;
    this.dragLastY = pointer.y;
    this.scrollBounce = null;
  }

  private handleDragMove(pointer: Phaser.Input.Pointer): void {
    if (!this.dragging || pointer.id !== this.dragPointerId || !this.currentFlow) return;
    const delta = this.dragLastY - pointer.y;
    this.dragLastY = pointer.y;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, delta, this.currentFlow.maxScroll);
    this.renderModal();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
  }

  private buildModal(): void {
    const theme = this.adapter.getTheme();
    const dim = this.scene.add
      .rectangle(0, 0, 1, 1, 0x000000, DIM_ALPHA)
      .setOrigin(0, 0)
      .setInteractive();
    dim.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      if (this.currentFlow && this.isWithinPanel(pointer.x, pointer.y)) return;
      this.close();
    });

    const panel = this.scene.add.rectangle(0, 0, 1, 1, PANEL_COLOR, 0.98).setStrokeStyle(1, GOLD_LIGHT, 0.5);
    const title = this.scene.add.text(0, 0, this.content.title, {
      fontFamily: 'sans-serif',
      fontSize: '16px',
      color: '#d4af37',
      fontStyle: 'bold',
    });
    const closeRect = this.scene.add
      .rectangle(0, 0, 1, 1, PANEL_COLOR)
      .setStrokeStyle(2, GOLD_LIGHT, 0.8)
      .setInteractive({ useHandCursor: true });
    closeRect.on('pointerdown', () => this.close());
    const closeLabel = this.scene.add
      .text(0, 0, '\u2715', { fontFamily: 'sans-serif', fontSize: '16px', color: '#ffffff' })
      .setOrigin(0.5);

    const content = this.scene.add.container(0, 0);
    const clipMask = this.scene.make.graphics(undefined, false);
    content.setMask(clipMask.createGeometryMask());

    this.modal = {
      dim,
      panel,
      title,
      closeRect,
      closeLabel,
      content,
      clipMask,
      scrollTrack: null,
      scrollThumb: null,
      sectionObjects: [],
    };
    void theme;
  }

  private destroyModal(): void {
    if (!this.modal) return;
    for (const obj of this.modal.sectionObjects) {
      obj.heading.destroy();
      for (const line of obj.bodyLines) line.destroy();
    }
    this.modal.scrollTrack?.destroy();
    this.modal.scrollThumb?.destroy();
    this.modal.dim.destroy();
    this.modal.panel.destroy();
    this.modal.title.destroy();
    this.modal.closeRect.destroy();
    this.modal.closeLabel.destroy();
    this.modal.content.destroy();
    this.modal.clipMask.destroy();
    this.modal = null;
    this.currentFlow = null;
  }

  private isOffscreen(y: number, flow: HelpOverlayFlow): boolean {
    return y < flow.viewportTop - 40 || y > flow.viewportTop + flow.viewportHeight;
  }

  private renderModal(): void {
    if (!this.modal) return;
    const viewport = this.viewport();
    const flow = computeHelpOverlayFlow(viewport, this.content, this.scrollOffset);
    this.currentFlow = flow;

    this.modal.dim.setSize(viewport.width, viewport.height);

    const panelCx = flow.panelRect.x + flow.panelRect.width / 2;
    const panelCy = flow.panelRect.y + flow.panelRect.height / 2;
    this.modal.panel.setPosition(panelCx, panelCy).setSize(flow.panelRect.width, flow.panelRect.height);

    // Wrapped rather than left to overlap the close button -- PC's own
    // draw() renders this title at a fixed x with no width clamp
    // either (widgets.py ~1591), but PC's panel is never narrower than
    // ~944px (min(680, 1024-80), its lowest supported resolution);
    // this renderer's MIN_PANEL_WIDTH floor (260px, for phone
    // viewports PC never has to handle) makes a long title actually
    // reach the close button, found via this pass's own SVG layout
    // verification render on a 480px-wide mockup.
    this.modal.title
      .setPosition(flow.titleLine.x, flow.titleLine.y)
      .setFontSize(flow.titleLine.fontPx)
      .setWordWrapWidth(Math.max(20, flow.closeButton.x - flow.titleLine.x - 10), true);

    const closeCx = flow.closeButton.x + flow.closeButton.width / 2;
    const closeCy = flow.closeButton.y + flow.closeButton.height / 2;
    this.modal.closeRect.setPosition(closeCx, closeCy).setSize(flow.closeButton.width, flow.closeButton.height);
    if (this.modal.closeRect.input) {
      this.modal.closeRect.input.hitArea.width = flow.closeButton.width;
      this.modal.closeRect.input.hitArea.height = flow.closeButton.height;
    }
    this.modal.closeLabel.setPosition(closeCx, closeCy);

    this.modal.clipMask.clear();
    this.modal.clipMask.fillStyle(0xffffff);
    this.modal.clipMask.fillRect(flow.panelRect.x, flow.viewportTop, flow.panelRect.width, flow.viewportHeight);

    // Rebuild scrollable section text from scratch on every render(),
    // same throwaway-and-recreate discipline as RulesScene's own
    // render() (see that file's header for why this is fine at this
    // content's scale).
    for (const obj of this.modal.sectionObjects) {
      obj.heading.destroy();
      for (const line of obj.bodyLines) line.destroy();
    }
    this.modal.sectionObjects = [];

    for (const section of flow.sections) {
      if (this.isOffscreen(section.heading.y, flow) && section.bodyLines.every((l) => this.isOffscreen(l.y, flow))) {
        continue;
      }
      const headingObj = this.scene.add.text(section.heading.x, section.heading.y, section.heading.text, {
        fontFamily: 'sans-serif',
        fontSize: `${section.heading.fontPx}px`,
        color: '#d4af37',
        fontStyle: 'bold',
      });
      const bodyObjs = section.bodyLines
        .filter((line) => !this.isOffscreen(line.y, flow))
        .map((line) =>
          this.scene.add.text(line.x, line.y, line.text, {
            fontFamily: 'sans-serif',
            fontSize: `${line.fontPx}px`,
            color: '#ffffff',
          }),
        );
      this.modal.content.add([headingObj, ...bodyObjs]);
      this.modal.sectionObjects.push({ heading: headingObj, bodyLines: bodyObjs });
    }

    this.modal.scrollTrack?.destroy();
    this.modal.scrollThumb?.destroy();
    this.modal.scrollTrack = null;
    this.modal.scrollThumb = null;
    if (flow.scrollbarTrack && flow.scrollbarThumb) {
      const track = flow.scrollbarTrack;
      const thumb = flow.scrollbarThumb;
      this.modal.scrollTrack = this.scene.add.rectangle(
        track.x + track.width / 2,
        track.y + track.height / 2,
        track.width,
        track.height,
        0x3c424e,
      );
      this.modal.scrollThumb = this.scene.add.rectangle(
        thumb.x + thumb.width / 2,
        thumb.y + thumb.height / 2,
        thumb.width,
        thumb.height,
        GOLD_LIGHT,
        0.8,
      );
    }
  }
}
