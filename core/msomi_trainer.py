"""
KADI - MSOMI Tier 1 trainer: a conditional-logit ("discrete choice")
model over the same named features _evaluate_play already computes.

Given many decisions, each a set of legal options with known features
and which one was actually picked, this learns feature weights so a
linear combination of the CHOSEN option's features scores higher than
the other options in the same decision, as often as possible — the
standard econometric "conditional logit" setup, fit here with plain
gradient descent. No heavy dependency: just numpy, and this is a tiny
model (a couple dozen features at most) that trains in well under a
second even on a large logged dataset.

This deliberately does NOT reuse _evaluate_play's own 'score' as an
input feature — that would just be re-deriving the existing hand-tuned
formula instead of learning new weights from real decisions, which is
the whole point of Tier 1.

Tier 2 (a tree-ensemble model, for when the dataset is large enough to
benefit from one) reads the exact same exported decisions — only the
training algorithm and the resulting model file differ; nothing here
needs to change when Tier 2 is added.
"""
from __future__ import annotations
import json
import os
import shutil
from typing import Dict, List, Optional, Tuple

from core.decision_logger import SCHEMA_VERSION as DECISION_SCHEMA_VERSION
from core.game_logger import base_dir
from constants import resource_base_dir

MODEL_SCHEMA_VERSION = 1
MODELS_DIR_NAME = "msomi_models"

# The trainable feature set — every one of these is a plain number or
# boolean already present on every logged option (see
# core/decision_logger._OPTION_FIELDS). Deliberately excludes 'score'
# (see module docstring) and the structural 'is_draw'/'cards' fields,
# which aren't judged features. Chuo's checkbox list is built from
# exactly this, so a UI change there and a training change here can
# never quietly drift out of sync with each other.
TRAINABLE_FEATURES = [
    'cards_played', 'cards_remaining', 'empties_hand', 'wastes_win',
    'leaves_kadi', 'unanswered_question', 'pickup_value_added',
    'has_suit_change', 'has_skip', 'has_kickback', 'has_question',
    'next_is_threat', 'stranded_cluster_cost',
]


def _to_float(v) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v is None:
        return 0.0
    return float(v)


def load_decisions(paths: List[str], include_human: bool = True,
                    include_ai: bool = True) -> Tuple[List[dict], dict]:
    """Read and concatenate decision records from one or more JSONL
    files (see core/decision_logger) — Chuo's multi-select log-file
    picker feeds straight into this, no limit on how many. Skips lines
    that fail to parse or that don't match the current decision-log
    schema version, rather than aborting the whole load — one bad line,
    or one file logged under an old game version, shouldn't silently
    poison a training run OR crash it. Returns (decisions, stats) so
    Chuo can report exactly what was skipped and why."""
    decisions = []
    skipped_schema = 0
    skipped_parse = 0
    for path in paths:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    skipped_parse += 1
                    continue
                if rec.get('schema_version') != DECISION_SCHEMA_VERSION:
                    skipped_schema += 1
                    continue
                if rec.get('is_human') and not include_human:
                    continue
                if not rec.get('is_human') and not include_ai:
                    continue
                decisions.append(rec)
    stats = {
        'loaded': len(decisions),
        'skipped_schema_mismatch': skipped_schema,
        'skipped_unparseable': skipped_parse,
        'human_count': sum(1 for d in decisions if d.get('is_human')),
        'ai_count': sum(1 for d in decisions if not d.get('is_human')),
    }
    return decisions, stats


