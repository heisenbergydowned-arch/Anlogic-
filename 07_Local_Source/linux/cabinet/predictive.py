"""Read-only condition selection and evidence-gated degradation forecasting."""
import math
from pathlib import Path
import statistics
from hmi_daily.cabinet.baseline import digest, provenance_context, signature_document, validate_profile
from v4_runtime.qualification import pinned_json
from .freshness import aged_ms
from .protocol import elapsed32


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError('Finite maintenance measurement required')
    return value


class ConditionBank:
    def __init__(self, path, pin, dwell_seconds=5):
        bank = pinned_json(path, pin)
        if bank.get('schema') != 'cabinet-condition-bank-v1' or not isinstance(bank.get('conditions'), list) or not 1 <= len(bank['conditions']) <= 64:
            raise ValueError('Bounded condition bank required')
        if number(dwell_seconds) < 0:
            raise ValueError('Non-negative selection dwell required')
        self.conditions = bank['conditions']
        identities = set()
        for condition in self.conditions:
            profile = validate_profile(condition['baseline'])
            if provenance_context(profile) != condition['context']:
                raise ValueError('Condition context differs from original baseline signature provenance')
            if condition.get('id') in identities or not isinstance(condition.get('id'), str):
                raise ValueError('Unique condition identities required')
            identities.add(condition['id'])
            if set(condition['context']) != {'device_id', 'installation_id', 'feature_config_id', 'calibration_id', 'sample_mode_id', 'pl_build_id', 'protection_config_id'}:
                raise ValueError('Complete condition compatibility context required')
            if condition['context']['device_id'] != profile['device_id']:
                raise ValueError('Baseline belongs to another device')
            if any(type(condition['context'][key]) is not int or not 0 < condition['context'][key] <= 0xffffffff
                   for key in ('feature_config_id','calibration_id','sample_mode_id','pl_build_id','protection_config_id')):
                raise ValueError('Exact nonzero configuration identities required')
            if not condition['context']['calibration_id'] or condition['context']['installation_id'] != profile['installation_id']:
                raise ValueError('Calibrated installation-bound baseline required')
            for key in ['rpm', 'temperature']:
                lower, upper = condition[key]
                if number(lower) >= number(upper):
                    raise ValueError('Empty condition coverage')
            if condition['rpm'][0] < profile['rpm_min'] or condition['rpm'][1] > profile['rpm_max']:
                raise ValueError('Condition exceeds measured baseline coverage')
        self.dwell = dwell_seconds
        self.candidate = self.since = self.last = None

    def reset(self):
        self.candidate = self.since = self.last = None

    def select(self, context, rpm, temperature, now, valid):
        number(now)
        if not valid or (self.last is not None and now < self.last):
            self.reset()
            return dict(state='INVALID_INPUT', condition=None)
        self.last = now
        matches = [condition for condition in self.conditions if condition['context'] == context and
                   condition['rpm'][0] <= number(rpm) < condition['rpm'][1] and
                   condition['temperature'][0] <= number(temperature) < condition['temperature'][1]]
        if len(matches) != 1:
            self.candidate = self.since = None
            return dict(state='AMBIGUOUS' if matches else 'OUT_OF_COVERAGE', condition=None)
        condition = matches[0]
        if self.candidate != condition['id']:
            self.candidate, self.since = condition['id'], now
        if now - self.since < self.dwell:
            return dict(state='WAIT_STABLE', condition=None)
        return dict(state='SELECTED', condition=condition)


