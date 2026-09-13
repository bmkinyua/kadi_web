/**
 * KADI web-client — Chuo / MSOMI trainer, ported from
 * core/msomi_trainer.py's `load_decisions()` / `train()` /
 * `score_option()` / `validate_model()`.
 *
 * THE PORTING DECISION (Part A's load-bearing question): `train()` on
 * the PC side fits a conditional-logit model with plain gradient
 * descent — a couple dozen features at most, ~500 iterations, no
 * numerical-optimization library beyond NumPy for the matrix
 * multiplies and `exp()`/`sum()`. That's small enough to hand-roll
 * directly in TypeScript with ordinary `number[]`/`number[][]` arrays
 * and `for` loops — no `mathjs` or any other new dependency needed.
 * Two other options were considered and rejected:
 *   - A WASM/native numeric library: real overkill for ≤13 features
 *     and a training set that (per the PC module's own docstring)
 *     "trains in well under a second even on a large logged dataset"
 *     — the plain-JS version below is well under that already at
 *     realistic Chuo dataset sizes (hundreds to low thousands of
 *     decisions), verified against the same iteration count.
 *   - `mathjs`: would make the matrix code read closer to the Python
 *     original (`X.T.dot(...)`-style), but this codebase's own
 *     stated bias (see the handoff prompt) is against adding a heavy
 *     dependency for something this size, and mathjs's general-matrix
 *     API is genuine overkill for a fixed-shape "N options × M
 *     features" problem — plain nested arrays are simpler to read,
 *     debug, and unit-test here.
 * So: a direct, dependency-free reimplementation of the exact same
 * loss/gradient (softmax over each decision's options, weighted by
 * human_weight, averaged by total weight) — see trainConditionalLogit()
 * below. Parity with the Python original is verified directly, not
 * assumed: __tests__/trainer.test.ts trains on a small fixed decision
 * set and asserts the learned weights match core/msomi_trainer.py's
 * own `train()` output on the SAME input (generated once via a real
 * Python run — see that test's own header for the exact numbers and
 * how they were produced), not just "looks reasonable."
 *
 * SCHEMA VERSIONS: DECISION_SCHEMA_VERSION/MODEL_SCHEMA_VERSION below
 * are copied from core/decision_logger.SCHEMA_VERSION and
 * core/msomi_trainer.MODEL_SCHEMA_VERSION as of this port. There is no
 * shared source of truth across the Python and TypeScript codebases —
 * if either ever bumps its version (a logged-feature shape change),
 * THIS FILE'S CONSTANT must be bumped by hand to match, or a model/log
 * trained under the new PC format will be silently treated as a
 * version mismatch here (or worse, the reverse: an old assumption
 * silently accepted). Flagged here deliberately as a manual
 * cross-language sync point — see
 * KADI_web_port_implementation_plan.md's "Flagged Risks — Chuo/MSOMI
 * delivery" section for the tracked version of this same note.
 */

import type { MsomiDecisionRecord, MsomiTrainedModel } from '@kadi/adapter-interface';

/** Mirrors core/decision_logger.SCHEMA_VERSION as of this port — see
 * this file's header for the manual-sync caveat. */
export const DECISION_SCHEMA_VERSION = 1;

/** Mirrors core/msomi_trainer.MODEL_SCHEMA_VERSION as of this port —
 * same manual-sync caveat as DECISION_SCHEMA_VERSION above. */
export const MODEL_SCHEMA_VERSION = 1;

/** Verbatim copy of core/msomi_trainer.TRAINABLE_FEATURES — see that
 * module's own comment: deliberately excludes 'score' (the point of
 * Tier 1 is to learn NEW weights, not re-derive the hand-tuned
 * formula) and the structural 'is_draw'/'cards' fields. Chuo's
 * feature checkboxes are built from exactly this list, same as the
 * PC's own Features tab, so a change here and a training change there
 * can never quietly drift apart. */
export const TRAINABLE_FEATURES = [
  'cards_played',
  'cards_remaining',
  'empties_hand',
  'wastes_win',
  'leaves_kadi',
  'unanswered_question',
  'pickup_value_added',
  'has_suit_change',
  'has_skip',
  'has_kickback',
  'has_question',
  'next_is_threat',
  'stranded_cluster_cost',
] as const;

export type TrainableFeature = (typeof TRAINABLE_FEATURES)[number];

/** Mirrors `_to_float()` exactly: booleans become 1.0/0.0, missing/
 * null becomes 0.0, everything else is coerced numerically. */
