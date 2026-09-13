/**
 * KADI - MsomiStore backend for browsers that support the File System
 * Access API (current Chromium-based browsers). See MsomiStore.ts's
 * own header for the two-backend decision, and IndexedDbMsomiStore.ts
 * for the fallback this mirrors the CONTRACT of but not the storage
 * mechanism.
 *
 * STORAGE: a single working directory the player grants access to
 * ONCE (`showDirectoryPicker()`), containing `logs/` and
 * `msomi_models/` subdirectories — deliberately the SAME two names
 * core/game_logger.py's `LOG_DIR_NAME` and core/msomi_trainer.py's
 * `MODELS_DIR_NAME` use, so a player who points this at their actual
 * PC KADI per-user data directory (see core/game_logger.py's
 * `_per_user_data_dir()`) gets the real desktop logs/models showing up
 * here with zero copying — genuinely reading the same files the
 * desktop client itself writes, not just files that merely look
 * similar. The chosen `FileSystemDirectoryHandle` is persisted (it's
 * structured-clone-serializable) in a tiny dedicated IndexedDB
 * key/value store (./idb.ts's own DB, a third object store scoped
 * just to this one handle) so the player isn't re-prompted on every
 * page load — subject to the browser's own permission model: a stale
 * handle's access is re-requested via `requestPermission()` before
 * every real read/write, per the spec's own re-grant flow.
 *
 * WHY NOT ALSO USE THIS FOR THE ONE-OFF "Import from device" PICK:
 * it is — `importLogFiles()` uses `showOpenFilePicker()` (this
 * backend's own real multi-select file dialog, unrestricted to the
 * working directory, mirroring `_browse_for_logs()`'s "anywhere on
 * the computer" scope) and copies the result into the working
 * directory's `logs/` subfolder, exactly like IndexedDbMsomiStore's
 * `importLogFiles()` copies into its object store — see MsomiStore.ts's
 * own docstring on why this is a copy-in on both backends, not a live
 * link.
 *
 * TESTABILITY: every FSA call this file makes goes through the small
 * `FileSystemAccessLike` surface below rather than the real
 * `window.showDirectoryPicker`/`showOpenFilePicker` directly, both
 * injectable via the constructor. No environment available while
 * writing this (see the handoff prompt's own "no live browser
 * available here" note) has a real File System Access API — Node has
 * none, and no headless-browser test runner is wired into this
 * codebase — so __tests__/FileSystemAccessMsomiStore.test.ts exercises
 * this file's actual logic (directory creation, read/write/list/
 * delete, permission-request calls, import-and-copy behavior) against
 * small in-memory FAKE handle objects implementing that same surface,
 * not the real browser API. See this file's own MANUAL BROWSER TEST
 * STEPS note (bottom) for what a person needs to click through once a
 * real browser is available, since that path genuinely can't be
 * exercised headlessly.
 */
import type { MsomiLogFileMeta, MsomiStore, MsomiTrainedModel } from '@kadi/adapter-interface';
import { FSA_HANDLE_STORE, idbGet, idbPut, openMsomiDb } from './idb.js';

const ROOT_HANDLE_KEY = 'root';
const LOGS_DIR_NAME = 'logs';
const MODELS_DIR_NAME = 'msomi_models';

/** The minimal subset of the real File System Access API this file
 * actually uses — real `FileSystemDirectoryHandle`/`FileSystemFileHandle`
 * objects satisfy this structurally with no adapter needed; tests
 * supply small in-memory fakes instead. Kept narrow deliberately, not
 * because the real API is bigger (it is), but so a fake only has to
 * implement exactly what's called here. */
export interface FSFileHandleLike {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<{ text(): Promise<string>; size: number }>;
  createWritable(): Promise<{ write(data: string): Promise<void>; close(): Promise<void> }>;
}

export interface FSDirectoryHandleLike {
  readonly kind: 'directory';
  readonly name: string;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FSDirectoryHandleLike>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FSFileHandleLike>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  values(): AsyncIterableIterator<FSFileHandleLike | FSDirectoryHandleLike>;
  requestPermission?(descriptor: { mode: 'readwrite' }): Promise<'granted' | 'denied' | 'prompt'>;
  queryPermission?(descriptor: { mode: 'readwrite' }): Promise<'granted' | 'denied' | 'prompt'>;
}

/** The (much smaller) surface used for the one-off "Import from
 * device" file-open dialog — separate from the directory-handle
 * surface above since it's a one-shot picker, not a persisted handle. */
export type ShowOpenFilePicker = (options: {
  multiple: boolean;
  types: { description: string; accept: Record<string, string[]> }[];
}) => Promise<FSFileHandleLike[]>;