class TrendPredictor:
    def __init__(self, threshold=6.0, min_samples=20, min_span_s=600, max_gap_s=90, horizon_s=86400):
        if number(threshold) <= 0 or type(min_samples) is not int or not 3 <= min_samples <= 256:
            raise ValueError('Invalid forecast threshold/sample budget')
        if min(number(min_span_s), number(max_gap_s), number(horizon_s)) <= 0:
            raise ValueError('Positive forecast timing bounds required')
        self.threshold, self.minimum, self.span, self.gap, self.horizon = threshold, min_samples, min_span_s, max_gap_s, horizon_s
        self.rows, self.context = [], None
        self.last_observed = None

    def update(self, context, timestamp, score, valid=True):
        if not valid:
            self.rows, self.context = [], None
            self.last_observed = None
            return dict(state='INVALID_INPUT', remaining_life_s=None)
        number(timestamp); number(score)
        if score < 0:
            raise ValueError('Negative degradation score')
        if context != self.context or (self.last_observed is not None and
                (timestamp <= self.last_observed or timestamp - self.last_observed > self.gap)):
            self.rows = []
        self.context = context
        self.last_observed = timestamp
        if not self.rows or timestamp - self.rows[-1][0] >= self.span / 240:
            self.rows = (self.rows + [(timestamp, score)])[-256:]
        rows = self.rows if self.rows[-1][0] == timestamp else self.rows[-255:] + [(timestamp, score)]
        if len(rows) < self.minimum or timestamp - rows[0][0] < self.span:
            return dict(state='WARMUP', remaining_life_s=None)
        origin = rows[0][0]
        xs, ys = [row[0] - origin for row in rows], [row[1] for row in rows]
        mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
        variance = sum((value - mean_x) ** 2 for value in xs)
        slope = sum((value - mean_x) * (target - mean_y) for value, target in zip(xs, ys)) / variance
        intercept = mean_y - slope * mean_x
        residual = sum((target - intercept - slope * value) ** 2 for value, target in zip(xs, ys))
        total = sum((value - mean_y) ** 2 for value in ys)
        fit = 1 - residual / total if total else 0
        error = math.sqrt(max(0, residual) / (len(xs) - 2) / variance)
        lower, upper = slope - 1.96 * error, slope + 1.96 * error
        if slope <= 0 or lower <= 0 or fit < 0.8:
            return dict(state='NO_RELIABLE_DEGRADATION_TREND', remaining_life_s=None, r_squared=fit)
        distance = max(0, self.threshold - (intercept + slope * xs[-1]))
        crossing = distance / slope
        if crossing > self.horizon:
            return dict(state='BEYOND_FORECAST_HORIZON', remaining_life_s=None)
        return dict(state='THRESHOLD_FORECAST', threshold_crossing_s=crossing,
                    interval_s=[distance / upper, distance / lower], slope_per_second=slope,
                    r_squared=fit, remaining_life_s=None, prediction_kind='degradation_threshold_not_failure_lifetime')


def validate_lifetime_evidence(config, condition, threshold):
    if not config:
        return False
    evidence = pinned_json(config['path'], config['sha256'])
    if evidence.get('schema') != 'cabinet-lifetime-calibration-v1' or evidence.get('source') != 'REAL_RUN_TO_FAILURE':
        raise ValueError('Actual run-to-failure calibration required')
    if evidence.get('condition_id') != condition['id'] or evidence.get('baseline_id') != condition['baseline']['id'] or evidence.get('threshold') != threshold or evidence.get('context') != condition['context']:
        raise ValueError('Lifetime calibration context mismatch')
    if evidence.get('threshold_semantics') != 'OBSERVED_END_OF_LIFE':
        raise ValueError('A warning threshold cannot be called lifetime')
    train, held_out = evidence.get('train_sessions', []), evidence.get('held_out', [])
    if len(set(train)) < 2 or len(held_out) < 2:
        raise ValueError('Independent lifetime sessions required')
    sessions, errors = set(train), []
    for row in held_out:
        if not isinstance(row.get('session'), str) or row['session'] in sessions:
            raise ValueError('Lifetime split leakage')
        sessions.add(row['session'])
        actual, predicted = number(row['actual_seconds']), number(row['predicted_seconds'])
        if actual <= 0 or predicted < 0:
            raise ValueError('Invalid remaining lifetime label')
        errors.append(abs(predicted - actual) / actual)
    if statistics.mean(errors) >= 0.1:
        raise ValueError('Lifetime held-out error must be below ten percent')
    return True


