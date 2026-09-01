import Phaser from 'phaser';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import { LobbyScene } from './LobbyScene.js';

export { LobbyScene } from './LobbyScene.js';

/**
 * The one function every apps/* entry point calls (see
 * apps/web-pwa/src/main.ts). Takes a concrete adapter -- already
 * chosen by that entry point, per KADI_web_port_implementation_plan.md
 * §2's build-time platform selection -- and boots the shared Phaser
 * game against it. This function itself never imports a concrete
 * adapter class, only the PlatformAdapter type.
 */
export function bootstrapGame(adapter: PlatformAdapter, parent: string | HTMLElement): Phaser.Game {
  const game = new Phaser.Game({
    type: Phaser.CANVAS,
    parent,
    width: 480,
    height: 640,
    backgroundColor: adapter.getTheme().background,
    // Deliberately NOT listed here (scene: [LobbyScene]) -- that
    // would auto-start it with no init data on boot, then starting it
    // again below with the real adapter would run create() twice
    // (two WebSocket connections). Added+started exactly once, below,
    // with its init data, instead.
    scene: [],
    callbacks: {
      postBoot: (bootedGame) => {
        bootedGame.scene.add('LobbyScene', LobbyScene, true, { adapter });
      },
    },
  });
  return game;
}
