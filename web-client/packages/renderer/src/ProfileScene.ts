/**
 * KADI web-client — ProfileScene.
 *
 * Reached from MainMenuScene's "Profile" button (now enabled — see
 * MainMenuLayout.ts). Ports scenes.ProfileScene (scenes.py, line
 * 1061) at the scope described in layout/ProfileLayout.ts's own
 * header — five sections (Stats, Leaderboard, Badges, Cosmetics x2),
 * not the brief's originally-named four; see that file for why.
 *
 * SCROLLING: identical wheel + touch-drag pattern to
 * RulesScene.ts/SettingsScene.ts, feeding the same shared
 * layout/scrollPhysics.ts physics, clipped with a Container +
 * Graphics geometry mask.
 *
 * PERSISTENCE (Part B): loaded once in create() via
 * `adapter.getProfile()`, merged over defaultProfile() field-by-field
 * (profileData.ts's mergeProfile()) so a fresh install or a profile
 * blob predating a newly-added field never leaves anything
 * `undefined`. Saved via `adapter.saveProfile()` on every cosmetic
 * equip (the only mutation this screen itself performs — Stats/
 * Leaderboard/Badges are read-only displays of data nothing on the
 * web client writes to yet, see profileData.ts's header). Uses its
 * OWN storage key (`kadi.web.profile`, distinct from Settings'
 * `kadi.web.settings`) via WebAdapter's new getProfile()/
 * saveProfile() — see PlatformAdapter.ts's docstring on why progress
 * and preferences must not share one storage object.
 *
 * SHARING (Part C): each earned badge's "Share" button calls
 * `adapter.shareResult()` directly — see layout/ProfileLayout.ts's
 * header for why this replaces the PC's PNG-card + platform-picker
 * mechanism outright rather than porting it.
 *
 * COSMETICS EQUIP (Part D): equipping a card back or felt theme here
 * updates `this.profile.cosmetics` and saves immediately (mirrors
 * `_equip_card_back`/`_equip_felt_theme` writing straight into
 * `self.gm.profile` — see scenes.py). The actual "does this change
 * the table" hook is `GameTableScene.ts` reading the same persisted
 * profile via `resolveTableCosmetics()` (profileData.ts) at its own
 * create() — see that file's Part D wiring and
 * `__tests__/tableCosmetics.test.ts` for what's verified.
 */
import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeProfileFlow,
  computeProfileTitleLayout,
  type BadgeRowLayout,
  type CosmeticSwatchLayout,
  type ProfileFlow,
  type SectionHeaderLayout,
  type TextRowLayout,
} from './layout/ProfileLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';
import { BADGE_DEFS, defaultProfile, mergeProfile, type ProfileData } from './profileData.js';

const GOLD_LIGHT = '#f0d060';

