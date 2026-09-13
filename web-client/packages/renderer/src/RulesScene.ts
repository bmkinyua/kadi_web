/**
 * KADI web-client — RulesScene ("How to Play").
 *
 * Reached from MainMenuScene's "How to Play" button (now enabled --
 * see MainMenuLayout.ts). Content and panel-stacking structure are
 * ported from scenes.RulesScene (scenes.py); see layout/RulesLayout.ts
 * for the pure position/wrap math this scene is built on top of, and
 * that file's own header for the two places this translation
 * genuinely departs from the PC original (continuous card-width
 * scaling instead of a per-resolution lookup table; estimated instead
 * of measured text metrics) plus why.
 *
 * SCROLL INPUT -- a genuine web-side addition, not a 1:1 port: the PC
 * original is mouse-wheel-only (scenes.py's RulesScene._on_wheel()).
 * This scene adds touch-drag scrolling (POINTER_DOWN/MOVE/UP within
 * the viewport band) on top of that, because a touch-first web/mobile
 * surface with no scrollbar and no wheel at all needs SOME way to
 * scroll -- wheel-only would leave phone/tablet players with no way
 * to read anything past the first screenful. Both input paths feed
 * the exact same shared physics (layout/scrollPhysics.ts's
 * scrollWheelDelta/settleScroll) that already back RulesScene's PC
 * counterpart, so the *feel* (bounded overshoot, eased settle) is the
 * same regardless of which input drove it.
 *
 * CLIPPING: content above/below the scrollable viewport band is
 * clipped with a Phaser Graphics geometry mask on a Container, the
 * idiomatic Phaser equivalent of the PC's own
 * `surf.set_clip(viewport_rect)` around its whole card-drawing loop
 * (scenes.py's RulesScene.draw()). No other scene here has needed
 * real scroll-clipping yet (InternetLobbyScene's roster list doesn't
 * scroll), so this is the first use of a mask in this codebase.
 *
 * RENDERING/LAYOUT DISCIPLINE: same as every other scene (§6, §6a) --
 * canvas-only GameObjects, every position/size from
 * layout/RulesLayout.ts, recomputed on every scroll-offset change AND
 * every genuine resize (render() is the one call site, same
 * single-source-of-truth pattern as GameTableScene's own re-render
 * discipline).
 */
import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeRulesFlow,
  computeRulesTitleLayout,
  type RulesFlow,
} from './layout/RulesLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';

interface SectionObjects {
  panel: Phaser.GameObjects.Rectangle;
  title: Phaser.GameObjects.Text;
  bodyLines: Phaser.GameObjects.Text[];
}

