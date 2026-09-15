/**
 * KADI web-client — safe-area handling (Part D).
 *
 * `PlatformAdapter.getSafeAreaInsets()` has been defined since the
 * first pass (see adapter-interface/src/PlatformAdapter.ts) but
 * nothing has ever read it. This module is what reads it: it turns a
 * raw viewport + insets into the "content rect" every scene should
 * lay content out inside, so host-platform chrome (Discord's own UI
 * around the iframe, Telegram's BottomSheet drag handle, a phone's
 * notch/home-indicator) never overlaps game UI.
 *
 * Pure and framework-agnostic, like scale.ts — see __tests__ for
 * direct tests of the arithmetic.
 */
import type { SafeAreaInsets } from '@kadi/adapter-interface';
import type { Viewport } from './scale.js';

export interface ContentRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The usable rectangle inside `viewport` once `insets` are excluded.
 * x/y are the top-left corner content should start from; width/height
 * are what's left to lay elements out in. */
export function getSafeContentRect(viewport: Viewport, insets: SafeAreaInsets): ContentRect {
  const width = Math.max(0, viewport.width - insets.left - insets.right);
  const height = Math.max(0, viewport.height - insets.top - insets.bottom);
  return {
    x: insets.left,
    y: insets.top,
    width,
    height,
  };
}