def train(decisions: List[dict], feature_names: List[str],
          human_weight: float = 2.0, iterations: int = 500,
          learning_rate: float = 0.1) -> dict:
    """Fit a conditional-logit model over `feature_names` (a subset of
    TRAINABLE_FEATURES — this is exactly what Chuo's feature checkboxes
    select). human_weight scales how much more each human decision
    counts relative to an AI one in the loss, per MSOMI's "learn from
    humans first" priority — 2.0 means a human decision counts twice as
    much as an AI decision of the same shape; 1.0 treats them equally.

    Returns a plain dict, JSON-serializable as-is: schema version, the
    feature list actually used (so a mismatched future game version can
    be caught at load time instead of silently misbehaving), the
    learned weight per feature, and training diagnostics — exactly the
    "see the params well" output requested, no opaque binary blob.
    """
    import numpy as np

    if not feature_names:
        raise ValueError("Select at least one feature to train on.")
    invalid = [f for f in feature_names if f not in TRAINABLE_FEATURES]
    if invalid:
        raise ValueError(f"Not a trainable feature: {invalid}")

    groups: List[Tuple['np.ndarray', int, float, bool]] = []
    for rec in decisions:
        opts = rec.get('options', [])
        if len(opts) < 2:
            continue  # no real choice was made here — nothing to learn from
        X_i = np.array([[_to_float(o.get(f, 0)) for f in feature_names] for o in opts])
        chosen_i = rec['chosen_rank']
        is_human = bool(rec.get('is_human'))
        weight_i = human_weight if is_human else 1.0
        groups.append((X_i, chosen_i, weight_i, is_human))

    if not groups:
        raise ValueError("No decision had more than one real option — nothing to learn from.")

    n_features = len(feature_names)
    w = np.zeros(n_features)
    total_weight = sum(g[2] for g in groups)

    for _ in range(iterations):
        grad = np.zeros(n_features)
        for X_i, chosen_i, weight_i, _ in groups:
            scores = X_i @ w
            scores = scores - scores.max()  # numerical stability, doesn't change softmax
            exp_scores = np.exp(scores)
            probs = exp_scores / exp_scores.sum()
            onehot = np.zeros(len(probs))
            onehot[chosen_i] = 1.0
            grad += weight_i * (X_i.T @ (probs - onehot))
        grad /= total_weight
        w -= learning_rate * grad

    # Diagnostics: how often the trained model's own argmax matches what
    # was actually chosen, ON THE TRAINING DATA ITSELF — Chuo's dataset
    # is generally too small to hold out a meaningful validation split,
    # so this is reported plainly as a training-set agreement rate, not
    # claimed as out-of-sample accuracy.
    correct = 0
    human_correct = 0
    human_total = 0
    for X_i, chosen_i, weight_i, is_human in groups:
        pred = int(np.argmax(X_i @ w))
        if pred == chosen_i:
            correct += 1
            if is_human:
                human_correct += 1
        if is_human:
            human_total += 1

    return {
        'schema_version': MODEL_SCHEMA_VERSION,
        'decision_schema_version': DECISION_SCHEMA_VERSION,
        'model_type': 'conditional_logit',
        'features': list(feature_names),
        'weights': {f: float(wi) for f, wi in zip(feature_names, w)},
        'training': {
            'num_decisions': len(groups),
            'num_human_decisions': human_total,
            'num_ai_decisions': len(groups) - human_total,
            'human_weight': human_weight,
            'iterations': iterations,
            'learning_rate': learning_rate,
            'train_agreement': correct / len(groups),
            'train_agreement_human_only': (human_correct / human_total) if human_total else None,
        },
    }


def score_option(model: dict, option_features: dict) -> float:
    """Score one option's raw feature dict using a trained model —
    plain weighted sum, no numpy needed at inference time. Missing
    features (e.g. the model was trained on a smaller feature subset
    than the game currently computes) contribute 0, matching how
    training encoded them."""
    total = 0.0
    for f, w in model['weights'].items():
        total += w * _to_float(option_features.get(f, 0))
    return total


