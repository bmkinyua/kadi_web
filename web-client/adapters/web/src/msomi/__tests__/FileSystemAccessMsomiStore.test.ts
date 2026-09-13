/**
 * Exercises FileSystemAccessMsomiStore's actual logic against small
 * in-memory fakes implementing FSDirectoryHandleLike/FSFileHandleLike
 * — no real browser File System Access API is available in this
 * environment (see that file's own header). These fakes implement
 * exactly the narrow surface the store calls, not the full spec.
 */
import { IDBFactory } from 'fake-indexeddb';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  FileSystemAccessMsomiStore,
  isFileSystemAccessSupported,
  type FSDirectoryHandleLike,
  type FSFileHandleLike,
} from '../FileSystemAccessMsomiStore.js';
import type { MsomiTrainedModel } from '@kadi/adapter-interface';

// ── Minimal in-memory fake filesystem ──────────────────────────────

class FakeFileHandle implements FSFileHandleLike {
  readonly kind = 'file' as const;
  constructor(
    public name: string,
    public content: string = '',
  ) {}
  async getFile() {
    const content = this.content;
    return { text: async () => content, size: new TextEncoder().encode(content).length };
  }
  async createWritable() {
    const self = this;
    let buffer = '';
    return {
      write: async (data: string) => {
        buffer += data;
      },
      close: async () => {
        self.content = buffer;
      },
    };
  }
}

class FakeDirectoryHandle implements FSDirectoryHandleLike {
  readonly kind = 'directory' as const;
  entries = new Map<string, FakeFileHandle | FakeDirectoryHandle>();
  permission: 'granted' | 'denied' | 'prompt' = 'granted';

  constructor(public name: string) {}

  async getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FSDirectoryHandleLike> {
    const existing = this.entries.get(name);
    if (existing && existing.kind === 'directory') return existing;
    if (!options?.create) throw new Error(`Directory "${name}" not found`);
    const created = new FakeDirectoryHandle(name);
    this.entries.set(name, created);
    return created;
  }

  async getFileHandle(name: string, options?: { create?: boolean }): Promise<FSFileHandleLike> {
    const existing = this.entries.get(name);
    if (existing && existing.kind === 'file') return existing;
    if (!options?.create) throw new Error(`File "${name}" not found`);
    const created = new FakeFileHandle(name);
    this.entries.set(name, created);
    return created;
  }

  async removeEntry(name: string): Promise<void> {
    if (!this.entries.has(name)) throw new Error(`"${name}" not found`);
    this.entries.delete(name);
  }

  async *values(): AsyncIterableIterator<FSFileHandleLike | FSDirectoryHandleLike> {
    for (const entry of this.entries.values()) yield entry;
  }

  async requestPermission(): Promise<'granted' | 'denied' | 'prompt'> {
    return this.permission;
  }