function toFloat(v: unknown): number {
  if (typeof v === 'boolean') return v ? 1.0 : 0.0;
  if (v === null || v === undefined) return 0.0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0.0;
}

export interface LoadDecisionsStats {
  loaded: number;
  skippedSchemaMismatch: number;
  skippedUnparseable: number;
  humanCount: number;
  aiCount: number;
}

export interface LoadDecisionsOptions {
  includeHuman?: boolean;
  includeAi?: boolean;
}

/**
 * Ports `load_decisions()`. The PC version reads files by path; this
 * version takes the already-read text content of each file (Chuo.ts
 * gets that from MsomiStore.readLogFile() — see that interface's own
 * header for why file I/O itself lives one level below this pure
 * module). Same behavior otherwise: skips lines that fail to parse or
 * that don't match DECISION_SCHEMA_VERSION rather than aborting the
 * whole load, and reports exactly what was skipped and why.
 */
export function loadDecisionsFromText(
  fileContents: string[],
  options: LoadDecisionsOptions = {},
): { decisions: MsomiDecisionRecord[]; stats: LoadDecisionsStats } {
  const includeHuman = options.includeHuman ?? true;
  const includeAi = options.includeAi ?? true;

  const decisions: MsomiDecisionRecord[] = [];
  let skippedSchemaMismatch = 0;
  let skippedUnparseable = 0;

  for (const text of fileContents) {
    for (const rawLine of text.split('\n')) {
      const line = rawLine.trim();
      if (!line) continue;
      let rec: unknown;
      try {
        rec = JSON.parse(line);
      } catch {
        skippedUnparseable += 1;
        continue;
      }
      const candidate = rec as Partial<MsomiDecisionRecord> | null;
      if (!candidate || typeof candidate !== 'object' || candidate.schema_version !== DECISION_SCHEMA_VERSION) {
        skippedSchemaMismatch += 1;
        continue;
      }
      if (candidate.is_human && !includeHuman) continue;
      if (!candidate.is_human && !includeAi) continue;
      decisions.push(candidate as MsomiDecisionRecord);
    }
  }

  const humanCount = decisions.filter((d) => d.is_human).length;
  return {
    decisions,
    stats: {
      loaded: decisions.length,
      skippedSchemaMismatch,
      skippedUnparseable,
      humanCount,
      aiCount: decisions.length - humanCount,
    },
  };
}

export interface TrainOptions {
  humanWeight?: number;
  iterations?: number;
  learningRate?: number;
}

/** Thrown for the same two "nothing to train on" cases
 * core/msomi_trainer.train() raises ValueError for — kept as a plain
 * Error (not a custom class) since ChuoScene.ts only ever reads
 * `.message`, same as scenes.py's `except Exception as e` /
 * `f"Training failed: {e}"` handling. */
export class MsomiTrainingError extends Error {}

/**
 * Direct port of `train()` — see this file's header for the porting
 * decision. `featureNames` must be a subset of TRAINABLE_FEATURES.
 */
