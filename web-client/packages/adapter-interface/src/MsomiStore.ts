/**
 * KADI - the local storage contract for Chuo / MSOMI (train-your-own-
 * AI). Sits in this package for the same reason PlatformAdapter.ts
 * does (see that file's header): packages/renderer must be able to
 * TYPE against this without ever importing a concrete backend class,
 * and concrete implementations live one level down in adapters/*.
 *
 * WHY THIS ISN'T PART OF PlatformAdapter ITSELF: getSettings()/
 * getProfile() are each a single small JSON blob with one obvious
 * shape everywhere. MSOMI storage is fundamentally different —
 * multiple named decision-log files (arbitrarily many, arbitrarily
 * large, imported from anywhere on the player's device — see
 * scenes.py's ChuoScene._browse_for_logs()) plus multiple named
 * trained-model files — so it needs its own small file-system-shaped
 * interface (list/read/import, list/save/load/delete) rather than
 * a get/save pair. Kept as a SEPARATE contract, injected into
 * ChuoScene.ts alongside `adapter` (see bootstrapGame() in index.ts
 * and apps/web-pwa/src/main.ts), so a future platform with no local
 * filesystem concept at all (Discord/Telegram) simply never
 * constructs one rather than having to implement dead methods on
 * PlatformAdapter itself.
 *
 * TWO BACKENDS, ONE INTERFACE (this session's storage decision — see
 * KADI_web_port_implementation_plan.md §9's Chuo row): the File
 * System Access API (`showDirectoryPicker`/`showOpenFilePicker`)
 * where the browser supports it, IndexedDB everywhere else. Both
 * satisfy this exact interface; ChuoScene.ts and the trainer never
 * know or care which one is live — see adapters/web/src/msomi/
 * createMsomiStore.ts for the feature-detection that picks one.
 * Every method here is a Promise for that reason: IndexedDB is
 * inherently async, and FSA's own directory/file handle calls are
 * async too, so both backends implement this identically shaped
 * surface without either being forced into a synchronous facade it
 * doesn't have.
 */

/** One entry in the log-file list Chuo's Data tab renders — enough to
 * show a name and let the player pick it, without needing the full
 * (often large) decision-log content just to populate a list. */
export interface MsomiLogFileMeta {
  /** Stable key for readLogFile()/deletion — an opaque store-assigned
   * id, NOT necessarily the same as `name` (two imports of files that
   * happen to share a filename must not collide). */
  id: string;
  /** Display filename, e.g. "LOG_20260101_120000.jsonl". */
  name: string;
  /** Byte length of the stored content, for Chuo's list rows (mirrors
   * the PC's own file list, which is filename-only, but a size is
   * cheap to keep and genuinely useful for a "which one is huge"
   * glance the PC version doesn't offer). */
  size: number;
  /** When this entry was imported into the store (epoch ms) — used
   * for default list ordering (most-recent-first, matching
   * `_scan_log_files()`'s own `files.sort(reverse=True)` on
   * timestamp-prefixed filenames). */
  importedAt: number;
}

/** Which concrete backend is actually live — surfaced so Chuo's UI
 * can show a small "Files/IndexedDB" indicator (useful for a player
 * wondering why "Import from device" does or doesn't open a real
 * native file-picker dialog) without importing either concrete class
 * to find out. */
export type MsomiStoreBackendKind = 'file-system-access' | 'indexeddb';

export interface MsomiStore {
  readonly backendKind: MsomiStoreBackendKind;

  /** Every log file currently in this store, most-recently-imported
   * first. Mirrors `_scan_log_files()` + `_browse_for_logs()`'s
   * combined result on the PC side — there is no "built-in folder vs
   * externally browsed" distinction here, since a browser has no
   * equivalent of "the game's own logs/ folder" separate from
   * "somewhere else on disk": everything reaches this store via
   * importLogFiles() below, and from then on is just an entry here. */
  listLogFiles(): Promise<MsomiLogFileMeta[]>;

  /** Raw `.jsonl` text content of one previously-imported log file,
   * by its `id`. Rejects if the id doesn't exist (caller should have
   * just gotten it from listLogFiles()). */
  readLogFile(id: string): Promise<string>;