def get_models_dir() -> str:
    """The msomi_models/ directory Chuo saves trained models into (and
    the MSOMI settings' "attach a model" picker reads from) — created if
    it doesn't exist yet, sitting alongside logs/ at the app root."""
    d = os.path.join(base_dir(), MODELS_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def seed_bundled_reference_model_if_empty() -> Optional[str]:
    """Copies the ONE reference MSOMI model shipped alongside the app
    (see project-root msomi_models/ — NOT the same directory as
    get_models_dir()'s per-user one; that distinction is the whole
    point here) into the real per-user models directory, but ONLY if
    that per-user directory is currently empty — i.e. a genuinely fresh
    install/profile that has never trained or received a model before.

    Call this once, at startup (see main.py), after settings/profile
    are loaded. Deliberately a one-time seed, not an ongoing sync: once
    a player has ANY model of their own (even a bad first attempt),
    this backs off permanently and never touches their models directory
    again — the shipped reference is a starting point, not something
    that should reappear or get force-updated later.

    Returns the destination path if a model was actually seeded, or
    None if there was nothing to do (per-user dir already has models,
    or no bundled reference model exists in this build/checkout —
    both are perfectly normal, not errors)."""
    dest_dir = get_models_dir()
    if os.listdir(dest_dir):
        return None  # not empty — player already has model(s), never touch

    bundled_dir = os.path.join(resource_base_dir(), MODELS_DIR_NAME)
    if not os.path.isdir(bundled_dir):
        return None  # dev checkout / build with no bundled reference model
    bundled_models = sorted(f for f in os.listdir(bundled_dir) if f.endswith('.json'))
    if not bundled_models:
        return None

    # Only one is ever meant to ship (see the packaging decision this
    # implements) — but if a build somehow includes more, take the
    # alphabetically-last one, which for this project's
    # msomi_TIMESTAMP.json naming convention is also the most recent.
    src = os.path.join(bundled_dir, bundled_models[-1])
    dst = os.path.join(dest_dir, bundled_models[-1])
    try:
        shutil.copy2(src, dst)
        return dst
    except OSError:
        return None  # non-fatal — Chuo just starts with no models, same as any fresh install


def save_model(model: dict, filename: str) -> str:
    """Save a trained model dict as pretty-printed JSON — Chuo's "see
    the params well" output. Returns the full path written."""
    if not filename.endswith('.json'):
        filename += '.json'
    path = os.path.join(get_models_dir(), filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(model, f, indent=2)
    return path


def list_models() -> List[str]:
    """Filenames (not full paths) of every saved model in the models
    directory, most recently modified first — feeds both Chuo's own
    "previously trained" list and the MSOMI attach-model picker."""
    d = get_models_dir()
    files = [f for f in os.listdir(d) if f.endswith('.json')]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
    return files


def load_model(filename_or_path: str) -> dict:
    """Load a model JSON file, by filename (resolved against
    get_models_dir()) or a full path."""
    path = filename_or_path
    if not os.path.isabs(path) and not os.path.dirname(path):
        path = os.path.join(get_models_dir(), path)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def validate_model(model: dict) -> Optional[str]:
    """Returns None if `model` looks like a well-formed model file this
    game version can use, else a human-readable reason it can't — used
    by the MSOMI settings' "attach a model" flow so a stale or corrupt
    file is caught with a clear message instead of crashing or silently
    misplaying."""
    if not isinstance(model, dict):
        return "Not a valid model file."
    if model.get('schema_version') != MODEL_SCHEMA_VERSION:
        return (f"This model was trained under a different MSOMI format "
                f"(v{model.get('schema_version')}, this game uses v{MODEL_SCHEMA_VERSION}) "
                f"— retrain it in Chuo.")
    if model.get('decision_schema_version') != DECISION_SCHEMA_VERSION:
        return (f"This model was trained on logs from a different game version "
                f"(decision format v{model.get('decision_schema_version')}, this "
                f"game logs v{DECISION_SCHEMA_VERSION}) — retrain it in Chuo using "
                f"logs from the current version.")
    weights = model.get('weights')
    if not isinstance(weights, dict) or not weights:
        return "Model file has no learned weights."
    if any(f not in TRAINABLE_FEATURES for f in weights):
        return "Model file references a feature this game version doesn't recognize."
    return None
