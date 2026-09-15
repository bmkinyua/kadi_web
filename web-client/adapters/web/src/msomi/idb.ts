/**
 * KADI - minimal IndexedDB promise wrapper, hand-rolled rather than
 * pulling in the `idb` package: IndexedDbMsomiStore.ts only ever needs
 * "open this DB with these two object stores" plus get/getAll/put/
 * delete on a single store per call, which is a handful of small
 * promisified wrappers around the raw callback-based IDB API — not
 * enough surface to justify a dependency, consistent with this
 * codebase's existing bias toward hand-rolled code over a new package
 * for something this size (see trainer.ts's own header for the same
 * reasoning applied to the trainer itself).
 */

const DB_NAME = 'kadi-msomi';
const DB_VERSION = 1;
export const LOGS_STORE = 'logs';
export const MODELS_STORE = 'models';
/** Holds the one persisted `FileSystemDirectoryHandle` for
 * FileSystemAccessMsomiStore.ts — a third, unrelated-shape store in
 * this same small database rather than a whole separate DB, since
 * IndexedDB's own version-upgrade machinery makes "one DB, a few
 * stores" simpler than coordinating two open connections for what's
 * conceptually the same "local MSOMI storage" concern either way. */
export const FSA_HANDLE_STORE = 'fsaHandles';

/** Opens (creating on first use) the shared MSOMI database. Takes an
 * injectable `IDBFactory` so tests can point this at `fake-indexeddb`
 * instead of a real browser — see __tests__/IndexedDbMsomiStore.test.ts. */
export function openMsomiDb(factory: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = factory.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(LOGS_STORE)) {
        db.createObjectStore(LOGS_STORE, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(MODELS_STORE)) {
        db.createObjectStore(MODELS_STORE, { keyPath: 'filename' });
      }
      if (!db.objectStoreNames.contains(FSA_HANDLE_STORE)) {
        db.createObjectStore(FSA_HANDLE_STORE, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Failed to open kadi-msomi IndexedDB'));
  });
}

export function idbRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

export function idbGetAll<T>(db: IDBDatabase, store: string): Promise<T[]> {
  const tx = db.transaction(store, 'readonly');
  return idbRequest<T[]>(tx.objectStore(store).getAll());
}

export function idbGet<T>(db: IDBDatabase, store: string, key: IDBValidKey): Promise<T | undefined> {
  const tx = db.transaction(store, 'readonly');
  return idbRequest<T>(tx.objectStore(store).get(key));
}

export function idbPut(db: IDBDatabase, store: string, value: unknown): Promise<IDBValidKey> {
  try {
    const tx = db.transaction(store, 'readwrite');
    return idbRequest<IDBValidKey>(tx.objectStore(store).put(value));
  } catch (err) {
    // A real IndexedDB (and fake-indexeddb) throws SYNCHRONOUSLY, not
    // via a rejected request, when `value` can't be structured-cloned
    // -- e.g. a hand-built test fake carrying function properties (a
    // real FileSystemDirectoryHandle clones fine in an actual
    // browser; this codebase's own test fakes for it don't, see
    // FileSystemAccessMsomiStore.ts's own best-effort-persistence
    // comment at its one idbPut() call site). Normalized into a
    // rejected promise here so every caller can use one `.catch()`
    // shape regardless of whether the failure was sync or async.
    return Promise.reject(err instanceof Error ? err : new Error(String(err)));
  }
}

export function idbDelete(db: IDBDatabase, store: string, key: IDBValidKey): Promise<void> {
  const tx = db.transaction(store, 'readwrite');
  return idbRequest<undefined>(tx.objectStore(store).delete(key)).then(() => undefined);
}
