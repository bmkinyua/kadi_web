import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * GameTableScene.ts's Part D wiring for the new 'game_summary'
 * message (§9's Profile Part 5 disclosure) -- verified at the same
 * source-level regression grep as gameTableCosmeticsWiring.test.ts
 * uses for the cosmetics wiring, and for the identical reason stated
 * in that file's own header: GameTableScene extends Phaser.Scene and
 * this package has no canvas/WebGL test environment to actually mount
 * one. The real end-to-end behavior (server sends game_summary with
 * correct values once at GAME_OVER) is covered by
 * tests/test_game_summary.py on the Python side (real server, real
 * loopback connection, a genuine finished game); applyGameSummary()'s
 * own badge/counter logic is covered by checkBadgesAfterGame.test.ts.
 * This file's job is only the wiring BETWEEN those two: that
 * GameTableScene actually listens for the message and actually calls
 * into the real profile read/apply/save path rather than silently
 * dropping it.
 */

const GAME_TABLE_SCENE_PATH = fileURLToPath(new URL('../GameTableScene.ts', import.meta.url));
const source = readFileSync(GAME_TABLE_SCENE_PATH, 'utf-8');

describe('GameTableScene.ts game_summary wiring (source-level, see this file\'s own header)', () => {
  it('imports applyGameSummary from profileData.ts', () => {
    expect(source).toMatch(/import\s*\{[^}]*applyGameSummary[^}]*\}\s*from\s*'\.\/profileData\.js'/s);
  });

  it("onServerMessage dispatches msg.type === 'game_summary' to a handler", () => {
    expect(source).toMatch(/msg\.type === 'game_summary'/);
  });

  it('the game_summary handler re-fetches the current profile rather than reusing a stale snapshot', () => {
    const start = source.indexOf('private onGameSummary(');
    expect(start).toBeGreaterThan(-1);
    const end = source.indexOf('\n  private ', start + 20);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('this.adapter.getProfile()');
  });

  it('the game_summary handler applies the message via applyGameSummary and persists via adapter.saveProfile', () => {
    const start = source.indexOf('private onGameSummary(');
    const end = source.indexOf('\n  private ', start + 20);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('applyGameSummary(profile, msg)');
    expect(body).toContain('this.adapter.saveProfile(');
  });

  it('the game_summary handler is guarded against ever running twice for the same room', () => {
    const start = source.indexOf('private onGameSummary(');
    const end = source.indexOf('\n  private ', start + 20);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('this.gameSummaryApplied');
  });

  it('the guard flag is reset in init() so a later game in the same scene instance can apply its own summary', () => {
    const start = source.indexOf('init(data:');
    const end = source.indexOf('\n  create(', start);
    const body = source.slice(start, end === -1 ? undefined : end);
    expect(body).toContain('this.gameSummaryApplied = false');
  });

  it('the win screen surfaces newly-earned badges from the applied summary, not a hardcoded/empty list', () => {
    const start = source.indexOf('private renderWinScreen(');
    expect(start).toBeGreaterThan(-1);
    const body = source.slice(start);
    expect(body).toContain('this.newlyEarnedBadgeIds');
  });
});
