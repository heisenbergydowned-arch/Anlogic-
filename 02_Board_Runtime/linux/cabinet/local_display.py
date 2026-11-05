"""Bounded display/learning subscriber. Never opens or acknowledges hardware."""
import copy
import json
from pathlib import Path
import queue
import sqlite3
import threading
import time

from hmi_daily.cabinet.baseline import BaselineStore, BUSY, Learner, LearningOwnershipError
from hmi_daily.cabinet.learning_rpc import LearningRPC
from hmi_daily.cabinet.learning_web import ClockTrust, WebLearningControl
from hmi_daily.daily import build_daily
from hmi_daily.current_units import CurrentDisplayMean
from hmi_daily.pressure_units import PressureDisplayMean
from hmi_daily.instrument import monitor_fields
from hmi_daily.read_real import sample_record
from hmi_daily.reader import publish, publish_inference, view_state
from .environment import age_environment
from normal_npu.presentation import fields as normal_npu_fields
from labeled_npu.presentation import fields as labeled_npu_fields
from .icm_display import display_fields as icm_display_fields
from .feature_display import raw_feature_fields, verified_sensor_pair_deadline
from .control_display import ControlDisplay


class LocalDisplay:
    def __init__(self, config, output, learning_config, learning_db, clock_factory=ClockTrust, recorder=None):
        self.config = config
        self.output = Path(output)
        self.learning_config = Path(learning_config)
        self.learning_db = Path(learning_db)
        self.clock_factory = clock_factory
        self.recorder = recorder
        self.queue = queue.Queue(maxsize=16)
        self.input_queue = queue.Queue(maxsize=16)
        self.input_thread = None
        self.input_session = None
        self.input_test_seen = False
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.store = self.learner = self.web = self.rpc = self.clock = None
        self.learning_error = None
        self.owner_conflict = False
        self.sequence = 0
        self.last_frame = self.last_received = None
        self.last_packet_at = self.last_source_sequence = self.session = None
        self.test_source_seen = False
        self.previous_uptime = None
        self.last_progress = None
        self.latest_sequence = None
        self.last_offline_reason = None
        self.last_offline_capture = None
        self.hardware_context = None
        self.hardware_frame_id = None
        self.hardware_window_drops = None
        self.hardware_mailbox_drops = None
        self.sensor_pair_since_ms = None
        self.control_display = ControlDisplay()
        self.current_display_mean = CurrentDisplayMean()
        self.pressure_display_mean = PressureDisplayMean()
        self.advisory_base = self.advisory_sample = self.advisory_rendered = None
        self.advisory_refreshed_at = None
        self.view_render_due = None

    def initialize(self):
        try:
            self.rpc = LearningRPC(self.output / 'learning.sock')
            value = json.loads(self.learning_config.read_text(encoding='utf-8'))
            if value.get('device_id') != self.config['device_id']:
                raise ValueError('DEVICE_ID_MISMATCH')
            if any(value.get('contract', {}).get(key) != self.config['contract'].get(key)
                   for key in ('feature_config_id', 'calibration_id', 'sample_mode_id')):
                raise ValueError('LEARNING_CONTRACT_MISMATCH')
            self.store = BaselineStore(self.learning_db)
            self.learner = Learner(self.store, value)
            self.clock = self.clock_factory()
            self.web = WebLearningControl(self.learner, self.clock, context_guard=self.context_guard)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            self.learning_error = str(error)
            self.owner_conflict = isinstance(error, LearningOwnershipError)
            if self.rpc is not None:
                self.rpc.close()
                self.rpc = None
            if self.clock is not None:
                self.clock.close()
                self.clock = None
            if self.store is not None:
                self.store.close()
                self.store = None
            self.learner = self.web = None

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Display subscriber already started')
        self.thread = threading.Thread(target=self.run, name='cabinet-display-learning', daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError('Display subscriber failed to initialize')
        if self.owner_conflict:
            raise LearningOwnershipError(self.learning_error)
        self.input_thread = threading.Thread(target=self.run_input, name='cabinet-npu-input', daemon=True)
        self.input_thread.start()

    def submit(self, packet):
        self.latest_sequence = packet['sequence']
        value = copy.deepcopy(packet)
        if packet.get('link') == 'ONLINE':
            if packet.get('boot') != self.input_session:
                self.input_session = packet.get('boot')
                self.input_test_seen = False
            self.input_test_seen = self.input_test_seen or packet.get('test',False) or bool(packet.get('frame') and packet['frame'].test)
        value['_npu_test_seen'] = self.input_test_seen
        if self.input_thread is not None:
            try:
                self.input_queue.put_nowait(value)
            except queue.Full:
                try:self.input_queue.get_nowait()
                except queue.Empty:pass
                try:self.input_queue.put_nowait(value)
                except queue.Full:pass
        try:
            self.queue.put_nowait(value)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.queue.put_nowait(value)
            except queue.Full:
                pass

    def publish_input_packet(self, packet, now):
        if (packet.get('link') != 'ONLINE' or
                not 0 <= now - packet['received_at'] <= 1):
            publish_inference(self.output, None, 'COLLECTOR_STALE')
            return
        sample = sample_record(packet.get('frame'), packet['status'], packet['mailbox'], packet['feature_words'])
        sample.update(link=packet['link'], received_at=packet['received_at'],
                      boot=packet['boot'], sequence=packet['sequence'],
                      icm_diagnostics=packet.get('icm_diagnostics'),
                      bench=packet.get('bench'), normal_reference_guard=packet.get('normal_reference_guard'))
        control=packet.get('control')
        if type(control) is dict:
            sample['control']={'temperature_pwm':control.get('temperature_pwm')}
        if packet.get('_npu_test_seen'):
            sample['frame']['state'] = 'REJECTED_TEST'
        publish_inference(self.output, sample)

    def run_input(self):
        """No hardware access: publish copied collector packets ahead of UI work."""
        last_received = None
        offline = False
        try:
            while not self.stopping.is_set():
                try:packet = self.input_queue.get(timeout=.025)
                except queue.Empty:packet = None
                try:
                    now = time.monotonic()
                    if packet is not None:
                        self.publish_input_packet(packet, now)
                        last_received = packet['received_at']
                        offline = packet.get('link') != 'ONLINE' or not 0 <= now-last_received <= 1
                    elif last_received is not None and now-last_received > 1 and not offline:
                        publish_inference(self.output, None, 'COLLECTOR_STALE')
                        offline = True
                except (OSError,ValueError,TypeError,KeyError):
                    try:publish_inference(self.output, None, 'INVALID_COLLECTOR_INPUT')
                    except OSError:pass
                    offline = True
        finally:
            try:publish_inference(self.output, None, 'SERVICE_STOPPED')
            except OSError:pass

    def context_guard(self):
        if self.latest_sequence != self.last_source_sequence or not self.queue.empty():
            return 'COLLECTOR_BACKLOG'
        return None

    def hardware_continuity(self, packet):
        context = (packet['boot'], tuple(packet['feature_words'][:3]))
        problem = None
        if self.hardware_context != context:
            if self.hardware_context is not None:
                problem = 'HARDWARE_CONTEXT_CHANGED'
            self.hardware_frame_id = self.hardware_window_drops = self.hardware_mailbox_drops = None
            self.hardware_context = context
        mailbox_drops = packet['mailbox'].get('dropped_frames', 0)
        if self.hardware_mailbox_drops is not None and mailbox_drops != self.hardware_mailbox_drops:
            problem = 'HARDWARE_MAILBOX_GAP'
        self.hardware_mailbox_drops = mailbox_drops
        frame = packet.get('frame')
        if frame is not None:
            if self.hardware_frame_id is not None and ((frame.id - self.hardware_frame_id) & 0xffffffff) != 1:
                problem = 'HARDWARE_FRAME_GAP'
            if self.hardware_window_drops is not None and frame.header[23] != self.hardware_window_drops:
                problem = 'HARDWARE_WINDOW_GAP'
            self.hardware_frame_id = frame.id
            self.hardware_window_drops = frame.header[23]
        if problem and self.learner is not None and self.learning_error is None:
            self.learner.invalidate(problem)
        return problem

    def disable_learning(self, reason):
        self.learning_error = reason
        if self.learner is not None:
            try:
                self.learner.invalidate(reason)
            except sqlite3.Error:
                pass
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None

    def offline(self, reason):
        self.current_display_mean.reset()
        self.pressure_display_mean.reset()
        self.advisory_base = self.advisory_sample = self.advisory_rendered = None
        self.advisory_refreshed_at = None
        self.sensor_pair_since_ms = None
        self.view_render_due = None
        if self.learner is not None and self.learning_error is None:
            self.learner.invalidate(reason)
        if self.web is not None:
            self.web.linked = False
        self.last_frame = self.last_received = None
        capture = {}
        if self.recorder is not None:
            from .capture import display_fields
            capture = display_fields(self.recorder.snapshot(), time.monotonic())
        if self.last_offline_reason == reason and self.last_offline_capture == capture:
            return
        self.last_offline_reason = reason
        self.last_offline_capture = capture
        self.sequence += 1
        state = {'sequence': self.sequence, 'link': 'ERROR', 'message': reason}
        state.update(capture)
        if self.input_thread is None:
            publish_inference(self.output, None, reason)
        publish(self.output, state, None)

    def step(self, packet, now):
        self.last_packet_at = packet['received_at']
        self.sequence += 1
        if packet.get('link') != 'ONLINE' or now - packet['received_at'] > 1 or packet['received_at'] > now:
            self.offline('COLLECTOR_STALE')
            return
        self.last_offline_reason = None
        session = packet['boot']
        if self.session is not None and session != self.session:
            self.last_frame = self.last_received = None
            self.test_source_seen = False
            self.previous_uptime = self.last_progress = None
            self.sensor_pair_since_ms = None
        if self.last_source_sequence is not None and packet['sequence'] != self.last_source_sequence + 1:
            # Missing packets can hide a sensor loss/recovery transition.
            self.sensor_pair_since_ms = None
            if self.learner is not None and self.learning_error is None:
                self.learner.invalidate('COLLECTOR_GAP')
        self.session, self.last_source_sequence = session, packet['sequence']
        status = packet['status']
        uptime = status['uptime_ms']
        if self.previous_uptime is not None and uptime < self.previous_uptime and self.previous_uptime - uptime < 0x80000000:
            self.offline('PL_UPTIME_RESTART')
            return
        if uptime != self.previous_uptime:
            self.last_progress = packet['received_at']
        elif now - self.last_progress > 2:
            self.offline('PL_STATUS_STOPPED')
            return
        self.previous_uptime = uptime
        self.hardware_continuity(packet)
        frame = packet.get('frame')
        self.test_source_seen = self.test_source_seen or packet['test'] or bool(frame and frame.test)
        sample = sample_record(frame, status, packet['mailbox'], packet['feature_words'])
        sample.update(link=packet['link'], received_at=packet['received_at'],
                      boot=packet['boot'], sequence=packet['sequence'])
        sample['environment'] = age_environment(packet.get('environment'), (now - packet['received_at']) * 1000)
        sample['icm_diagnostics'] = packet.get('icm_diagnostics')
        sample['vibration_monitor'] = packet.get('vibration_monitor')
        sample['control'] = packet.get('control',{})
        sample['bench'] = copy.deepcopy(packet.get('bench'))
        sample['normal_reference_guard'] = copy.deepcopy(packet.get('normal_reference_guard'))
        if self.test_source_seen:
            sample['frame']['state'] = 'REJECTED_TEST'
        model = packet.get('model')
        contract = packet['feature_words']
        model_fresh = bool(model and not model.get('test') and len(contract) == 17 and
                           model.get('diagnostic_state') not in ('REJECTED_CONFIDENCE', 'REJECTED_MARGIN', 'OUT_OF_DOMAIN') and
                           packet.get('model_state') not in ('REJECTED_CONFIDENCE', 'REJECTED_MARGIN', 'NORMAL_CANDIDATE') and
                           (model.get('feature_config_id'), model.get('calibration_id')) == tuple(contract[:2]) and
                           packet.get('model_fresh'))
        sample['model'] = model if model_fresh else None
        sample['model_formal'] = bool(model_fresh and packet['model_formal'])
        # Let the NPU process this exact source packet while the display and
        # learner assemble their view. Advisory refreshes never replay it.
        if self.input_thread is None:
            publish_inference(self.output, sample)
        baseline = {'state': 'ERROR', 'reason': 'SERVICE_UNAVAILABLE', 'can_start': False,
                    'evidence': {'state': 'INVALID_INPUT', 'score': None, 'level': 0}, 'detail': self.learning_error}
        if self.learner is not None and self.learning_error is None:
            try:
                self.learner.observe(frame, status, packet['feature_words'], session, packet['received_at'])
                if self.test_source_seen:
                    self.learner.invalidate('TEST_SOURCE')
                elif packet['model_required'] and not model_fresh:
                    self.learner.invalidate('MODEL_UNAVAILABLE')
                elif packet['model_formal'] and model_fresh and model.get('label') != 'normal':
                    self.learner.invalidate('MODEL_CONFLICT')
                self.web.update(status, session, packet['received_at'], reported_at=packet['reported_at'])
                self.web.model_available = model_fresh
                baseline = self.learner.snapshot()
                sample['learning_web'] = self.web.snapshot(now)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                self.disable_learning(type(error).__name__)
        state, self.last_frame, self.last_received = view_state(sample, self.last_frame, self.last_received, now, self.sequence)
        sample['baseline'] = baseline
        state.update(build_daily(state, sample, baseline))
        self.current_display_mean.apply(state,sample,now)
        self.pressure_display_mean.apply(state,sample,now)
        sensor_fields = icm_display_fields(packet.get('icm_diagnostics'), now, packet['received_at'], session, self.test_source_seen)
        state.update(sensor_fields)
        if not verified_sensor_pair_deadline(sensor_fields, now):
            self.sensor_pair_since_ms = None
        elif self.sensor_pair_since_ms is None:
            self.sensor_pair_since_ms = uptime
        raw_fields = {'panel_raw_features_valid': '0', 'panel_raw_features_deadline_ms': '0'}
        if not self.test_source_seen:
            raw_fields = raw_feature_fields(self.last_frame, packet['feature_words'], status, now,
                                           packet['received_at'], sensor_fields, self.sensor_pair_since_ms)
        state.update(raw_fields)
        state['panel_collector_context']=sample['boot']+'|'+','.join(str(v) for v in sample['feature_words'])
        # Physical-unit and raw dual-point matrices share the same source gate.
        # The existing C dashboard falls back to independent per-channel XYZ RAW.
        if raw_fields['panel_raw_features_valid'] != '1':
            state['panel_vibration_valid'] = '0'
        state.update(self.control_display.fields(sample,now))
        if self.recorder is not None:
            from .capture import display_fields
            state.update(display_fields(self.recorder.snapshot(), now))
        # NPU results arrive after this observation is published. Retain the
        # exact observation and refresh only advisory presentation between
        # packets; never advance acquisition timestamps or replay learning.
        # submit() already owns a deep snapshot of the packet. This sample is
        # private to the subscriber and is never mutated after publication.
        # Copying it again costs tens of ms on the target and delays acquisition.
        self.advisory_base = dict(state)
        self.advisory_sample = sample
        # Preserve every packet for continuity, learning, and rolling means,
        # but do not serialize/render intermediate views while newer packets
        # are waiting. Publishing each old view can make this queue self-lag.
        if self.view_render_due is None:
            self.view_render_due = now + .2
        if not self.queue.empty() and now < self.view_render_due:
            return
        state = self.compose_advisories(self.advisory_base, self.advisory_sample, now)
        self.advisory_rendered = state
        self.advisory_refreshed_at = now
        self.view_render_due = now + .2
        publish(self.output, state, sample)

    def compose_advisories(self, base, sample, now):
        # Display values are scalars; only this flat mapping is updated here.
        state = dict(base)
        state.update(normal_npu_fields(sample, now, clock=time.monotonic))
        classified = labeled_npu_fields(sample, now, clock=time.monotonic)
        if classified.get('panel_classifier_valid') == '1' or state.get('panel_nn_valid') != '1':
            state.update(classified)
        state.update(monitor_fields(state, sample))
        from .vibration_monitor import panel_fields as vibration_fields
        state.update(vibration_fields(sample.get('vibration_monitor'), time.monotonic()))
        return state

    def refresh_advisories(self, now):
        if (not self.queue.empty() or self.advisory_sample is None or self.last_packet_at is None
                or not 0 <= now - self.last_packet_at <= 1
                or (self.advisory_refreshed_at is not None
                    and now - self.advisory_refreshed_at < .025)):
            return
        state = self.compose_advisories(self.advisory_base, self.advisory_sample, now)
        self.advisory_refreshed_at = now
        if state != self.advisory_rendered:
            publish(self.output, state, self.advisory_sample)
            self.advisory_rendered = state

    def poll(self, now):
        if self.last_packet_at is not None and now - self.last_packet_at > 1:
            self.offline('COLLECTOR_STALE')
        else:
            self.refresh_advisories(now)
        if self.rpc is not None:
            if self.queue.empty():
                self.rpc.poll(self.learner, now, self.web)

    def run(self):
        try:
            self.initialize()
            self.ready.set()
            if self.owner_conflict:
                return
            while not self.stopping.is_set():
                try:
                    packet = self.queue.get(timeout=0.025)
                except queue.Empty:
                    packet = None
                try:
                    if packet is not None:
                        self.step(packet, time.monotonic())
                    self.poll(time.monotonic())
                except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
                    self.disable_learning('SUBSCRIBER_ERROR')
                    try:
                        self.offline('SUBSCRIBER_ERROR')
                    except OSError:
                        pass
        finally:
            self.ready.set()
            if self.rpc is not None:
                self.rpc.close()
            if self.learner is not None and self.learner.state in BUSY:
                try:
                    self.learner.finish('ABORTED', 'SERVICE_STOPPED')
                except (OSError, sqlite3.Error):
                    pass
            if self.clock is not None:
                self.clock.close()
            if self.store is not None:
                self.store.close()

    def close(self):
        self.stopping.set()
        if self.input_thread is not None:
            self.input_thread.join(timeout=5)
            if self.input_thread.is_alive():
                raise RuntimeError('NPU input subscriber failed to stop')
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('Display subscriber failed to stop')