class Maintenance:
    def __init__(self, config):
        self.config = config
        self.bank = ConditionBank(config['bank'], config['bank_sha256'], config.get('dwell_seconds', 5))
        self.predictor = TrendPredictor(**config.get('forecast', {}))
        self.session = self.last_frame = None

    def update(self, state, timestamp):
        frame, status = state.get('frame') or {}, state.get('status') or {}
        values = frame.get('values') or {}
        age=aged_ms(state,'frame_age_ms',require_snapshot=True)
        valid = (state.get('link') == 'ONLINE' and state.get('test') is not True and frame.get('test') is not True and
                 frame.get('quality') == 0 and type(frame.get('calibration_id')) is int and frame['calibration_id']>0 and
                 age is not None and age<=1000 and len(values) == 39)
        if state.get('boot_id')!=self.session:
            self.session=state.get('boot_id');self.bank.reset();self.last_frame=None
            self.predictor.update(None,0,0,False)
        sample_time=state['snapshot_monotonic']-state['frame_age_ms']/1000 if valid else timestamp
        build = frame.get('bitstream_id')
        if isinstance(build, str):
            try:build = int(build, 16)
            except ValueError:build = None
        context = dict(device_id=self.config['device_id'],installation_id=self.config['installation_id'], feature_config_id=frame.get('feature_config_id'),
                       calibration_id=frame.get('calibration_id'), sample_mode_id=frame.get('sample_mode_id'),
                       pl_build_id=build, protection_config_id=status.get('configuration_id',status.get('config_id')))
        valid = valid and all(type(value) in (float, int) and math.isfinite(value) for value in values.values())
        selection = self.bank.select(context, values.get('rpm'), values.get('temp'), sample_time, valid)
        if selection['state'] != 'SELECTED':
            self.predictor.update(None, sample_time, 0, False);self.last_frame=None
            return dict(state=selection['state'], remaining_life_s=None, control_authority=False)
        condition = selection['condition']
        baseline = condition['baseline']
        header, words = state.get('frame_header'), state.get('feature_words')
        if (type(header) is not list or len(header) != 32 or
                any(type(word) is not int or not 0 <= word <= 0xffffffff for word in header) or
                header[:3] != [0x46524d31, 0x10000, 284] or header[19] != 3 or
                (header[3], header[15], header[16], header[17], header[18], header[26]) != (
                    frame.get('frame_id'), frame.get('quality'), frame.get('feature_config_id'),
                    frame.get('calibration_id'), frame.get('sample_mode_id'), build) or
                type(words) is not list or len(words) != 17 or
                any(type(word) is not int or not 0 <= word <= 0xffffffff for word in words) or
                digest(signature_document(baseline['provenance']['config'], header, words,
                    context['protection_config_id'])) != baseline['signature']):
            self.bank.reset()
            self.predictor.update(None, sample_time, 0, False);self.last_frame=None
            return dict(state='BASELINE_CONTEXT_MISMATCH', remaining_life_s=None, control_authority=False)
        from v4_runtime.bundle import FEATURES
        score = max(abs(number(values[name]) - baseline['center'][index]) / baseline['scale'][index]
                    for index, name in enumerate(FEATURES[:38]))
        identity = (state.get('boot_id'), condition['id'], frame.get('frame_id'))
        if identity == self.last_frame:
            return dict(state='WAIT_NEW_FRAME', condition_id=condition['id'], remaining_life_s=None, control_authority=False)
        if (self.last_frame is not None and identity[:2]==self.last_frame[:2] and
                not 0<elapsed32(identity[2],self.last_frame[2])<0x80000000):
            self.bank.reset();self.last_frame=None;self.predictor.update(None,sample_time,0,False)
            return dict(state='INVALID_INPUT',remaining_life_s=None,control_authority=False)
        self.last_frame = identity
        forecast = self.predictor.update((identity[0], condition['id']), sample_time, score)
        calibrated = validate_lifetime_evidence(self.config.get('lifetime'), condition, self.predictor.threshold)
        if calibrated and forecast['state'] == 'THRESHOLD_FORECAST':
            forecast.update(remaining_life_s=forecast['threshold_crossing_s'], prediction_kind='calibrated_remaining_life')
        return dict(forecast, condition_id=condition['id'], baseline_id=baseline['id'], score=score,
                    advisory_qualified=baseline['advisory_qualified'] or calibrated,
                    lifetime_qualified=calibrated, control_authority=False)
