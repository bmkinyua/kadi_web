/**
 * KADI - the one call site that picks a concrete MsomiStore backend.
 * Mirrors `@kadi/adapter-web`'s own role for PlatformAdapter (see
 * apps/web-pwa/src/main.ts's header: "the ONLY file that imports a
 * concrete adapter class") — this is that same discipline applied to
 * MsomiStore: everything else (ChuoScene.ts, trainer.ts) only ever
 * sees the `MsomiStore` type from `@kadi/adapter-interface`.
 *
 * FEATURE DETECTION, NOT USER-AGENT SNIFFING (Part B's explicit
 * requirement): gated on `isFileSystemAccessSupported()`, which checks
 * for the actual `showDirectoryPicker` function on `window` — the
 * same "does the capability exist" test every other platform-specific
 * branch in this codebase already uses (see e.g. WebAdapter.ts's
 * `crypto.randomUUID` check), never a browser/OS name check.
 */
import type { MsomiStore } from '@kadi/adapter-interface';
import { FileSystemAccessMsomiStore, isFileSystemAccessSupported } from './FileSystemAccessMsomiStore.js';
import { IndexedDbMsomiStore } from './IndexedDbMsomiStore.js';

export function createMsomiStore(): MsomiStore {
  if (isFileSystemAccessSupported()) {
    return new FileSystemAccessMsomiStore();
  }
  return new IndexedDbMsomiStore();
}

export { FileSystemAccessMsomiStore, isFileSystemAccessSupported } from './FileSystemAccessMsomiStore.js';
export { IndexedDbMsomiStore } from './IndexedDbMsomiStore.js';
