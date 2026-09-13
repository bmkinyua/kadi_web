/**
 * KADI web-client — ModeSelectScene.
 *
 * Reached from MainMenuScene's "Play" button. See
 * layout/ModeSelectLayout.ts's docstring for full scope reasoning
 * (why only two modes, why no LAN). "Internet Multiplayer" now routes
 * to InternetLobbyScene -- the real browse/host/join/waiting-room flow
 * (see that file's own docstring) -- rather than the plain LobbyScene,
 * which remains the Quick-Play-vs-AI destination for "Play vs AI"
 * only, unchanged.
 *
 * RENDERING/LAYOUT DISCIPLINE: same as every other scene (§6, §6a).
 */
import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeModeSelectLayout,
  type ModeSelectButtonLayout,
  type ModeSelectLayout,
} from './layout/ModeSelectLayout.js';

interface ButtonObjects {
  rect: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
}

const BUTTON_COLORS: Record<string, number> = {
  vsAi: 0x2a5a34,
  internet: 0x5a3a8a,
  back: 0x505050,
};

export class ModeSelectScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;

  private titleText!: Phaser.GameObjects.Text;
  private buttonObjects = new Map<string, ButtonObjects>();

  constructor() {
    super('ModeSelectScene');
  }

  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    const layout = this.currentLayout();

    this.titleText = this.add
      .text(layout.title.x, layout.title.y, 'Choose a mode', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.title.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
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

  private currentLayout(): ModeSelectLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeModeSelectLayout(viewport, insets);
  }

  private createButton(button: ModeSelectButtonLayout): ButtonObjects {
    const fillColor = BUTTON_COLORS[button.id] ?? 0x2a5a34;

    const rect = this.add
      .rectangle(
        button.x + button.width / 2,
        button.y + button.height / 2,
        button.width,
        button.height,
        fillColor,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setInteractive({ useHandCursor: true });

    const label = this.add
      .text(rect.x, rect.y, button.label, {
        fontFamily: 'sans-serif',
        fontSize: '14px',
        color: '#ffffff',
      })
      .setOrigin(0.5);

    rect.on('pointerdown', () => this.onButtonTapped(button.id));

    return { rect, label };
  }

  private onButtonTapped(id: string): void {
    if (id === 'vsAi') {
      // autoQuickPlay: skip a second, redundant tap on LobbyScene's
      // own "Quick Play vs AI" button -- see LobbyScene.ts's init().
      this.scene.start('LobbyScene', { adapter: this.adapter, autoQuickPlay: true });
    } else if (id === 'internet') {
      this.scene.start('InternetLobbyScene', { adapter: this.adapter });
    } else if (id === 'back') {
      this.scene.start('MainMenuScene', { adapter: this.adapter });
    }
  }

  private handleResize(): void {
    const layout = this.currentLayout();

    this.titleText.setPosition(layout.title.x, layout.title.y);
    this.titleText.setFontSize(layout.title.fontPx);

    for (const button of layout.buttons) {
      const objects = this.buttonObjects.get(button.id);
      if (!objects) continue;
      const cx = button.x + button.width / 2;
      const cy = button.y + button.height / 2;
      objects.rect.setPosition(cx, cy);
      objects.rect.setSize(button.width, button.height);
      if (objects.rect.input) {
        objects.rect.input.hitArea.width = button.width;
        objects.rect.input.hitArea.height = button.height;
      }
      objects.label.setPosition(cx, cy);
    }
  }
}
