"""Predeclared normal-AE selection and diagnostics; no holdout-driven search."""
import math

CANDIDATES = ((.01, 20261101), (.1, 20261102), (1., 20261103))


def selection_policy():
    return dict(schema='cabinet-normal-quantized-selection-v1',
                candidates=[dict(candidate_index=i, alpha=alpha, seed=seed)
                            for i, (alpha, seed) in enumerate(CANDIDATES)],
                selection_split='calibration',
                selection_metric='quantized_reconstruction_mse',
                inference_path='uint8_onnx_cpu_using_runtime_prepare',
                tie_break='first_predeclared_candidate',
                maximum_candidate_count=len(CANDIDATES),
                maximum_independent_test_evaluations=1,
                test_used_for_training_selection_or_threshold=False)


def reconstruction_metrics(predictions, norm):
    count = len(predictions) * 39
    if not count:
        raise ValueError('EMPTY_RECONSTRUCTION_EVALUATION')
    learned = constant = 0.
    for z, _, output, _ in predictions:
        if len(z) != 39 or len(output) != 39:
            raise ValueError('RECONSTRUCTION_SHAPE_CHANGED')
        for value, quantized in zip(z, output):
            reconstruction = (int(quantized) - norm['output_zero_point']) * norm['output_scale']
            learned += (float(value) - reconstruction) ** 2
            constant += float(value) ** 2
    learned /= count
    constant /= count
    if not math.isfinite(learned) or not math.isfinite(constant):
        raise ValueError('NONFINITE_RECONSTRUCTION_METRIC')
    return dict(quantized_reconstruction_mse=learned, constant_mean_mse=constant,
                improvement_fraction=1 - learned / constant if constant > 0 else None)


def select_candidate(evaluations):
    if len(evaluations) != len(CANDIDATES):
        raise ValueError('INCOMPLETE_PREDECLARED_CANDIDATE_SET')
    baseline = None
    for i, (item, (alpha, seed)) in enumerate(zip(evaluations, CANDIDATES)):
        if (item.get('candidate_index'), item.get('alpha'), item.get('seed')) != (i, alpha, seed):
            raise ValueError('PREDECLARED_CANDIDATE_CHANGED')
        metrics = item['quantized_calibration']
        mse, constant = metrics['quantized_reconstruction_mse'], metrics['constant_mean_mse']
        if not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (mse, constant)):
            raise ValueError('INVALID_CALIBRATION_METRIC')
        if baseline is not None and not math.isclose(constant, baseline, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('CALIBRATION_COMPARISON_CHANGED')
        baseline = constant
    return min(range(len(evaluations)), key=lambda i: evaluations[i]['quantized_calibration']['quantized_reconstruction_mse'])


def validation_status(metrics, false_alarm):
    # Preserve the established strict >10% gain and <=5% false-alarm gates.
    useful = all(v['constant_mean_mse'] > 0 and
                 v['quantized_reconstruction_mse'] < .9 * v['constant_mean_mse']
                 for v in metrics.values())
    if false_alarm > .05:
        return 'FAIL_NORMAL_HOLDOUT_FALSE_ALARM'
    return 'PASS_REAL_NORMAL_ADVISORY_HOST_TRAINING' if useful else 'FAIL_QUANTIZED_LEARNING_GAIN'


def input_quality(predictions, limits, features):
    maxima = [0.] * len(features)
    outside = clipped_rows = clipped_values = 0
    for z, _, _, clipped in predictions:
        maxima = [max(old, abs(float(value))) for old, value in zip(maxima, z)]
        outside += any(abs(float(value)) > limit for value, limit in zip(z, limits))
        clipped_rows += clipped > 0
        clipped_values += int(clipped)
    peak = max(range(len(features)), key=lambda i: maxima[i])
    return dict(rows=len(predictions), input_clipped_rows=clipped_rows,
                input_clipped_values=clipped_values, outside_train_domain_rows=outside,
                maximum_abs_z=maxima[peak], maximum_abs_z_feature=features[peak],
                diagnostic_only=True, rows_removed_or_relabeled=0)
