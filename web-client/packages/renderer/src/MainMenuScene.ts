/**
 * KADI web-client — MainMenuScene: the game's real entry point.
 *
 * Before this scene existed, `apps/web-pwa/src/main.ts` booted
 * straight into LobbyScene (see index.ts's previous
 * `bootedGame.scene.add('LobbyScene', LobbyScene, true, { adapter })`),
 * and LobbyScene itself offered nothing but "Quick Play vs AI" — no
 * real menu, no way to reach a future Internet Multiplayer flow
 * without it being bolted onto the lobby screen itself. This scene is
 * the plan §9 fix: Main Menu → Mode Select → Lobby, matching the PC
 * client's own entry flow (scenes.py's MainMenuScene → ModeSelectScene)
 * at the scope this web pass actually needs — see MainMenuLayout.ts's
 * own docstring for exactly which PC buttons made the cut and why.
 *
 * RENDERING/LAYOUT DISCIPLINE: same as every other scene (§6, §6a) —
 * canvas-only GameObjects, every position/size from
 * computeMainMenuLayout(), recomputed on every genuine resize.
 */
import Phaser from 'phaser';
import type { MsomiStore, PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeMainMenuLayout,
  type MainMenuButtonLayout,
  type MainMenuLayout,
} from './layout/MainMenuLayout.js';

interface ButtonObjects {
  rect: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
}

export class MainMenuScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  /** Optional (Part E) -- undefined for a platform with no local-
   * filesystem-shaped storage concept at all; see index.ts's
   * bootstrapGame() header. The Chuo button is disabled rather than
   * routed anywhere when this is undefined (see createButtonDefs()
   * below). */
  private msomiStore: MsomiStore | undefined;

  private titleText!: Phaser.GameObjects.Text;
  private subtitleText!: Phaser.GameObjects.Text;
  private buttonObjects = new Map<string, ButtonObjects>();

  constructor() {
    super('MainMenuScene');
  }

  init(data: { adapter: PlatformAdapter; msomiStore?: MsomiStore }): void {
    this.adapter = data.adapter;
    this.msomiStore = data.msomiStore;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    const layout = this.currentLayout();

    this.titleText = this.add
      .text(layout.title.x, layout.title.y, 'KADI', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.title.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5);

    this.subtitleText = this.add
      .text(layout.subtitle.x, layout.subtitle.y, 'A Swahili card game', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.subtitle.fontPx}px`,
        color: theme.accent,
      })
      .setOrigin(0.5);

    for (const button of layout.buttons) {
      this.buttonObjects.set(button.id, this.createButton(button));
    }

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    });
  }

  private currentLayout(): MainMenuLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    const layout = computeMainMenuLayout(viewport, insets);
    if (!this.msomiStore) {
      // See this file's own header on msomiStore -- disable rather
      // than route anywhere when no store was supplied.
      layout.buttons = layout.buttons.map((b) => (b.id === 'chuo' ? { ...b, enabled: false } : b));
    }
    return layout;
  }

  private createButton(button: MainMenuButtonLayout): ButtonObjects {
    const fillColor = button.enabled ? 0x2a5a34 : 0x3a3a3a;
    const textColor = button.enabled ? '#ffffff' : '#9a9a9a';

    const rect = this.add
      .rectangle(
        button.x + button.width / 2,
        button.y + button.height / 2,
        button.width,
        button.height,
        fillColor,
      )
      .setStrokeStyle(1, 0xffffff, button.enabled ? 0.6 : 0.25);

    const label = this.add
      .text(rect.x, rect.y, button.label, {
        fontFamily: 'sans-serif',
        fontSize: '14px',
        color: textColor,
      })
      .setOrigin(0.5);

    if (button.enabled) {
      rect.setInteractive({ useHandCursor: true });
      rect.on('pointerdown', () => this.onButtonTapped(button.id));
    }

    return { rect, label };
  }

  private onButtonTapped(id: string): void {
    if (id === 'play') {
      this.scene.start('ModeSelectScene', { adapter: this.adapter });
    } else if (id === 'howToPlay') {
      this.scene.start('RulesScene', { adapter: this.adapter });
    } else if (id === 'settings') {
      this.scene.start('SettingsScene', { adapter: this.adapter });
    } else if (id === 'profile') {
      this.scene.start('ProfileScene', { adapter: this.adapter });
    } else if (id === 'chuo' && this.msomiStore) {
      this.scene.start('ChuoScene', { adapter: this.adapter, msomiStore: this.msomiStore });
    }
  }

  private handleResize(): void {
    const layout = this.currentLayout();

    this.titleText.setPosition(layout.title.x, layout.title.y);
    this.titleText.setFontSize(layout.title.fontPx);

    this.subtitleText.setPosition(layout.subtitle.x, layout.subtitle.y);
    this.subtitleText.setFontSize(layout.subtitle.fontPx);

    for (const button of layout.buttons) {
      const objects = this.buttonObjects.get(button.id);
      if (!objects) continue;
      const cx = button.x + button.width / 2;
      const cy = button.y + button.height / 2;
      objects.rect.setPosition(cx, cy);
      objects.rect.setSize(button.width, button.height);
      if (objects.rect.input) {
        // Same reasoning as LobbyScene.handleResize(): setInteractive()
        // captured the hit-area size once at creation time, so a
        // resize needs to update it explicitly.
        objects.rect.input.hitArea.width = button.width;
        objects.rect.input.hitArea.height = button.height;
      }
      objects.label.setPosition(cx, cy);
    }
  }
}