export class RulesScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;

  private titleText!: Phaser.GameObjects.Text;

  // Everything scrollable lives in this container so one Graphics
  // mask clips it all to the viewport band at once -- see this file's
  // header note on why a mask, and RulesLayout.ts's RulesFlow for the
  // viewportTop/viewportHeight band it's clipped to.
  private content!: Phaser.GameObjects.Container;
  private clipMask!: Phaser.GameObjects.Graphics;
  private sectionObjects: SectionObjects[] = [];
  private backRect!: Phaser.GameObjects.Rectangle;
  private backLabel!: Phaser.GameObjects.Text;

  private scrollOffset = 0;
  private scrollBounce: ScrollBounce | null = null;
  private currentFlow!: RulesFlow;

  // Touch/mouse drag-to-scroll state -- see this file's header note
  // on why this exists at all (no wheel on touch surfaces).
  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  constructor() {
    super('RulesScene');
  }

  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
    // Fresh scroll state on every entry -- this Scene instance is
    // registered once (autoStart=false, see index.ts) and reused
    // across repeated scene.start() calls, so a leftover scroll
    // position or in-flight bounce from a previous visit must not
    // leak into this one (same reset-on-entry reasoning as e.g.
    // GameTableScene's statusTextGuard being rebuilt fresh in
    // create()).
    this.scrollOffset = 0;
    this.scrollBounce = null;
    this.dragging = false;
    this.dragPointerId = null;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeRulesTitleLayout(this.viewport(), insets);

    this.titleText = this.add
      .text(titleLayout.x, titleLayout.y, 'How to Play', {
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
    this.input.on(Phaser.Input.Events.POINTER_MOVE, this.handleDragMove, this);
    this.input.on(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
      this.input.off(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
      this.input.off(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
      this.input.off(Phaser.Input.Events.POINTER_MOVE, this.handleDragMove, this);
      this.input.off(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
      this.input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    });
  }

  update(_time: number, delta: number): void {
    // Only pay for a re-render while a settle is actually needed --
    // an in-range, non-bouncing scroll position is otherwise static
    // between input events and needs no per-frame work.
    const outOfRange = this.scrollOffset < 0 || this.scrollOffset > this.currentFlow.maxScroll;
    if (!this.scrollBounce && !outOfRange) return;

    const result = settleScroll(this.scrollOffset, this.scrollBounce, delta, this.currentFlow.maxScroll);
    this.scrollOffset = result.value;
    this.scrollBounce = result.bounce;
    this.render();
  }

  private viewport(): { width: number; height: number } {
    return { width: this.scale.width, height: this.scale.height };
  }

  private handleWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (this.dragging) return; // an active drag owns the scroll for its duration
    pointer.event?.preventDefault();
    this.scrollBounce = null; // a fresh wheel tick interrupts any in-flight settle, same as starting a fresh drag would
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, dy, this.currentFlow.maxScroll);
    this.render();
  }

  private isWithinViewportBand(pointer: Phaser.Input.Pointer): boolean {
    const flow = this.currentFlow;
    return pointer.y >= flow.viewportTop && pointer.y <= flow.viewportTop + flow.viewportHeight;
  }

  private handleDragStart(pointer: Phaser.Input.Pointer): void {
    if (this.dragPointerId !== null) return; // already tracking a drag from another pointer
    if (!this.isWithinViewportBand(pointer)) return;
    this.dragging = true;
    this.dragPointerId = pointer.id;
    this.dragLastY = pointer.y;
    this.scrollBounce = null;
  }

  private handleDragMove(pointer: Phaser.Input.Pointer): void {
    if (!this.dragging || pointer.id !== this.dragPointerId) return;
    // Dragging DOWN (pointer.y increases) should reveal content
    // ABOVE, i.e. decrease scrollOffset -- the opposite sign
    // convention from a wheel's deltaY, so the delta fed into the
    // same shared scrollWheelDelta() is deliberately inverted here.
    const delta = this.dragLastY - pointer.y;
    this.dragLastY = pointer.y;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, delta, this.currentFlow.maxScroll);
    this.render();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
    // No fling/momentum on release -- a direct 1:1 drag plus the
    // overshoot-then-settle bounce already running every frame in
    // update() reads as responsive without a separate momentum-
    // physics system this task didn't call for.
  }

  private isOffscreen(rect: RectLayout, flow: RulesFlow): boolean {
    return rect.y + rect.height < flow.viewportTop || rect.y > flow.viewportTop + flow.viewportHeight;
  }

  private render(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const flow = computeRulesFlow(this.viewport(), insets, this.scrollOffset);
    this.currentFlow = flow;

    this.clipMask.clear();
    this.clipMask.fillStyle(0xffffff);
    this.clipMask.fillRect(flow.contentRect.x, flow.viewportTop, flow.contentRect.width, flow.viewportHeight);

    // Rebuild the scrollable section GameObjects from scratch on
    // every render() -- same throwaway-and-recreate discipline as
    // GameTableScene's clearDynamic()/track() pattern; simpler than
    // diffing given how cheap ~6 small text panels are to recreate on
    // every scroll tick, and it naturally skips any panel that has
    // scrolled fully offscreen (see the isOffscreen() check below)
    // rather than needing separate show/hide bookkeeping per panel.
    for (const obj of this.sectionObjects) {
      obj.panel.destroy();
      obj.title.destroy();
      for (const line of obj.bodyLines) line.destroy();
    }
    this.sectionObjects = [];

    const theme = this.adapter.getTheme();
    for (const section of flow.sections) {
      if (this.isOffscreen(section.panelRect, flow)) continue;

      const panel = this.add
        .rectangle(
          section.panelRect.x + section.panelRect.width / 2,
          section.panelRect.y + section.panelRect.height / 2,
          section.panelRect.width,
          section.panelRect.height,
          0x1e1e1e,
          0.9,
        )
        .setStrokeStyle(1, 0xffffff, 0.15);

      const title = this.add.text(section.title.x, section.title.y, section.title.text, {
        fontFamily: 'sans-serif',
        fontSize: `${section.title.fontPx}px`,
        color: theme.accent,
        fontStyle: 'bold',
      });

      const bodyLines = section.bodyLines.map((line) =>
        this.add.text(line.x, line.y, line.text, {
          fontFamily: 'sans-serif',
          fontSize: `${line.fontPx}px`,
          color: theme.text,
        }),
      );

      this.content.add([panel, title, ...bodyLines]);
      this.sectionObjects.push({ panel, title, bodyLines });
    }

    this.renderBackButton(flow, theme);
  }

  private renderBackButton(flow: RulesFlow, theme: ReturnType<PlatformAdapter['getTheme']>): void {
    const cx = flow.backButton.x + flow.backButton.width / 2;
    const cy = flow.backButton.y + flow.backButton.height / 2;

    if (!this.backRect) {
      this.backRect = this.add
        .rectangle(cx, cy, flow.backButton.width, flow.backButton.height, 0x505050)
        .setStrokeStyle(1, 0xffffff, 0.6)
        .setInteractive({ useHandCursor: true });
      this.backRect.on('pointerdown', () => {
        this.scene.start('MainMenuScene', { adapter: this.adapter });
      });
      this.backLabel = this.add
        .text(cx, cy, 'Back', { fontFamily: 'sans-serif', fontSize: '16px', color: theme.text })
        .setOrigin(0.5);
    }

    this.backRect.setPosition(cx, cy);
    this.backRect.setSize(flow.backButton.width, flow.backButton.height);
    this.backLabel.setPosition(cx, cy);

    // The button scrolls with the rest of the content (matches the
    // PC original -- scenes.py's RulesScene draws its back button
    // inside the same clipped, scrolling loop as its cards). The mask
    // above already hides it visually once it's outside the viewport
    // band, but a Phaser mask has no effect on pointer hit-testing --
    // an invisible-but-still-there rectangle would otherwise keep
    // accepting taps, so its interactivity is toggled explicitly here
    // to match what's actually visible.
    const offscreen = this.isOffscreen(flow.backButton, flow);
    if (this.backRect.input) {
      this.backRect.input.hitArea.width = flow.backButton.width;
      this.backRect.input.hitArea.height = flow.backButton.height;
      this.backRect.input.enabled = !offscreen;
    }

    this.content.add([this.backRect, this.backLabel]);
  }

  private handleResize(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeRulesTitleLayout(this.viewport(), insets);
    this.titleText.setPosition(titleLayout.x, titleLayout.y);
    this.titleText.setFontSize(titleLayout.fontPx);
    this.render();
  }
}
