/**
 * KADI web-client — MainMenuScene's layout, as pure data.
 *
 * Same discipline as LobbyLayout.ts (see that file's own docstring):
 * framework-agnostic, unit-testable without Phaser, and the one call
 * site MainMenuScene.ts goes through for every position/size.
 *
 * SCOPE (plan §9, Feature Parity Tracking): the PC entry point
 * (scenes.py's MainMenuScene) offers Continue Game / Play vs AI /
 * Multiplayer / How to Play / Settings / Chuo / Profile / Quit. This
 * web port now covers five of those eight rows:
 *
 * - "Play" — the only ENABLED button. Routes to ModeSelectScene
 *   (see MainMenuScene.ts), which itself only offers the two modes
 *   that exist or are planned for web (vs AI, Internet Multiplayer;
 *   LAN is permanently out per §9).
 * - "How to Play" — ENABLED as of this pass, routing to RulesScene
 *   (see MainMenuScene.ts). §9's Feature Parity Tracking row for this
 *   moves from "planned" to "done" alongside this change.
 * - "Settings" — ENABLED as of the Settings task, routing to
 *   SettingsScene (see MainMenuScene.ts and layout/SettingsLayout.ts
 *   for the full 8-card port). §9's row for this moves from
 *   "planned" to "done" alongside this change.
 * - "Profile" — ENABLED as of the Profile task, routing to
 *   ProfileScene (see MainMenuScene.ts and layout/ProfileLayout.ts).
 *   §9's row for this moves from "coming soon" to "done" alongside
 *   this change.
 * - "Continue Game" and "Quit" are DROPPED, not disabled: "Continue"
 *   depends on save_manager's local-save-file concept, which has no
 *   web equivalent yet and isn't tracked in §9 as a planned item, and
 *   "Quit" has no web equivalent at all (closing the tab already does
 *   that) — see MainMenuScene.ts for the same reasoning restated at
 *   the call site.
 * - "Chuo" (MSOMI AI-model training) — ENABLED as of this pass,
 *   routing to ChuoScene (see MainMenuScene.ts and
 *   layout/ChuoLayout.ts for the four-tab port). §9's row for this
 *   moves from "in scope, deferred" to "done" alongside this change.
 *   (An earlier version of this comment said Chuo was dropped/out of
 *   scope entirely — that was stale relative to §9, which had already
 *   recorded it as in-scope-but-deferred; fixed here rather than left
 *   to drift further now that it's actually shipped.)
 */
import { type Viewport, computeLayoutScale, enforceMinTouchTarget, fontPx } from './scale.js';
import { type ContentRect, getSafeContentRect } from './safeArea.js';
import type { TextLayout } from './LobbyLayout.js';
import type { SafeAreaInsets } from '@kadi/adapter-interface';

export type MainMenuButtonId = 'play' | 'profile' | 'settings' | 'howToPlay' | 'chuo';

export interface MainMenuButtonLayout {
  id: MainMenuButtonId;
  label: string;
  enabled: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MainMenuLayout {
  scale: number;
  contentRect: ContentRect;
  title: TextLayout;
  subtitle: TextLayout;
  buttons: MainMenuButtonLayout[];
}

const BASE_TITLE_Y = 96;
const BASE_SUBTITLE_Y = 136;
const BASE_BUTTON_WIDTH = 220;
const BASE_BUTTON_HEIGHT = 44;
const BASE_BUTTON_GAP = 16;
const BASE_BUTTONS_START_Y = 210;

const BUTTON_DEFS: { id: MainMenuButtonId; label: string; enabled: boolean }[] = [
  { id: 'play', label: 'Play', enabled: true },
  { id: 'profile', label: 'Profile', enabled: true },
  { id: 'settings', label: 'Settings', enabled: true },
  { id: 'howToPlay', label: 'How to Play', enabled: true },
  { id: 'chuo', label: 'Chuo', enabled: true },
];

export function computeMainMenuLayout(rawViewport: Viewport, insets: SafeAreaInsets): MainMenuLayout {
  const scale = computeLayoutScale(rawViewport);
  const contentRect = getSafeContentRect(rawViewport, insets);
  const centerX = contentRect.x + contentRect.width / 2;

  const title: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_TITLE_Y * scale,
    fontPx: fontPx('ui_large', scale),
  };
  const subtitle: TextLayout = {
    x: centerX,
    y: contentRect.y + BASE_SUBTITLE_Y * scale,
    fontPx: fontPx('ui_normal', scale),
  };

  const buttonSize = enforceMinTouchTarget({
    width: BASE_BUTTON_WIDTH * scale,
    height: BASE_BUTTON_HEIGHT * scale,
  });
  const gap = BASE_BUTTON_GAP * scale;
  const step = buttonSize.height + gap;
  const startY = contentRect.y + BASE_BUTTONS_START_Y * scale;

  const buttons: MainMenuButtonLayout[] = BUTTON_DEFS.map((def, i) => ({
    id: def.id,
    label: def.label,
    enabled: def.enabled,
    x: centerX - buttonSize.width / 2,
    y: startY + i * step,
    width: buttonSize.width,
    height: buttonSize.height,
  }));

  return { scale, contentRect, title, subtitle, buttons };
}
