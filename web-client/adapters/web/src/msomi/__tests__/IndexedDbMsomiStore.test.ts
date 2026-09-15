/**
 * Exercises IndexedDbMsomiStore against a fresh in-memory
 * `fake-indexeddb` IDBFactory per test (real IndexedDB semantics, no
 * browser needed — this environment has no live browser at all, see
 * the handoff prompt's own note). `storeLogFile()` is used directly
 * rather than `importLogFiles()` for log-import tests, since
 * `importLogFiles()`'s own job is just driving a real `<input
 * type="file">` dialog — see IndexedDbMsomiStore.ts's header for why
 * that half is deliberately excluded from what's tested here.
 */
import { IDBFactory } from 'fake-indexeddb';
import { beforeEach, describe, expect, it } from 'vitest';
import { IndexedDbMsomiStore } from '../IndexedDbMsomiStore.js';
import type { MsomiTrainedModel } from '@kadi/adapter-interface';

function freshStore(): IndexedDbMsomiStore {
  // A brand-new IDBFactory per test -- total isolation, no need to
  // delete a shared database between tests.
  return new IndexedDbMsomiStore(new IDBFactory() as unknown as globalThis.IDBFactory, async () => []);
}

const sampleModel: MsomiTrainedModel = {
  schema_version: 1,
  decision_schema_version: 1,
  model_type: 'conditional_logit',
  features: ['cards_played'],
  weights: { cards_played: 1.5 },
  training: {
    num_decisions: 10,
    num_human_decisions: 5,
    num_ai_decisions: 5,
    human_weight: 2,
    iterations: 500,
    learning_rate: 0.3,
    train_agreement: 0.9,
    train_agreement_human_only: 0.8,
  },
};

describe('IndexedDbMsomiStore', () => {
  let store: IndexedDbMsomiStore;

  beforeEach(() => {
    store = freshStore();
  });

  it('reports its backend kind', () => {
    expect(store.backendKind).toBe('indexeddb');
  });

  it('starts with no log files or models', async () => {
    expect(await store.listLogFiles()).toEqual([]);
    expect(await store.listModels()).toEqual([]);
  });

  it('stores a log file and lists it back with correct metadata', async () => {
    const content = '{"schema_version":1}\n';
    const meta = await store.storeLogFile('LOG_1.jsonl', content);
    expect(meta.name).toBe('LOG_1.jsonl');
    expect(meta.size).toBe(new TextEncoder().encode(content).length);

    const listed = await store.listLogFiles();
    expect(listed).toHaveLength(1);
    expect(listed[0]).toEqual(meta);
  });

  it('two imports with the same filename get distinct ids and both survive', async () => {
    const a = await store.storeLogFile('dup.jsonl', 'a');
    const b = await store.storeLogFile('dup.jsonl', 'b');
    expect(a.id).not.toBe(b.id);
    const listed = await store.listLogFiles();
    expect(listed).toHaveLength(2);
  });

  it('reads back the exact content of a stored log file by id', async () => {
    const meta = await store.storeLogFile('LOG_1.jsonl', 'hello world');
    expect(await store.readLogFile(meta.id)).toBe('hello world');
  });

  it('rejects reading a log file id that does not exist', async () => {
    await expect(store.readLogFile('nonexistent')).rejects.toThrow(/No log file/);
  });

  it('lists log files most-recently-imported first', async () => {
    const first = await store.storeLogFile('first.jsonl', '1');
    await new Promise((r) => setTimeout(r, 5));
    const second = await store.storeLogFile('second.jsonl', '2');
    const listed = await store.listLogFiles();
    expect(listed.map((l) => l.id)).toEqual([second.id, first.id]);
  });

  it('saves and loads a model round-trip, appending .json if missing', async () => {
    await store.saveModel('my-model', sampleModel);
    expect(await store.listModels()).toEqual(['my-model.json']);
    const loaded = await store.loadModel('my-model.json');
    expect(loaded).toEqual(sampleModel);
  });

  it('does not double-append .json if already present', async () => {
    await store.saveModel('already-named.json', sampleModel);
    expect(await store.listModels()).toEqual(['already-named.json']);
  });

  it('rejects loading a model that does not exist', async () => {
    await expect(store.loadModel('missing.json')).rejects.toThrow(/No saved model/);
  });

  it('deletes a saved model', async () => {
    await store.saveModel('to-delete', sampleModel);
    expect(await store.listModels()).toEqual(['to-delete.json']);
    await store.deleteModel('to-delete.json');
    expect(await store.listModels()).toEqual([]);
  });

  it('deleting a model that does not exist is a no-op, not a rejection', async () => {
    await expect(store.deleteModel('never-existed.json')).resolves.toBeUndefined();
  });

  it('lists models most-recently-saved first', async () => {
    await store.saveModel('older', sampleModel);
    await new Promise((r) => setTimeout(r, 5));
    await store.saveModel('newer', sampleModel);
    expect(await store.listModels()).toEqual(['newer.json', 'older.json']);
  });

  it('importLogFiles() stores whatever the injected picker returns', async () => {
    const fakeFile = new File(['{"a":1}\n'], 'picked.jsonl', { type: 'application/x-ndjson' });
    const injected = new IndexedDbMsomiStore(new IDBFactory() as unknown as globalThis.IDBFactory, async () => [
      fakeFile,
    ]);
    const imported = await injected.importLogFiles();
    expect(imported).toHaveLength(1);
    expect(imported[0].name).toBe('picked.jsonl');
    expect(await injected.readLogFile(imported[0].id)).toBe('{"a":1}\n');
  });

  it('importLogFiles() returns an empty array when the picker yields nothing (cancel)', async () => {
    const imported = await store.importLogFiles();
    expect(imported).toEqual([]);
  });
});
