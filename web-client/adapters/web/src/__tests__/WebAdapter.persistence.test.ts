import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

/**
 * SettingsScene persistence (Part C of the Settings task) -- "confirm
 * settings actually persist across a page reload (real test, not
 * assumed)".
 *
 * A jsdom/happy-dom localStorage mock would only prove our own code
 * reads back whatever it just wrote IN THE SAME PROCESS -- it can't
 * catch a bug where persistence looks fine because nothing ever
 * actually left memory. A real page reload is a NEW JS runtime with
 * no shared memory, re-reading from disk. The closest thing to that
 * outside an actual browser is Node's own (experimental, but real --
 * not a polyfill) Web Storage implementation, backed by an actual
 * file via --experimental-webstorage --localstorage-file=<path>: two
 * independent `node` process invocations, sharing only that file,
 * IS two independent runtimes reading real persisted state -- same
 * "spawn the real thing as a subprocess" testing philosophy
 * packages/client-core's own integration tests already use for the
 * real Python server, applied here to a real browser API instead.
 *
 * Each subprocess below runs one of the two tiny scripts in
 * ./fixtures/ (write-once.ts / read-once.ts), which do nothing but
 * import the REAL WebAdapter.ts and call saveSettings()/getSettings()
 * -- no test-only stand-in of the adapter itself.
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

describe('WebAdapter settings persistence (real subprocess, disk-backed localStorage)', () => {
  let dir: string;
  let storageFile: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'kadi-settings-persist-'));
    storageFile = join(dir, 'localstorage.db');
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('round-trips a full settings object across two independent process runs', () => {
    const written = runFixture('write-once.ts', storageFile);
    const readBack = runFixture('read-once.ts', storageFile);
    expect(readBack).toEqual(written);
  });

  it('getSettings() returns null (not a throw, not stale defaults) when nothing was ever saved', () => {
    const result = runFixture('read-once.ts', storageFile);
    expect(result).toBeNull();
  });

  it('getSettings() returns null on corrupt stored JSON, matching the settings_store.py load-failure fallback', () => {
    const result = runFixture('read-after-corrupt-write.ts', storageFile);
    expect(result).toBeNull();
  });

  it('a second write in a later "session" overwrites the first, and the newest value is what persists', () => {
    runFixture('write-once.ts', storageFile);
    const secondWrite = runFixture('write-different.ts', storageFile);
    const readBack = runFixture('read-once.ts', storageFile);
    expect(readBack).toEqual(secondWrite);
  });
});