  /** Opens this backend's picker (a real OS file-open dialog either
   * way — `showOpenFilePicker` on the File-System-Access backend, a
   * classic `<input type="file">` on the IndexedDB fallback; see this
   * file's header on why the visible difference is real but doesn't
   * change this contract) and imports whatever `.jsonl` file(s) the
   * player selects, copying their content into this store. Returns
   * metadata for the newly-imported files only (already-listed files
   * are unaffected) — mirrors `_browse_for_logs()`'s "Added N
   * external file(s)" result. Returns an empty array if the player
   * cancels the dialog, never throws for a plain cancel.
   *
   * NOTE ON RE-IMPORT: this is a COPY-IN, not a live link — an FSA
   * pick captures that file's content at the moment of import, same
   * as the IndexedDB path's `<input>`-based read. Editing the
   * original file on disk afterward has no effect on the copy sitting
   * in this store until it's explicitly re-imported. (A live,
   * re-scannable link to a real folder — `showDirectoryPicker` kept
   * open across sessions — was considered and deliberately not built
   * this pass: it adds real cross-session permission-re-grant
   * handling for a "log files change after import" scenario that
   * doesn't come up in normal play, where a finished game's log is
   * already complete by the time anyone opens Chuo.)
   */
  importLogFiles(): Promise<MsomiLogFileMeta[]>;

  /** Filenames (not full paths/ids — this store's models are simpler
   * than its logs: no import-collision concern, since every saved
   * model is generated by this same session's own Save Model button,
   * never picked from an external file the way logs are) of every
   * saved model, most-recently-saved first — mirrors `list_models()`. */
  listModels(): Promise<string[]>;

  /** Persists a trained model under `filename` (".json" appended if
   * missing, matching `save_model()`). Overwrites silently if that
   * filename already exists — Chuo's own Save Model flow always
   * generates a fresh timestamped name (see ChuoScene.ts), so a
   * collision here would only happen from a deliberate re-save. */
  saveModel(filename: string, model: MsomiTrainedModel): Promise<void>;

  /** Loads a previously-saved model by filename. Rejects if it
   * doesn't exist. */
  loadModel(filename: string): Promise<MsomiTrainedModel>;

  /** Removes a saved model by filename. This is a genuine web-side
   * addition, not a PC port — see ChuoScene.ts's own header for why
   * (the PC's ChuoScene has no delete affordance for saved models at
   * all; this store still exposes one, since it's the natural
   * counterpart of a local save and costs nothing extra to support).
   * No-op (does not reject) if the filename doesn't exist. */
  deleteModel(filename: string): Promise<void>;
}

// ── Trained-model / decision-log shapes — mirrors core/msomi_trainer.py
// and core/decision_logger.py's own wire formats exactly (field names,
// nesting) so a model or log file exported from the PC desktop client
// can be imported here (and vice versa) with no translation step. See
// packages/renderer/src/msomi/trainer.ts for the actual training/
// scoring/validation logic that produces and consumes these shapes —
// kept here rather than there because MsomiStore's save/load methods
// above need the type regardless of which package ends up owning the
// training math. ──

/** One legal option as logged by core/decision_logger.py's
 * `log_decision()` — `cards`/`is_draw` are structural, everything else
 * is a plain number/boolean feature. Left loosely typed (index
 * signature) rather than one field per TRAINABLE_FEATURES entry,
 * mirroring how core/msomi_trainer.py's own `_to_float()` reads these
 * generically by name rather than the option dict being a fixed
 * dataclass — a model trained on a feature this version doesn't know
 * about yet should still load and skip it (see validateModel), not
 * be rejected here at the type level. */
export interface MsomiOptionRecord {
  cards: (string | null)[] | null;
  is_draw: boolean;
  score?: number;
  [feature: string]: unknown;
}

/** One decision record, one line of a `.jsonl` log file — mirrors
 * `log_decision()`'s `record` dict exactly. */
export interface MsomiDecisionRecord {
  schema_version: number;
  game_id: string | null;
  is_human: boolean;
  player_name: string;
  difficulty: string;
  hand_before: (string | null)[];
  hand_count: number;
  top_card: string | null;
  pickup_pending: number;
  declared_kadi: boolean;
  chosen_rank: number;
  num_options: number;
  options: MsomiOptionRecord[];
}

/** A trained model file's exact shape — mirrors `train()`'s return
 * dict in core/msomi_trainer.py field-for-field. */
export interface MsomiTrainedModel {
  schema_version: number;
  decision_schema_version: number;
  model_type: 'conditional_logit';
  features: string[];
  weights: Record<string, number>;
  training: {
    num_decisions: number;
    num_human_decisions: number;
    num_ai_decisions: number;
    human_weight: number;
    iterations: number;
    learning_rate: number;
    train_agreement: number;
    train_agreement_human_only: number | null;
  };
}