export type ShowDirectoryPicker = () => Promise<FSDirectoryHandleLike>;

/** True when the current browser exposes the File System Access
 * directory-picker API — the feature-detection createMsomiStore.ts
 * gates its backend choice on. Deliberately checks `showDirectoryPicker`
 * specifically (not just `showOpenFilePicker`, which Safari also lacks
 * but some environments could theoretically add independently) since
 * this backend's persisted working directory depends on it. */
export function isFileSystemAccessSupported(scope: typeof globalThis = globalThis): boolean {
  return typeof (scope as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function';
}

async function ensurePermission(handle: FSDirectoryHandleLike): Promise<void> {
  if (!handle.queryPermission || !handle.requestPermission) return; // fakes may omit these
  const current = await handle.queryPermission({ mode: 'readwrite' });
  if (current === 'granted') return;
  const requested = await handle.requestPermission({ mode: 'readwrite' });
  if (requested !== 'granted') {
    throw new Error('Permission to the chosen folder was not granted.');
  }
}

export class FileSystemAccessMsomiStore implements MsomiStore {
  readonly backendKind = 'file-system-access' as const;

  private rootHandle: FSDirectoryHandleLike | null = null;

  constructor(
    private readonly idbFactory: IDBFactory = typeof indexedDB !== 'undefined' ? indexedDB : (undefined as never),
    private readonly showDirectoryPicker: ShowDirectoryPicker = (globalThis as unknown as {
      showDirectoryPicker: ShowDirectoryPicker;
    }).showDirectoryPicker,
    private readonly showOpenFilePicker: ShowOpenFilePicker = (globalThis as unknown as {
      showOpenFilePicker: ShowOpenFilePicker;
    }).showOpenFilePicker,
  ) {}

  /** Resolves the working directory, prompting the player to pick one
   * (and persisting the handle) only if none is saved yet or the saved
   * one no longer has permission — see this file's header. Every
   * public method below calls this first, so a fresh instance works
   * whether or not a handle was already persisted from a prior
   * session. */
  private async getRoot(): Promise<FSDirectoryHandleLike> {
    if (this.rootHandle) {
      await ensurePermission(this.rootHandle);
      return this.rootHandle;
    }
    const db = await openMsomiDb(this.idbFactory);
    const savedRecord = await idbGet<{ id: string; handle: FSDirectoryHandleLike }>(
      db,
      FSA_HANDLE_STORE,
      ROOT_HANDLE_KEY,
    );
    if (savedRecord) {
      await ensurePermission(savedRecord.handle);
      this.rootHandle = savedRecord.handle;
      return savedRecord.handle;
    }
    const picked = await this.showDirectoryPicker();
    await ensurePermission(picked);
    await idbPut(db, FSA_HANDLE_STORE, { id: ROOT_HANDLE_KEY, handle: picked }).catch(() => {
      // Best-effort persistence -- a handle that can't be structured-
      // cloned (shouldn't happen for a real browser handle; could for
      // a hand-built test fake) just means re-prompting next session,
      // not a functional failure this session.
    });
    this.rootHandle = picked;
    return picked;
  }

  private async logsDir(): Promise<FSDirectoryHandleLike> {
    const root = await this.getRoot();
    return root.getDirectoryHandle(LOGS_DIR_NAME, { create: true });
  }

  private async modelsDir(): Promise<FSDirectoryHandleLike> {
    const root = await this.getRoot();
    return root.getDirectoryHandle(MODELS_DIR_NAME, { create: true });
  }

  async listLogFiles(): Promise<MsomiLogFileMeta[]> {
    const dir = await this.logsDir();
    const metas: MsomiLogFileMeta[] = [];
    for await (const entry of dir.values()) {
      if (entry.kind !== 'file' || !entry.name.endsWith('.jsonl')) continue;
      const file = await entry.getFile();
      metas.push({ id: entry.name, name: entry.name, size: file.size, importedAt: 0 });
    }
    // Real filesystems don't report import order the way IndexedDB's
    // own auto timestamps do -- alphabetical (reverse) is the same
    // fallback ordering `_scan_log_files()` uses on the PC side for
    // its own filename-sorted list (KADI log filenames are
    // timestamp-prefixed, so this also happens to be recency order).
    return metas.sort((a, b) => (a.name < b.name ? 1 : -1));
  }

  async readLogFile(id: string): Promise<string> {
    const dir = await this.logsDir();
    const handle = await dir.getFileHandle(id).catch(() => {
      throw new Error(`No log file named "${id}" in this store.`);
    });
    const file = await handle.getFile();
    return file.text();
  }

  async importLogFiles(): Promise<MsomiLogFileMeta[]> {
    if (!this.showOpenFilePicker) return [];
    let picked: FSFileHandleLike[];
    try {
      picked = await this.showOpenFilePicker({
        multiple: true,
        types: [{ description: 'MSOMI decision log', accept: { 'application/x-ndjson': ['.jsonl'] } }],
      });
    } catch {
      return []; // player cancelled the dialog
    }
    const dir = await this.logsDir();
    const metas: MsomiLogFileMeta[] = [];
    for (const source of picked) {
      const file = await source.getFile();
      const content = await file.text();
      const dest = await dir.getFileHandle(source.name, { create: true });
      const writable = await dest.createWritable();
      await writable.write(content);
      await writable.close();
      metas.push({ id: source.name, name: source.name, size: file.size, importedAt: Date.now() });
    }
    return metas;
  }

  async listModels(): Promise<string[]> {
    const dir = await this.modelsDir();
    const names: string[] = [];
    for await (const entry of dir.values()) {
      if (entry.kind === 'file' && entry.name.endsWith('.json')) names.push(entry.name);
    }
    // Same reasoning as listLogFiles(): no real mtime available
    // through this narrow interface, so newest-looking-first falls
    // back to filename order (Chuo's own filenames are
    // msomi_TIMESTAMP.json, so this is also recency order in
    // practice — mirrors list_models()'s own comment on the PC side
    // about its alphabetically-last-is-most-recent convention).
    return names.sort((a, b) => (a < b ? 1 : -1));
  }

  async saveModel(filename: string, model: MsomiTrainedModel): Promise<void> {
    const finalName = filename.endsWith('.json') ? filename : `${filename}.json`;
    const dir = await this.modelsDir();
    const handle = await dir.getFileHandle(finalName, { create: true });
    const writable = await handle.createWritable();
    await writable.write(JSON.stringify(model, null, 2));
    await writable.close();
  }

  async loadModel(filename: string): Promise<MsomiTrainedModel> {
    const dir = await this.modelsDir();
    const handle = await dir.getFileHandle(filename).catch(() => {
      throw new Error(`No saved model named "${filename}".`);
    });
    const file = await handle.getFile();
    return JSON.parse(await file.text()) as MsomiTrainedModel;
  }

  async deleteModel(filename: string): Promise<void> {
    const dir = await this.modelsDir();
    await dir.removeEntry(filename).catch(() => {
      // Matches MsomiStore.deleteModel()'s documented no-op-if-missing
      // contract -- removeEntry() rejects (NotFoundError) rather than
      // silently succeeding on a real FileSystemDirectoryHandle.
    });
  }
}

/**
 * MANUAL BROWSER TEST STEPS (file-picker path — cannot be exercised
 * headlessly, see this file's header):
 *
 * 1. Open Chuo in a Chromium-based browser (Chrome/Edge/Brave) —
 *    confirm the backend indicator (see ChuoScene.ts) shows "Files",
 *    not "Browser storage".
 * 2. On first use of the Data tab, confirm a real OS folder-picker
 *    dialog opens (not a browser-styled modal) — pick an empty
 *    scratch folder. Confirm `logs/` and `msomi_models/` subfolders
 *    are created inside it (visible in a real file manager).
 * 3. Click "Import from device", pick a `.jsonl` file from ANYWHERE
 *    else on disk (e.g. Downloads) — confirm it now appears in Chuo's
 *    log list, and a copy has actually landed in the chosen folder's
 *    `logs/` subfolder (check with a file manager).
 * 4. Reload the page. Confirm Chuo does NOT re-prompt for a folder
 *    (the persisted handle is reused) and the previously-imported log
 *    still lists.
 * 5. In the OS, revoke the site's file-system permission (or use the
 *    browser's own site-settings UI) and reload — confirm Chuo
 *    re-prompts for permission (via `requestPermission()`) rather than
 *    silently failing.
 * 6. Train and save a model; confirm a real `.json` file appears in
 *    the chosen folder's `msomi_models/` subfolder with the expected
 *    content, and that deleting it from Chuo's UI actually removes
 *    that file (check with a file manager after deleting).
 * 7. Point the folder picker at an ACTUAL PC KADI desktop install's
 *    per-user data directory (see core/game_logger.py's
 *    `_per_user_data_dir()` for where that is on your OS) instead of
 *    a scratch folder — confirm the real desktop app's own `.jsonl`
 *    logs and any `msomi_models/*.json` show up in Chuo directly, with
 *    no import step, since this backend reads that folder's `logs/`
 *    subfolder as its own log list.
 */
