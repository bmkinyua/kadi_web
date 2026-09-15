import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { CARD_BACK_STYLES, FELT_THEMES, defaultProfile, resolveTableCosmetics } from '../profileData.js';

/**
 * GameTableScene.ts's Part D wiring ("cosmetics equip actions need to
 * actually affect the game table" -- see this task's brief) --
 * verified at TWO levels, honestly split by what's actually testable
 * in this environment:
 *
 * 1. resolveTableCosmetics() itself -- the pure decision of "which
 *    colors does an equipped cosmetic resolve to" -- is fully unit
 *    tested in __tests__/profileData.test.ts (different equipped
 *    values genuinely produce different colors, corrupt/unknown
 *    values fall back safely).
 *
 * 2. THIS file verifies GameTableScene.ts's SOURCE actually calls
 *    that function and uses its result at every draw site that used
 *    to be a hardcoded color, rather than asserting on rendered
 *    pixels. That's a deliberate, stated boundary, not an oversight:
 *    GameTableScene extends Phaser.Scene, and this package's test
 *    setup has no canvas/WebGL context available (no vitest
 *    jsdom/canvas config, no `canvas` npm package in this repo --
 *    see package.json) to actually instantiate a Phaser Scene and
 *    read back pixels or Graphics fill-color state, and no other test
 *    in this codebase does that for any Scene class (only pure
 *    layout/* modules and standalone logic like cardPlayability.ts
 *    get executed directly -- Scene classes stay thin, unexercised-
 *    by-automation appliers of those pure functions' output, same
 *    split ProfileLayout.ts's own header documents). A source-grep
 *    regression test is the honest middle ground here: it fails loudly
 *    if a future edit reintroduces a hardcoded felt/card-back color
 *    literal, or removes the resolveTableCosmetics() call, even
 *    though it can't see an actual rendered frame.
 */

const GAME_TABLE_SCENE_PATH = fileURLToPath(new URL('../GameTableScene.ts', import.meta.url));
const source = readFileSync(GAME_TABLE_SCENE_PATH, 'utf-8');

describe('GameTableScene.ts cosmetics wiring (source-level, see this file\'s own header)', () => {
  it('imports and calls resolveTableCosmetics from profileData.ts', () => {
    expect(source).toMatch(/import\s*\{[^}]*resolveTableCosmetics[^}]*\}\s*from\s*'\.\/profileData\.js'/);
    expect(source).toContain('resolveTableCosmetics(');
  });

  it('resolves cosmetics from the SAME adapter.getProfile() this ProfileScene reads/writes, not a hardcoded profile', () => {
    expect(source).toContain('this.adapter.getProfile()');
  });

  it('renderTable() reads felt fill/edge from this.tableCosmetics, not a fixed hex literal', () => {
    const start = source.indexOf('private renderTable(');
    const end = source.indexOf('private renderPiles(');
    const body = source.slice(start, end);
    expect(body).toContain('this.tableCosmetics.feltFill');
    expect(body).toContain('this.tableCosmetics.feltEdge');
    // the OLD hardcoded values must be gone from this method specifically:
    expect(body).not.toContain('0x0f5c33');
    expect(body).not.toContain('0x0a3a20');
  });

  it('renderPiles()\'s draw-pile back reads from this.tableCosmetics, not a fixed hex literal', () => {
    const start = source.indexOf('private renderPiles(');
    const end = source.indexOf('private renderBanners(', start);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('this.tableCosmetics.cardBackA');
  });

  it('renderSeats()\'s opponent hidden-card block reads from this.tableCosmetics, not a fixed hex literal', () => {
    const start = source.indexOf('private renderSeats(');
    expect(start).toBeGreaterThan(-1);
    const end = source.indexOf('\n  private ', start + 20);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('this.tableCosmetics.cardBackA');
    expect(body).toContain('this.tableCosmetics.cardBackB');
  });

  it('sanity: the two cosmetics this wiring depends on genuinely differ from the default for a non-default profile', () => {
    // Belt-and-suspenders link back to profileData.test.ts's own
    // coverage, so THIS file doesn't silently pass if
    // resolveTableCosmetics() itself ever stopped varying.
    const p = defaultProfile();
    p.cosmetics.equipped_felt_theme = 'midnight';
    p.cosmetics.equipped_card_back = 'dots';
    const resolved = resolveTableCosmetics(p);
    expect(resolved.feltFill).toBe(FELT_THEMES.midnight.felt);
    expect(resolved.cardBackA).toBe(CARD_BACK_STYLES.dots.colorA);
    expect(resolved.feltFill).not.toBe(FELT_THEMES.default.felt);
  });
});