  async queryPermission(): Promise<'granted' | 'denied' | 'prompt'> {
    return this.permission;
  }
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

function freshStore(root: FakeDirectoryHandle, openFilePicker?: () => Promise<FSFileHandleLike[]>) {
  return new FileSystemAccessMsomiStore(
    new IDBFactory() as unknown as globalThis.IDBFactory,
    async () => root,
    openFilePicker ?? (async () => []),
  );
}

describe('isFileSystemAccessSupported', () => {
  it('is true when showDirectoryPicker exists on the given scope', () => {
    expect(isFileSystemAccessSupported({ showDirectoryPicker: () => {} } as never)).toBe(true);
  });
  it('is false when it does not', () => {
    expect(isFileSystemAccessSupported({} as never)).toBe(false);
  });
});

describe('FileSystemAccessMsomiStore', () => {
  let root: FakeDirectoryHandle;

  beforeEach(() => {
    root = new FakeDirectoryHandle('root');
  });

  it('reports its backend kind', () => {
    expect(freshStore(root).backendKind).toBe('file-system-access');
  });

  it('creates logs/ and msomi_models/ subdirectories under the chosen root, matching the PC folder names', async () => {
    const store = freshStore(root);
    await store.listLogFiles();
    await store.listModels();
    expect([...root.entries.keys()].sort()).toEqual(['logs', 'msomi_models']);
  });

  it('starts with no log files or models', async () => {
    const store = freshStore(root);
    expect(await store.listLogFiles()).toEqual([]);
    expect(await store.listModels()).toEqual([]);
  });

  it('only prompts for a directory once, then reuses the same handle for subsequent calls', async () => {
    let promptCount = 0;
    const store = new FileSystemAccessMsomiStore(
      new IDBFactory() as unknown as globalThis.IDBFactory,
      async () => {
        promptCount += 1;
        return root;
      },
      async () => [],
    );
    await store.listLogFiles();
    await store.listModels();
    await store.listLogFiles();
    expect(promptCount).toBe(1);
  });

  it('saves and loads a model round-trip, appending .json if missing', async () => {
    const store = freshStore(root);
    await store.saveModel('my-model', sampleModel);
    expect(await store.listModels()).toEqual(['my-model.json']);
    expect(await store.loadModel('my-model.json')).toEqual(sampleModel);
  });

  it('rejects loading a model that does not exist', async () => {
    const store = freshStore(root);
    await expect(store.loadModel('missing.json')).rejects.toThrow(/No saved model/);
  });

  it('deletes a saved model, matching the no-op-if-missing contract on a second delete', async () => {
    const store = freshStore(root);
    await store.saveModel('to-delete', sampleModel);
    await store.deleteModel('to-delete.json');
    expect(await store.listModels()).toEqual([]);
    await expect(store.deleteModel('to-delete.json')).resolves.toBeUndefined();
  });

  it('reads back exact log-file content written directly into the fake logs/ directory', async () => {
    const store = freshStore(root);
    const logsDir = (await root.getDirectoryHandle('logs', { create: true })) as FakeDirectoryHandle;
    await logsDir.getFileHandle('LOG_1.jsonl', { create: true });
    const handle = logsDir.entries.get('LOG_1.jsonl') as FakeFileHandle;
    handle.content = '{"schema_version":1}\n';

    const listed = await store.listLogFiles();
    expect(listed).toHaveLength(1);
    expect(listed[0].name).toBe('LOG_1.jsonl');
    expect(await store.readLogFile('LOG_1.jsonl')).toBe('{"schema_version":1}\n');
  });

  it('ignores non-.jsonl entries in the logs directory', async () => {
    const store = freshStore(root);
    const logsDir = (await root.getDirectoryHandle('logs', { create: true })) as FakeDirectoryHandle;
    await logsDir.getFileHandle('README.txt', { create: true });
    await logsDir.getFileHandle('LOG_1.jsonl', { create: true });
    const listed = await store.listLogFiles();
    expect(listed.map((l) => l.name)).toEqual(['LOG_1.jsonl']);
  });

  it('rejects reading a log file that does not exist', async () => {
    const store = freshStore(root);
    await expect(store.readLogFile('nope.jsonl')).rejects.toThrow(/No log file/);
  });

  it('importLogFiles() copies picked files into the logs/ subdirectory and reports them', async () => {
    const pickedFile = new FakeFileHandle('external.jsonl', '{"picked":true}\n');
    const store = freshStore(root, async () => [pickedFile]);

    const imported = await store.importLogFiles();
    expect(imported).toHaveLength(1);
    expect(imported[0].name).toBe('external.jsonl');

    // Confirm it's now a real copy sitting in the store's own logs/,
    // independent of the original fake handle.
    expect(await store.readLogFile('external.jsonl')).toBe('{"picked":true}\n');
    const listed = await store.listLogFiles();
    expect(listed.map((l) => l.name)).toEqual(['external.jsonl']);
  });

  it('importLogFiles() returns an empty array when the picker throws (cancel)', async () => {
    const store = freshStore(root, async () => {
      throw new DOMException('The user aborted a request.', 'AbortError');
    });
    expect(await store.importLogFiles()).toEqual([]);
  });

  it('requests permission via requestPermission() when queryPermission reports something other than granted', async () => {
    root.permission = 'prompt';
    let requestCalls = 0;
    root.requestPermission = async () => {
      requestCalls += 1;
      root.permission = 'granted'; // simulate the player clicking "Allow"
      return 'granted';
    };
    const store = freshStore(root);
    await store.listLogFiles();
    expect(requestCalls).toBeGreaterThan(0);
  });

  it('throws when permission is denied', async () => {
    root.permission = 'denied';
    const store = freshStore(root);
    await expect(store.listLogFiles()).rejects.toThrow(/[Pp]ermission/);
  });
});
