/**
 * KADI web-client — MultiplayerMenuScene's layout, as pure data.
 *
 * Replaces this codebase's old ModeSelectLayout.ts (see that file's
 * git history) now that a real per-game configuration screen exists
 * (GameConfigLayout.ts/GameConfigScene.ts) — this file now does what
 * its name always implied: the PC's `MultiplayerMenuScene`
 * (scenes.py, class at line 4303), reached from Main Menu's
 * "Multiplayer" button, NOT from "Play vs AI" (which now routes
 * directly to `GameConfigScene(vsAi=true)`, matching
 * `MainMenuScene._rebuild_buttons()`'s own
 * `on_click=lambda: self.manager.switch('mode_select', vs_ai=True)`
 * for that button specifically).
 *
 * Exactly two buttons plus Back, matching the PC's own three-way
 * split minus the permanently-out LAN row (§9):
 * - "Local Multiplayer" — routes to `GameConfigScene(vsAi=false)`.
 * - "Internet Multiplayer" — routes to `InternetLobbyScene`,
 *   untouched.
 * - No LAN placeholder, ever (asserted in this file's own test, same
 *   assertion the old ModeSelectLayout.test.ts carried over).
 *
 * BACK BUTTON: goes to `MainMenuScene`, exactly matching
 * `MultiplayerMenuScene`'s own Back on the PC side — NOT the
 * "improve the back chain" temptation a naive port might reach for
 * (see GameConfigLayout.ts's own header for the matching note on
 * GameConfigScene's Back, which likewise goes straight to Main Menu
 * rather than back here, even though Local Multiplayer was reached
 * through this screen).
 */
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { SafeAreaInsets } from '@kadi/adapter-interface';

export type MultiplayerMenuButtonId = 'local' | 'internet' | 'back';

export interface MultiplayerMenuButtonLayout {
  id: MultiplayerMenuButtonId;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MultiplayerMenuLayout {
  scale: number;
  contentRect: ContentRect;
  title: TextLayout;
  buttons: MultiplayerMenuButtonLayout[];
}

const BASE_TITLE_Y = 96;
const BASE_BUTTON_WIDTH = 260;
const BASE_BUTTON_HEIGHT = 48;
const BASE_BUTTON_GAP = 20;
const BASE_BUTTONS_START_Y = 180;
const BASE_BACK_BUTTON_WIDTH = 140;
const BASE_BACK_BUTTON_HEIGHT = 40;
const BASE_BACK_GAP = 40;

const MODE_BUTTON_DEFS: { id: MultiplayerMenuButtonId; label: string }[] = [
  { id: 'local', label: 'Local Multiplayer' },
  { id: 'internet', label: 'Internet Multiplayer' },
];

export function computeMultiplayerMenuLayout(rawViewport: Viewport, insets: SafeAreaInsets): MultiplayerMenuLayout {
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

  const buttons: MultiplayerMenuButtonLayout[] = MODE_BUTTON_DEFS.map((def, i) => ({
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
