/**
 * KADI web-client — MultiplayerMenuScene.
 *
 * Reached from MainMenuScene's "Multiplayer" button (see
 * layout/MultiplayerMenuLayout.ts's own header for full scope
 * reasoning and why this replaces the old ModeSelectScene.ts's
 * "which mode" job). "Local Multiplayer" routes to
 * GameConfigScene(vsAi=false); "Internet Multiplayer" routes to
 * InternetLobbyScene, unchanged. No LAN button, ever.
 *
 * BACK: goes to MainMenuScene -- matches MultiplayerMenuScene's own
 * Back on the PC side exactly (scenes.py, line ~4303).
 *
 * RENDERING/LAYOUT DISCIPLINE: same as every other scene (§6, §6a).
 */
import Phaser from 'phaser';
import type { MsomiStore, PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeMultiplayerMenuLayout,
  type MultiplayerMenuButtonLayout,
  type MultiplayerMenuLayout,
} from './layout/MultiplayerMenuLayout.js';
import { HelpOverlay } from './HelpOverlay.js';
import { MULTIPLAYER_MENU_HELP } from './layout/HELP_CONTENT.js';

interface ButtonObjects {
  rect: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
}

const BUTTON_COLORS: Record<string, number> = {
  local: 0x2a5a34,
  internet: 0x5a3a8a,
  back: 0x505050,
};

export class MultiplayerMenuScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  /** Handed straight through to GameConfigScene for the MSOMI attach
   * flow (Local Multiplayer doesn't use it, but GameConfigScene is
   * one shared scene for both modes -- see that file's own header). */
  private msomiStore: MsomiStore | undefined;

  private titleText!: Phaser.GameObjects.Text;
  private buttonObjects = new Map<string, ButtonObjects>();
  private helpOverlay!: HelpOverlay;

  constructor() {
    super('MultiplayerMenuScene');
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
      .text(layout.title.x, layout.title.y, 'Multiplayer', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.title.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5);

    for (const button of layout.buttons) {
      this.buttonObjects.set(button.id, this.createButton(button));
    }

    // Help Overlay -- ported from scenes.MultiplayerMenuScene
    // .HELP_SECTIONS, see HELP_CONTENT.ts.
    this.helpOverlay = new HelpOverlay(this, this.adapter, MULTIPLAYER_MENU_HELP);
    this.helpOverlay.create();

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
      this.helpOverlay.destroy();
    });
  }

  update(_time: number, delta: number): void {
    this.helpOverlay.update(delta);
  }

  private currentLayout(): MultiplayerMenuLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeMultiplayerMenuLayout(viewport, insets);
  }

  private createButton(button: MultiplayerMenuButtonLayout): ButtonObjects {
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
    if (id === 'local') {
      this.scene.start('GameConfigScene', { adapter: this.adapter, vsAi: false, msomiStore: this.msomiStore });
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

    this.helpOverlay.layout();
  }
}
