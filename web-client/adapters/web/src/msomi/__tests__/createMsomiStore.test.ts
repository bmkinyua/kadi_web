import { afterEach, describe, expect, it } from 'vitest';
import { createMsomiStore } from '../createMsomiStore.js';
import { FileSystemAccessMsomiStore } from '../FileSystemAccessMsomiStore.js';
import { IndexedDbMsomiStore } from '../IndexedDbMsomiStore.js';

describe('createMsomiStore', () => {
  const originalShowDirectoryPicker = (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker;

  afterEach(() => {
    (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker = originalShowDirectoryPicker;
  });

  it('picks FileSystemAccessMsomiStore when showDirectoryPicker exists', () => {
    (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker = async () => {
      throw new Error('not used in this test');
    };
    expect(createMsomiStore()).toBeInstanceOf(FileSystemAccessMsomiStore);
  });

  it('falls back to IndexedDbMsomiStore when it does not', () => {
    delete (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker;
    expect(createMsomiStore()).toBeInstanceOf(IndexedDbMsomiStore);
  });
});