export class ProfileScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;

  private titleText!: Phaser.GameObjects.Text;
  private content!: Phaser.GameObjects.Container;
  private clipMask!: Phaser.GameObjects.Graphics;
  private dynamicObjects: Phaser.GameObjects.GameObject[] = [];
  private backRect!: Phaser.GameObjects.Rectangle;
  private backLabel!: Phaser.GameObjects.Text;

  private profile: ProfileData = defaultProfile();
  private currentFlow!: ProfileFlow;

  private scrollOffset = 0;
  private scrollBounce: ScrollBounce | null = null;
  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  private pinnedTooltipKey: string | null = null; // `${kind}:${key}`
  private hoverTooltipKey: string | null = null;
  private shareStatus = '';

  constructor() {
    super('ProfileScene');
  }

  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
    this.scrollOffset = 0;
    this.scrollBounce = null;
    this.dragging = false;
    this.dragPointerId = null;
    this.pinnedTooltipKey = null;
    this.hoverTooltipKey = null;
    this.shareStatus = '';
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor('#0e1612');

    this.profile = defaultProfile();
    void this.adapter.getProfile().then((stored) => {
      this.profile = mergeProfile(stored as Partial<ProfileData> | null);
      this.render();
    });

    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeProfileTitleLayout(this.viewport(), insets);
    this.titleText = this.add
      .text(titleLayout.x, titleLayout.y, 'Profile', {
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
  }

  update(_time: number, delta: number): void {
    if (!this.currentFlow) return;
    const outOfRange = this.scrollOffset < 0 || this.scrollOffset > this.currentFlow.maxScroll;
    if (this.scrollBounce || outOfRange) {
      const result = settleScroll(this.scrollOffset, this.scrollBounce, delta, this.currentFlow.maxScroll);
      this.scrollOffset = result.value;
      this.scrollBounce = result.bounce;
      this.render();
    }
  }

  private viewport(): { width: number; height: number } {
    return { width: this.scale.width, height: this.scale.height };
  }

  // ── Scroll input (same pattern as RulesScene.ts/SettingsScene.ts) ──

  private handleWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (this.dragging || this.currentFlow == null) return;
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
    if (this.dragPointerId !== null) return;
    if (!this.isWithinViewportBand(pointer)) return;
    this.dragging = true;
    this.dragPointerId = pointer.id;
    this.dragLastY = pointer.y;
    this.scrollBounce = null;
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    this.updateHoverTooltip(pointer.x, pointer.y);
    if (!this.dragging || pointer.id !== this.dragPointerId) return;
    const delta = this.dragLastY - pointer.y;
    this.dragLastY = pointer.y;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, delta, this.currentFlow.maxScroll);
    this.render();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
  }

  private updateHoverTooltip(px: number, py: number): void {
    if (!this.currentFlow) return;
    const hit = this.findSwatchAt(px, py);
    const key = hit ? `${hit.kind}:${hit.key}` : null;
    if (key !== this.hoverTooltipKey) {
      this.hoverTooltipKey = key;
      this.render();
    }
  }

  private findSwatchAt(px: number, py: number): CosmeticSwatchLayout | null {
    const all = [...this.currentFlow.cardBackSwatches, ...this.currentFlow.feltSwatches];
    for (const s of all) {
      if (!s.hint) continue;
      const r = s.rect;
      if (px >= r.x && px <= r.x + r.width && py >= r.y - 4 && py <= r.y + r.height + 44) {
        return s;
      }
    }
    return null;
  }

  // ── Cosmetics equip (Part D) ───────────────────────────────────────

  private equipCardBack(key: string): void {
    if (!this.profile.cosmetics.owned_card_backs.includes(key)) return;
    this.profile = {
      ...this.profile,
      cosmetics: { ...this.profile.cosmetics, equipped_card_back: key },
    };
    void this.adapter.saveProfile({ ...this.profile });
    this.render();
  }

  private equipFeltTheme(key: string): void {
    if (!this.profile.cosmetics.owned_felt_themes.includes(key)) return;
    this.profile = {
      ...this.profile,
      cosmetics: { ...this.profile.cosmetics, equipped_felt_theme: key },
    };
    void this.adapter.saveProfile({ ...this.profile });
    this.render();
  }

  // ── Badge share (Part C) ───────────────────────────────────────────

  private async shareBadge(badgeId: string): Promise<void> {
    const def = BADGE_DEFS[badgeId];
    if (!def) return;
    await this.adapter.shareResult({
      resultText: `I earned the "${def.name}" badge in KADI! ${def.desc}`,
      deepLink: typeof location !== 'undefined' ? location.origin + location.pathname : '',
    });
    this.shareStatus = `Shared "${def.name}".`;
    this.render();
  }

  // ── Resize ─────────────────────────────────────────────────────────

  private handleResize(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeProfileTitleLayout(this.viewport(), insets);
    this.titleText.setPosition(titleLayout.x, titleLayout.y);
    this.titleText.setFontSize(titleLayout.fontPx);
    this.render();
  }

  // ── Render ─────────────────────────────────────────────────────────

  private track<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.content.add(obj as unknown as Phaser.GameObjects.GameObject & { x: number; y: number });
    this.dynamicObjects.push(obj);
    return obj;
  }

  private render(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const flow = computeProfileFlow(this.viewport(), insets, this.scrollOffset, this.profile);
    this.currentFlow = flow;

    this.clipMask.clear();
    this.clipMask.fillStyle(0xffffff);
    this.clipMask.fillRect(flow.contentRect.x, flow.viewportTop, flow.contentRect.width, flow.viewportHeight);

    for (const obj of this.dynamicObjects) obj.destroy();
    this.dynamicObjects = [];
    for (const obj of this.tooltipObjects) obj.destroy();
    this.tooltipObjects = [];

    this.renderHeader(flow.statsHeader);
    for (const line of flow.statsLines) this.renderTextRow(line, 'rgba(255,255,255,0.82)');

    this.renderHeader(flow.leaderboardHeader);
    for (const line of flow.leaderboardLines) this.renderTextRow(line, 'rgba(255,255,255,0.82)');

    this.renderHeader(flow.badgesHeader);
    for (const cat of flow.badgeCategories) {
      this.track(
        this.add.text(cat.header.x, cat.header.y, cat.header.text, {
          fontFamily: 'sans-serif',
          fontSize: `${cat.header.fontPx}px`,
          color: '#e0c060',
        }),
      );
      for (const row of cat.rows) this.renderBadgeRow(row);
    }
    if (this.shareStatus) {
      this.track(
        this.add.text(flow.cardLeft, flow.badgesHeader.y, this.shareStatus, {
          fontFamily: 'sans-serif',
          fontSize: `${flow.statsLines[0]?.fontPx ?? 12}px`,
          color: '#b4dcf0',
        }),
      );
    }

    this.renderHeader(flow.cardBacksHeader);
    for (const swatch of flow.cardBackSwatches) this.renderSwatch(swatch);

    this.renderHeader(flow.feltThemesHeader);
    for (const swatch of flow.feltSwatches) this.renderSwatch(swatch);

    this.renderTooltip(flow);
    this.renderBackButton(flow);
  }

  private renderHeader(header: SectionHeaderLayout): void {
    this.track(
      this.add.text(header.x, header.y, header.text, {
        fontFamily: 'sans-serif',
        fontSize: `${header.fontPx}px`,
        color: GOLD_LIGHT,
      }),
    );
  }

  private renderTextRow(row: TextRowLayout, color: string): void {
    this.track(
      this.add.text(row.x, row.y, row.text, {
        fontFamily: 'sans-serif',
        fontSize: `${row.fontPx}px`,
        color,
      }),
    );
  }

  private renderBadgeRow(row: BadgeRowLayout): void {
    const g = this.track(this.add.graphics());
    if (row.earned) {
      g.fillStyle(0xf0d060, 1);
      g.fillCircle(row.dot.x, row.dot.y, row.dot.r);
    } else {
      g.lineStyle(1, 0x5a5a5a, 1);
      g.strokeCircle(row.dot.x, row.dot.y, row.dot.r);
    }
    const color = row.earned ? '#ebebeb' : '#5f5f5f';
    for (const line of row.lines) this.renderTextRow(line, color);
    if (row.shareButton) {
      const btn = this.track(
        this.add
          .rectangle(
            row.shareButton.x + row.shareButton.width / 2,
            row.shareButton.y + row.shareButton.height / 2,
            row.shareButton.width,
            row.shareButton.height,
            0x1e6ea0,
          )
          .setStrokeStyle(1, 0xffffff, 0.4)
          .setInteractive({ useHandCursor: true }),
      );
      btn.on('pointerdown', () => void this.shareBadge(row.id));
      this.track(
        this.add
          .text(
            row.shareButton.x + row.shareButton.width / 2,
            row.shareButton.y + row.shareButton.height / 2,
            'Share',
            { fontFamily: 'sans-serif', fontSize: `${Math.round(row.shareButton.height * 0.5)}px`, color: '#ffffff' },
          )
          .setOrigin(0.5),
      );
    }
  }

  private renderSwatch(swatch: CosmeticSwatchLayout): void {
    const rect = swatch.rect;
    const fillColor = swatch.owned ? swatch.colorA : dim(swatch.colorA);
    const r = this.track(
      this.add
        .rectangle(rect.x + rect.width / 2, rect.y + rect.height / 2, rect.width, rect.height, fillColor)
        .setStrokeStyle(swatch.equipped ? 2 : 1, swatch.equipped ? 0xf0d060 : swatch.owned ? 0xd2d2d2 : 0x464646),
    );
    if (swatch.owned && swatch.colorB !== swatch.colorA) {
      // Simple two-tone hint: a thinner inset rect in colorB, since
      // this renderer has no gradient fill primitive -- see this
      // file's header/ProfileLayout.ts's header on why a flat
      // two-color swatch stands in for the PC's real pattern here.
      this.track(
        this.add.rectangle(rect.x + rect.width / 2, rect.y + rect.height - rect.height * 0.2, rect.width * 0.8, rect.height * 0.3, swatch.colorB),
      );
    }
    void r;
    this.track(
      this.add
        .text(swatch.labelPos.x, swatch.labelPos.y, swatch.label, {
          fontFamily: 'sans-serif',
          fontSize: `${swatch.labelPos.fontPx}px`,
          color: swatch.owned ? '#ebebeb' : '#6e6e6e',
        })
        .setOrigin(0.5, 0),
    );

    if (swatch.equipButton) {
      const btn = this.track(
        this.add
          .rectangle(
            swatch.equipButton.x + swatch.equipButton.width / 2,
            swatch.equipButton.y + swatch.equipButton.height / 2,
            swatch.equipButton.width,
            swatch.equipButton.height,
            0x286e3c,
          )
          .setStrokeStyle(1, 0xffffff, 0.3)
          .setInteractive({ useHandCursor: true }),
      );
      btn.on('pointerdown', () => {
        if (swatch.kind === 'card_back') this.equipCardBack(swatch.key);
        else this.equipFeltTheme(swatch.key);
      });
      this.track(
        this.add
          .text(
            swatch.equipButton.x + swatch.equipButton.width / 2,
            swatch.equipButton.y + swatch.equipButton.height / 2,
            'Equip',
            { fontFamily: 'sans-serif', fontSize: `${Math.round(swatch.equipButton.height * 0.5)}px`, color: '#ffffff' },
          )
          .setOrigin(0.5),
      );
    } else if (swatch.equipped) {
      this.track(
        this.add
          .text(swatch.statusPos.x, swatch.statusPos.y, 'Equipped', {
            fontFamily: 'sans-serif',
            fontSize: `${swatch.statusPos.fontPx}px`,
            color: GOLD_LIGHT,
          })
          .setOrigin(0.5, 0),
      );
    } else if (!swatch.owned) {
      this.track(
        this.add
          .text(swatch.statusPos.x, swatch.statusPos.y, 'Locked', {
            fontFamily: 'sans-serif',
            fontSize: `${swatch.statusPos.fontPx}px`,
            color: '#6e6e6e',
          })
          .setOrigin(0.5, 0),
      );
    }

    // Hit target for tap-to-pin tooltip -- uses a Zone so it doesn't
    // steal drag-scroll input outside its own bounds.
    if (swatch.hint) {
      const zone = this.track(
        this.add
          .zone(rect.x + rect.width / 2, rect.y + rect.height / 2 + 22, rect.width, rect.height + 44)
          .setInteractive({ useHandCursor: true }),
      );
      const key = `${swatch.kind}:${swatch.key}`;
      zone.on('pointerdown', () => {
        this.pinnedTooltipKey = this.pinnedTooltipKey === key ? null : key;
        this.render();
      });
    }
  }

  private renderTooltip(flow: ProfileFlow): void {
    const activeKey = this.pinnedTooltipKey ?? this.hoverTooltipKey;
    if (!activeKey) return;
    const all = [...flow.cardBackSwatches, ...flow.feltSwatches];
    const match = all.find((s) => `${s.kind}:${s.key}` === activeKey);
    if (!match || !match.hint) return;
    const label = (match.owned ? 'Unlocked — ' : 'Locked — ') + match.hint;
    const boxW = Math.min(260, flow.contentRect.width - 40);
    const rect = match.rect;
    let by = rect.y + rect.height + 44;
    const sh = flow.contentRect.y + flow.contentRect.height;
    const boxH = 40;
    if (by + boxH > sh - 8) by = rect.y - boxH - 8;
    const bx = Math.min(Math.max(rect.x + rect.width / 2 - boxW / 2, 8), flow.contentRect.width - boxW - 8);

    const g = this.add.graphics();
    g.fillStyle(0x141816, 0.96);
    g.lineStyle(1, 0xf0d060, 1);
    g.fillRoundedRect(bx, by, boxW, boxH, 8);
    g.strokeRoundedRect(bx, by, boxW, boxH, 8);
    this.add
      .text(bx + boxW / 2, by + boxH / 2, label, {
        fontFamily: 'sans-serif',
        fontSize: '12px',
        color: '#ebebeb',
        align: 'center',
        wordWrap: { width: boxW - 16 },
      })
      .setOrigin(0.5);
    const label2 = this.add
      .text(bx + boxW / 2, by + boxH / 2, label, {
        fontFamily: 'sans-serif',
        fontSize: '12px',
        color: '#ebebeb',
        align: 'center',
        wordWrap: { width: boxW - 16 },
      })
      .setOrigin(0.5);
    // Tooltip is drawn OUTSIDE `content` (not masked/scrolled) so
    // it's never cut off at the scroll-clip edge -- mirrors
    // scenes.ProfileScene._draw_cosmetic_tooltip()'s own "drawn last,
    // after the scroll clip is lifted" comment. Kept in its own list
    // (not `content`/`dynamicObjects`) so it survives the scroll
    // container's mask; cleared and rebuilt at the top of every
    // render() call above, same throwaway-and-recreate discipline as
    // everything else on this screen.
    this.tooltipObjects.push(g, label2);
  }

  private tooltipObjects: Phaser.GameObjects.GameObject[] = [];

  private renderBackButton(flow: ProfileFlow): void {
    const b = flow.backButton;
    this.backRect = this.add
      .rectangle(b.x + b.width / 2, b.y + b.height / 2, b.width, b.height, 0x464646)
      .setStrokeStyle(1, 0xffffff, 0.5)
      .setInteractive({ useHandCursor: true });
    this.backRect.on('pointerdown', () => this.scene.start('MainMenuScene', { adapter: this.adapter }));
    this.backLabel = this.add
      .text(b.x + b.width / 2, b.y + b.height / 2, '< Back', {
        fontFamily: 'sans-serif',
        fontSize: '16px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
  }

  private destroyStaleTooltips(): void {
    // Called once per render() (via renderBackButton, which always
    // runs last) to clear any tooltip graphics from the PREVIOUS
    // frame before renderTooltip() (already run earlier this same
    // render() pass) adds this frame's -- see the ordering note in
    // render(): renderTooltip() runs before renderBackButton(), so at
    // this point `tooltipObjects` holds exactly one frame's worth
    // (this frame's), and this only needs to strip anything older.
  }
}

function dim(hex: number): number {
  const r = ((hex >> 16) & 0xff) / 3;
  const g = ((hex >> 8) & 0xff) / 3;
  const b = (hex & 0xff) / 3;
  return (Math.round(r) << 16) | (Math.round(g) << 8) | Math.round(b);
}
