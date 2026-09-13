/**
 * KADI web-client — ModeSelectScene's layout, as pure data.
 *
 * Same discipline as LobbyLayout.ts/MainMenuLayout.ts.
 *
 * SCOPE (plan §9): the PC version's mode_select flow (scenes.py's
 * ModeSelectScene, reached either directly for "Play vs AI" or via
 * MultiplayerMenuScene for "Local"/"LAN"/"Internet") is a large
 * per-game CONFIGURATION screen (opponent count, AI difficulty,
 * elimination mode, MSOMI model, hot-seat player names, ...). This
 * web pass is deliberately NOT that screen — it's the one screen up
 * from it: which of the modes that actually exist/are planned for
 * web do you want.
 *
 * Only two buttons, because LAN is permanently out (§9) and "Local
 * Multiplayer" (same-device hot-seat, PC's MultiplayerMenuScene) has
 * no planned web row either — a web build's whole reason to exist is
 * one-device-per-player, so hot-seat isn't tracked as a future item
 * the way Profile/Settings/Rules are:
 *
 * - "Play vs AI" — routes to LobbyScene with an autoQuickPlay flag
 *   (see LobbyScene.ts) so the player doesn't have to land on the
 *   lobby and tap a second, redundant "Quick Play vs AI" button after
 *   already choosing that mode here.
 * - "Internet Multiplayer" — routes to InternetLobbyScene: the real
 *   browse/host/join/waiting-room flow (see that file's own docstring)
 *   against the already-working server lobby. No longer a scope cut —
 *   this closed the §9 row that used to live here.
 */
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { SafeAreaInsets } from '@kadi/adapter-interface';

export type ModeSelectButtonId = 'vsAi' | 'internet' | 'back';

export interface ModeSelectButtonLayout {
  id: ModeSelectButtonId;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ModeSelectLayout {
  scale: number;
  contentRect: ContentRect;
  title: TextLayout;
  buttons: ModeSelectButtonLayout[];
}

const BASE_TITLE_Y = 96;
const BASE_BUTTON_WIDTH = 240;
const BASE_BUTTON_HEIGHT = 48;
const BASE_BUTTON_GAP = 20;
const BASE_BUTTONS_START_Y = 180;
const BASE_BACK_BUTTON_WIDTH = 140;
const BASE_BACK_BUTTON_HEIGHT = 40;
const BASE_BACK_GAP = 40;

const MODE_BUTTON_DEFS: { id: ModeSelectButtonId; label: string }[] = [
  { id: 'vsAi', label: 'Play vs AI' },
  { id: 'internet', label: 'Internet Multiplayer' },
];

export function computeModeSelectLayout(rawViewport: Viewport, insets: SafeAreaInsets): ModeSelectLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const title: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };

  const modeSize = enforceMinTouchTarget({
    width: BASE_BUTTON_WIDTH * scale,
    height: BASE_BUTTON_HEIGHT * scale,
  });
  const gap = BASE_BUTTON_GAP * scale;
  const step = modeSize.height + gap;
  const startY = contentRect.y + BASE_BUTTONS_START_Y * scale;

  const buttons: ModeSelectButtonLayout[] = MODE_BUTTON_DEFS.map((def, i) => ({
    id: def.id,
    label: def.label,
    x: centerX - modeSize.width / 2,
    y: startY + i * step,
    width: modeSize.width,
    height: modeSize.height,
  }));

  const backSize = enforceMinTouchTarget({
    width: BASE_BACK_BUTTON_WIDTH * scale,
    height: BASE_BACK_BUTTON_HEIGHT * scale,
  });
  const lastModeButton = buttons[buttons.length - 1];
  const backY = lastModeButton
    ? lastModeButton.y + lastModeButton.height + BASE_BACK_GAP * scale
    : startY;
  buttons.push({
    id: 'back',
    label: 'Back',
    x: centerX - backSize.width / 2,
    y: backY,
    width: backSize.width,
    height: backSize.height,
  });

  return { scale, contentRect, title, buttons };
}