export function trainConditionalLogit(
  decisions: MsomiDecisionRecord[],
  featureNames: string[],
  options: TrainOptions = {},
): MsomiTrainedModel {
  const humanWeight = options.humanWeight ?? 2.0;
  const iterations = options.iterations ?? 500;
  const learningRate = options.learningRate ?? 0.1;

  if (featureNames.length === 0) {
    throw new MsomiTrainingError('Select at least one feature to train on.');
  }
  const invalid = featureNames.filter((f) => !(TRAINABLE_FEATURES as readonly string[]).includes(f));
  if (invalid.length > 0) {
    throw new MsomiTrainingError(`Not a trainable feature: ${invalid.join(', ')}`);
  }

  interface Group {
    X: number[][]; // options x features
    chosen: number;
    weight: number;
    isHuman: boolean;
  }

  const groups: Group[] = [];
  for (const rec of decisions) {
    const opts = rec.options ?? [];
    if (opts.length < 2) continue; // no real choice was made here
    const X = opts.map((o) => featureNames.map((f) => toFloat(o[f])));
    groups.push({
      X,
      chosen: rec.chosen_rank,
      weight: rec.is_human ? humanWeight : 1.0,
      isHuman: Boolean(rec.is_human),
    });
  }

  if (groups.length === 0) {
    throw new MsomiTrainingError('No decision had more than one real option — nothing to learn from.');
  }

  const nFeatures = featureNames.length;
  let w = new Array<number>(nFeatures).fill(0);
  const totalWeight = groups.reduce((sum, g) => sum + g.weight, 0);

  for (let iter = 0; iter < iterations; iter += 1) {
    const grad = new Array<number>(nFeatures).fill(0);
    for (const { X, chosen, weight } of groups) {
      const scores = X.map((row) => dot(row, w));
      const maxScore = Math.max(...scores);
      const expScores = scores.map((s) => Math.exp(s - maxScore));
      const sumExp = expScores.reduce((a, b) => a + b, 0);
      const probs = expScores.map((e) => e / sumExp);
      for (let j = 0; j < nFeatures; j += 1) {
        let g = 0;
        for (let i = 0; i < probs.length; i += 1) {
          const onehot = i === chosen ? 1 : 0;
          g += X[i][j] * (probs[i] - onehot);
        }
        grad[j] += weight * g;
      }
    }
    for (let j = 0; j < nFeatures; j += 1) grad[j] /= totalWeight;
    w = w.map((wj, j) => wj - learningRate * grad[j]);
  }

  let correct = 0;
  let humanCorrect = 0;
  let humanTotal = 0;
  for (const { X, chosen, isHuman } of groups) {
    const scores = X.map((row) => dot(row, w));
    const pred = argmax(scores);
    if (pred === chosen) {
      correct += 1;
      if (isHuman) humanCorrect += 1;
    }
    if (isHuman) humanTotal += 1;
  }

  const weights: Record<string, number> = {};
  featureNames.forEach((f, i) => {
    weights[f] = w[i];
  });

  return {
    schema_version: MODEL_SCHEMA_VERSION,
    decision_schema_version: DECISION_SCHEMA_VERSION,
    model_type: 'conditional_logit',
    features: [...featureNames],
    weights,
    training: {
      num_decisions: groups.length,
      num_human_decisions: humanTotal,
      num_ai_decisions: groups.length - humanTotal,
      human_weight: humanWeight,
      iterations,
      learning_rate: learningRate,
      train_agreement: correct / groups.length,
      train_agreement_human_only: humanTotal ? humanCorrect / humanTotal : null,
    },
  };
}

function dot(a: number[], b: number[]): number {
  let total = 0;
  for (let i = 0; i < a.length; i += 1) total += a[i] * b[i];
  return total;
}

function argmax(values: number[]): number {
  let bestIdx = 0;
  let bestVal = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    if (values[i] > bestVal) {
      bestVal = values[i];
      bestIdx = i;
    }
  }
  return bestIdx;
}

/** Direct port of `score_option()` — plain weighted sum, no matrix
 * math needed at inference time. Missing features contribute 0,
 * matching how training itself encodes them via toFloat(). */
export function scoreOption(model: MsomiTrainedModel, optionFeatures: Record<string, unknown>): number {
  let total = 0;
  for (const [f, wgt] of Object.entries(model.weights)) {
    total += wgt * toFloat(optionFeatures[f]);
  }
  return total;
}

/**
 * Direct port of `validate_model()` — same reasons/messages, used by
 * a future "attach a model" flow exactly as the PC's MSOMI settings
 * uses it, and by ChuoScene.ts's own model-list/import path so a
 * stale or corrupt file is caught with a clear message rather than
 * crashing training or silently misplaying. Returns null when valid.
 */
export function validateModel(model: unknown): string | null {
  if (typeof model !== 'object' || model === null) {
    return 'Not a valid model file.';
  }
  const m = model as Partial<MsomiTrainedModel>;
  if (m.schema_version !== MODEL_SCHEMA_VERSION) {
    return (
      `This model was trained under a different MSOMI format ` +
      `(v${String(m.schema_version)}, this game uses v${MODEL_SCHEMA_VERSION}) ` +
      `— retrain it in Chuo.`
    );
  }
  if (m.decision_schema_version !== DECISION_SCHEMA_VERSION) {
    return (
      `This model was trained on logs from a different game version ` +
      `(decision format v${String(m.decision_schema_version)}, this ` +
      `game logs v${DECISION_SCHEMA_VERSION}) — retrain it in Chuo using ` +
      `logs from the current version.`
    );
  }
  const weights = m.weights;
  if (typeof weights !== 'object' || weights === null || Array.isArray(weights) || Object.keys(weights).length === 0) {
    return 'Model file has no learned weights.';
  }
  const known: readonly string[] = TRAINABLE_FEATURES;
  if (Object.keys(weights).some((f) => !known.includes(f))) {
    return "Model file references a feature this game version doesn't recognize.";
  }
  return null;
}
