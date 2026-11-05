"""Predeclared host engineering gates, never hardware or release qualification."""
# Frozen from training/v4_training/quality.py in R46 P14; source SHA-256:
# 0f7c0d96007e7bf17e2f9e129d01c1fbe2af82ad83bb840d6ad508c7216a7c9f
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.neural_network import MLPClassifier

from v4_runtime.bundle import LABELS


POLICY = dict(schema='cabinet-engineering-quality-v1', qualified=False,
    max_normal_false_positive_window_rate=0.05, min_class_recall=0.80,
    min_macro_f1=0.85, min_input_coverage=0.99,
    source='PREDECLARED_SIMULATION_DEVELOPMENT_GATES_NOT_FIELD_LIMITS')
SETTINGS = [dict(alpha=0.1, normal_weight=weight) for weight in (1.0, 2.0, 4.0)]


def report(labels, probabilities, covered):
    labels, probabilities, covered = np.asarray(labels), np.asarray(probabilities), np.asarray(covered)
    if labels.ndim != 1 or labels.dtype.kind not in 'iu' or probabilities.shape != (len(labels), 5) or covered.shape != labels.shape or covered.dtype != np.bool_:
        raise ValueError('Quality evaluation requires labels, five probabilities and explicit coverage')
    if set(labels) != set(range(5)) or not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0) or np.any(probabilities > 1) or np.any(np.abs(probabilities.sum(1)-1) > 0.02):
        raise ValueError('All five classes and valid probabilities are required')
    predictions = probabilities.argmax(1)
    predictions = np.where(covered, predictions, 5)
    matrix = confusion_matrix(labels, predictions, labels=list(range(6)))[:5]
    recalls = np.diag(matrix)/matrix.sum(1)
    normal_count = int(matrix[0].sum())
    false_positives = int(matrix[0, 1:5].sum())
    false_positive_rate = false_positives/normal_count
    macro = float(f1_score(labels, predictions, labels=list(range(5)), average='macro', zero_division=0))
    checks = dict(normal_false_positive=false_positive_rate <= POLICY['max_normal_false_positive_window_rate'],
        every_class_recall=bool(np.all(recalls >= POLICY['min_class_recall'])),
        macro_f1=macro >= POLICY['min_macro_f1'], input_coverage=float(covered.mean()) >= POLICY['min_input_coverage'])
    return dict(status='PASS_ENGINEERING_QUALITY_ONLY' if all(checks.values()) else 'FAIL_MODEL_QUALITY_GATES',
        qualified=False, physical_truth_verified=False, policy=POLICY, checks=checks,
        normal_windows=normal_count, normal_false_positive_windows=false_positives,
        normal_rejected_windows=int(matrix[0, 5]), normal_false_positive_window_rate=false_positive_rate,
        min_class_recall=float(recalls.min()), per_class_recall=dict(zip(LABELS, recalls.tolist())),
        macro_f1=macro, input_coverage=float(covered.mean()), rejected_windows=int((~covered).sum()),
        confusion_columns=LABELS+['REJECTED_INPUT'], confusion_matrix=matrix.tolist(),
        rejected_windows_count_against_recall=True, not_events_per_hour=True)


def select(train, train_labels, validation, validation_labels, seed):
    candidates, successful = [], []
    for index, setting in enumerate(SETTINGS):
        model = MLPClassifier(hidden_layer_sizes=(32, 16), activation='relu', solver='lbfgs',
            random_state=seed, max_iter=1500, max_fun=30000, alpha=setting['alpha'], early_stopping=False)
        weights = np.where(train_labels == 0, setting['normal_weight'], 1.0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ConvergenceWarning)
            model.fit(train, train_labels, sample_weight=weights)
        converged = not any(issubclass(item.category, ConvergenceWarning) for item in caught)
        result = report(validation_labels, model.predict_proba(validation), np.ones(len(validation), dtype=bool))
        candidates.append(dict(index=index, setting=setting, converged=converged, validation=result))
        if converged:
            both = result['checks']['normal_false_positive'] and result['checks']['every_class_recall']
            score = (both, result['macro_f1']-2*result['normal_false_positive_window_rate'], result['min_class_recall'], -index)
            successful.append((score, index, model))
    if not successful:
        raise RuntimeError('No predeclared training candidate converged')
    unused, index, model = max(successful, key=lambda item: item[0])
    return model, dict(schema='cabinet-model-selection-v1', selected_index=index, candidates=candidates,
        selection_split='VALIDATION_ONLY', test_used_for_selection=False, settings=SETTINGS,
        architecture=[39, 32, 16, 5], policy=POLICY,
        objective='prefer normal FP/recall gates, then macroF1 - 2*normalFP, minimum recall, fixed order')


def input_calibration(train):
    train = np.asarray(train)
    if train.ndim != 2 or train.shape[1] != 39 or not np.all(np.isfinite(train)):
        raise ValueError('Only finite standardized training data may set input calibration')
    radius = max(float(np.max(np.abs(train)))*1.25, 1.0)
    return dict(rmin=-radius, rmax=radius)
