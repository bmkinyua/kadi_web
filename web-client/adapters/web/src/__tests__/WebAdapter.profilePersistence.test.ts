import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

/**
 * ProfileScene persistence (Part B of the Profile task) -- same real,
 * disk-backed, two-independent-subprocess rigor as
 * WebAdapter.persistence.test.ts's Settings coverage (see that file's
 * own header for why a jsdom/happy-dom mock wouldn't actually prove
 * anything survives a reload, and why Node's --experimental-webstorage
 * flag is used instead of a polyfill). Not duplicated logic — this
 * file exercises the NEW getProfile()/saveProfile() pair added to
 * WebAdapter.ts for this task, via its own fixtures/write-profile-*.ts
 * / read-profile-*.ts scripts (mirroring, not reusing, the settings
 * ones, since they call different adapter methods against a different
 * storage key).
 */

const FIXTURES_DIR = fileURLToPath(new URL('./fixtures/', import.meta.url));

function runFixture(script: string, storageFile: string): unknown {
  const stdout = execFileSync(
    process.execPath,
    ['--experimental-webstorage', `--localstorage-file=${storageFile}`, '--import', 'tsx', join(FIXTURES_DIR, script)],
    { encoding: 'utf-8' },
  );
  const line = stdout
    .trim()
    .split('\n')
    .find((l) => l.startsWith('RESULT:'));
  if (!line) throw new Error(`fixture ${script} produced no RESULT line. Full stdout:\n${stdout}`);
  return JSON.parse(line.slice('RESULT:'.length));
}

describe('WebAdapter profile persistence (real subprocess, disk-backed localStorage)', () => {
  let dir: string;
  let storageFile: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'kadi-profile-persist-'));
    storageFile = join(dir, 'localstorage.db');
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('round-trips a full profile object (stats/badges/cosmetics) across two independent process runs', () => {
    const written = runFixture('write-profile-once.ts', storageFile);
    const readBack = runFixture('read-profile-once.ts', storageFile);
    expect(readBack).toEqual(written);
  });

  it('getProfile() returns null (not a throw, not stale defaults) when nothing was ever saved', () => {
    const result = runFixture('read-profile-once.ts', storageFile);
    expect(result).toBeNull();
  });

  it('getProfile() returns null on corrupt stored JSON', () => {
    const result = runFixture('read-profile-after-corrupt-write.ts', storageFile);
    expect(result).toBeNull();
  });

  it('a later equip/save overwrites the earlier one, and the newest value is what persists', () => {
    runFixture('write-profile-once.ts', storageFile);
    const secondWrite = runFixture('write-profile-different.ts', storageFile);
    const readBack = runFixture('read-profile-once.ts', storageFile);
    expect(readBack).toEqual(secondWrite);
  });

  it('badges and equipped cosmetics both survive the round trip intact', () => {
    runFixture('write-profile-once.ts', storageFile);
    const readBack = runFixture('read-profile-once.ts', storageFile) as {
      badges: Record<string, string>;
      cosmetics: { equipped_card_back: string };
    };
    expect(readBack.badges.finish_question_chain).toBe('2026-02-02T00:00:00Z');
    expect(readBack.cosmetics.equipped_card_back).toBe('crosshatch');
  });

  it('Settings and Profile persist independently -- saving/reading one never touches the other\'s storage key', () => {
    const result = runFixture('write-both-settings-and-profile.ts', storageFile) as {
      settings: { turnTimerSecs: number };
      profile: { cosmetics: { equipped_card_back: string } };
    };
    expect(result.settings.turnTimerSecs).toBe(45);
    expect(result.profile.cosmetics.equipped_card_back).toBe('crosshatch');
  });
});
