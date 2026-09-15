/**
 * KADI - MsomiStore backend for browsers without the File System
 * Access API (Firefox, Safari, older Chromium). See MsomiStore.ts's
 * own header for the two-backend decision this implements one half
 * of, and FileSystemAccessMsomiStore.ts for the other half.
 *
 * STORAGE: a small IndexedDB database (`kadi-msomi`) with two object
 * stores — `logs` (keyed by an internally-generated id, so two
 * imports that happen to share a filename never collide) and `models`
 * (keyed by filename, mirroring core/msomi_trainer.py's own
 * filename-keyed msomi_models/ directory). See ./idb.ts for the small
 * hand-rolled promise wrapper this is built on.
 *
 * IMPORT MECHANISM: `importLogFiles()` is split into a DOM-dependent
 * half (`pickFiles`, defaulting to a hidden `<input type="file"
 * multiple accept=".jsonl">` — the only cross-browser way to open a
 * real OS file-open dialog without the File System Access API) and a
 * DOM-independent half (`storeLogFile`, the actual "copy these bytes
 * into IndexedDB" logic) — the latter is what __tests__/
 * IndexedDbMsomiStore.test.ts exercises directly, since driving a real
 * native file-picker dialog isn't something any headless test
 * environment can do (see the handoff prompt's own "no live browser
 * available here" note). `pickFiles` is constructor-injectable for
 * exactly that reason.
 */
import type { MsomiLogFileMeta, MsomiStore, MsomiTrainedModel } from '@kadi/adapter-interface';
import { LOGS_STORE, MODELS_STORE, idbDelete, idbGet, idbGetAll, idbPut, openMsomiDb } from './idb.js';

interface StoredLogFile extends MsomiLogFileMeta {
  content: string;
}

interface StoredModel {
  filename: string;
  model: MsomiTrainedModel;
  savedAt: number;
}

function generateId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `log-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Opens a hidden native file-picker via a classic `<input
 * type="file">` and resolves with whatever the player selected (an
 * empty array on cancel — `input.oncancel`/a window-focus fallback
 * covers browsers that fire neither `change` nor `cancel` reliably on
 * an empty selection). This is the "no real FSA picker" experience
 * this file's header refers to: a real OS dialog still opens, but
 * nothing here retains a reusable handle to what was picked — see
 * MsomiStore.ts's `importLogFiles()` docstring on why that's a
 * deliberate scope cut, not an oversight. */
function defaultPickFiles(): Promise<File[]> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      resolve([]);
      return;
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.jsonl,application/x-ndjson,text/plain';
    input.style.display = 'none';

    let settled = false;
    const finish = (files: File[]) => {
      if (settled) return;
      settled = true;
      input.remove();
      window.removeEventListener('focus', onFocus);
      resolve(files);
    };
    input.addEventListener('change', () => {
      finish(input.files ? Array.from(input.files) : []);
    });
    // No 'cancel' event exists on <input type=file> in every browser
    // — the window regaining focus after the dialog closes with
    // nothing selected is the standard fallback signal.
    const onFocus = () => {
      setTimeout(() => finish(input.files && input.files.length > 0 ? Array.from(input.files) : []), 300);
    };
    window.addEventListener('focus', onFocus);

    document.body.appendChild(input);
    input.click();
  });
}

export class IndexedDbMsomiStore implements MsomiStore {
  readonly backendKind = 'indexeddb' as const;

  constructor(
    private readonly idbFactory: IDBFactory = typeof indexedDB !== 'undefined' ? indexedDB : (undefined as never),
    private readonly pickFiles: () => Promise<File[]> = defaultPickFiles,
  ) {}

  private db(): Promise<IDBDatabase> {
    return openMsomiDb(this.idbFactory);
  }

  async listLogFiles(): Promise<MsomiLogFileMeta[]> {
    const db = await this.db();
    const rows = await idbGetAll<StoredLogFile>(db, LOGS_STORE);
    return rows
      .map(({ id, name, size, importedAt }) => ({ id, name, size, importedAt }))
      .sort((a, b) => b.importedAt - a.importedAt);
  }

  async readLogFile(id: string): Promise<string> {
    const db = await this.db();
    const row = await idbGet<StoredLogFile>(db, LOGS_STORE, id);
    if (!row) throw new Error(`No log file with id "${id}" in this store.`);
    return row.content;
  }

  /** The DOM-independent half of importLogFiles() — see this file's
   * header. Public so tests (and importLogFiles() itself) can call it
   * directly with known bytes. */
  async storeLogFile(name: string, content: string): Promise<MsomiLogFileMeta> {
    const db = await this.db();
    const meta: StoredLogFile = {
      id: generateId(),
      name,
      size: new TextEncoder().encode(content).length,
      importedAt: Date.now(),
      content,
    };
    await idbPut(db, LOGS_STORE, meta);
    const { id, size, importedAt } = meta;
    return { id, name, size, importedAt };
  }

  async importLogFiles(): Promise<MsomiLogFileMeta[]> {
    const files = await this.pickFiles();
    const metas: MsomiLogFileMeta[] = [];
    for (const file of files) {
      const content = await file.text();
      metas.push(await this.storeLogFile(file.name, content));
    }
    return metas;
  }

  async listModels(): Promise<string[]> {
    const db = await this.db();
    const rows = await idbGetAll<StoredModel>(db, MODELS_STORE);
    return rows.sort((a, b) => b.savedAt - a.savedAt).map((r) => r.filename);
  }

  async saveModel(filename: string, model: MsomiTrainedModel): Promise<void> {
    const finalName = filename.endsWith('.json') ? filename : `${filename}.json`;
    const db = await this.db();
    const record: StoredModel = { filename: finalName, model, savedAt: Date.now() };
    await idbPut(db, MODELS_STORE, record);
  }

  async loadModel(filename: string): Promise<MsomiTrainedModel> {
    const db = await this.db();
    const row = await idbGet<StoredModel>(db, MODELS_STORE, filename);
    if (!row) throw new Error(`No saved model named "${filename}".`);
    return row.model;
  }

  async deleteModel(filename: string): Promise<void> {
    const db = await this.db();
    await idbDelete(db, MODELS_STORE, filename);
  }
}
