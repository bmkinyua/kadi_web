import Phaser from 'phaser';
import type { MsomiStore, PlatformAdapter } from '@kadi/adapter-interface';
import { MainMenuScene } from './MainMenuScene.js';
import { MultiplayerMenuScene } from './MultiplayerMenuScene.js';
import { GameConfigScene } from './GameConfigScene.js';
import { LobbyScene } from './LobbyScene.js';
import { InternetLobbyScene } from './InternetLobbyScene.js';
import { GameTableScene } from './GameTableScene.js';
import { RulesScene } from './RulesScene.js';
import { SettingsScene } from './SettingsScene.js';
import { ProfileScene } from './ProfileScene.js';
import { ChuoScene } from './ChuoScene.js';
import {
  BASE_HEIGHT,
  BASE_WIDTH,
  MAX_VIEWPORT_HEIGHT,
  MAX_VIEWPORT_WIDTH,
  MIN_VIEWPORT_HEIGHT,
  MIN_VIEWPORT_WIDTH,
} from './layout/scale.js';

export { MainMenuScene } from './MainMenuScene.js';
export { MultiplayerMenuScene } from './MultiplayerMenuScene.js';
export { GameConfigScene } from './GameConfigScene.js';
export { LobbyScene } from './LobbyScene.js';
export { InternetLobbyScene } from './InternetLobbyScene.js';
export { GameTableScene } from './GameTableScene.js';
export { RulesScene } from './RulesScene.js';
export { SettingsScene } from './SettingsScene.js';
export { ProfileScene } from './ProfileScene.js';
export { ChuoScene } from './ChuoScene.js';
export * from './layout/scale.js';
export * from './layout/safeArea.js';
export * from './layout/MainMenuLayout.js';
export * from './layout/MultiplayerMenuLayout.js';
export * from './layout/GameConfigLayout.js';
export * from './layout/LobbyLayout.js';
export * from './layout/InternetLobbyLayout.js';
export * from './layout/GameTableLayout.js';
export * from './layout/RulesLayout.js';
export * from './layout/SettingsLayout.js';
export * from './layout/ProfileLayout.js';
export * from './layout/ChuoLayout.js';
export * from './layout/scrollPhysics.js';
export * from './cardPlayability.js';
export * from './profileData.js';
export * from './msomi/trainer.js';

/**
 * The one function every apps/* entry point calls (see
 * apps/web-pwa/src/main.ts). Takes a concrete adapter -- already
 * chosen by that entry point, per KADI_web_port_implementation_plan.md
 * §2's build-time platform selection -- and boots the shared Phaser
 * game against it. This function itself never imports a concrete
 * adapter class, only the PlatformAdapter type.
 *
 * `msomiStore` (Part B/E) is OPTIONAL and follows the exact same
 * discipline: a concrete MsomiStore is constructed by the entry point
 * (see apps/web-pwa/src/main.ts's own `createMsomiStore()` call, from
 * `@kadi/adapter-web` -- the one place allowed to import it) and
 * handed in here as a value of the `MsomiStore` type only. A platform
 * with no local-filesystem-shaped storage concept at all can simply
 * omit it -- MainMenuScene.ts disables the Chuo button rather than
 * routing anywhere when it's undefined, so this stays safe for a
 * future adapter that never supplies one.
 *
 * SCALE MANAGER (Part A/B): uses Phaser's own Phaser.Scale.RESIZE
 * mode rather than reinventing resize-event handling -- the canvas is
 * told to always match its parent element's actual current size, and
 * Phaser fires a `resize` event on `game.scale` (see LobbyScene's
 * subscription to it) every time that changes, whether from a browser
 * window resize, a mobile orientation change, or a host platform
 * (Discord/Telegram) resizing the iframe/panel around us. `min`/`max`
 * clamp the canvas itself to the supported viewport range (Part B) --
 * see layout/scale.ts's MIN_VIEWPORT_WIDTH / MAX_VIEWPORT_WIDTH (and
 * the HEIGHT equivalents) docs for why those specific numbers were
 * chosen (no fixed platform-mandated range exists to target exactly).
 */
export function bootstrapGame(
  adapter: PlatformAdapter,
  parent: string | HTMLElement,
  msomiStore?: MsomiStore,
): Phaser.Game {
  const game = new Phaser.Game({
    type: Phaser.CANVAS,
    parent,
    backgroundColor: adapter.getTheme().background,
    scale: {
      mode: Phaser.Scale.RESIZE,
      // Initial size before the first real resize measurement lands --
      // matches the old fixed canvas so there's no first-frame jump on
      // a viewport that happens to already be exactly this size.
      width: BASE_WIDTH,
      height: BASE_HEIGHT,
      min: { width: MIN_VIEWPORT_WIDTH, height: MIN_VIEWPORT_HEIGHT },
      max: { width: MAX_VIEWPORT_WIDTH, height: MAX_VIEWPORT_HEIGHT },
    },
    // Deliberately NOT listed here (scene: [MainMenuScene]) -- that
    // would auto-start it with no init data on boot, then starting it
    // again below with the real adapter would run create() twice
    // (two WebSocket connections, once LobbyScene is reached). Added
    // +started exactly once, below, with its init data, instead.
    scene: [],
    callbacks: {
      postBoot: (bootedGame) => {
        // MultiplayerMenuScene, GameConfigScene, LobbyScene,
        // InternetLobbyScene, GameTableScene, RulesScene,
        // SettingsScene, ProfileScene, and ChuoScene are only ever
        // entered via a scene.start() from the scene before them in
        // the flow (MainMenu -> GameConfigScene(vsAi=true) directly,
        // MainMenu -> MultiplayerMenuScene -> GameConfigScene(vsAi=
        // false)/InternetLobbyScene -> GameTable, MainMenu ->
        // RulesScene, MainMenu -> SettingsScene, MainMenu ->
        // ProfileScene, MainMenu -> ChuoScene, see each scene's own
        // docstring) -- registered here (autoStart=false) purely so
        // Phaser's scene manager knows the keys exist to start later;
        // each gets its real init data at that point, not now.
        bootedGame.scene.add('GameTableScene', GameTableScene, false);
        bootedGame.scene.add('LobbyScene', LobbyScene, false);
        bootedGame.scene.add('InternetLobbyScene', InternetLobbyScene, false);
        bootedGame.scene.add('MultiplayerMenuScene', MultiplayerMenuScene, false);
        bootedGame.scene.add('GameConfigScene', GameConfigScene, false);
        bootedGame.scene.add('RulesScene', RulesScene, false);
        bootedGame.scene.add('SettingsScene', SettingsScene, false);
        bootedGame.scene.add('ProfileScene', ProfileScene, false);
        bootedGame.scene.add('ChuoScene', ChuoScene, false);
        bootedGame.scene.add('MainMenuScene', MainMenuScene, true, { adapter, msomiStore });
      },
    },
  });
  return game;
}
