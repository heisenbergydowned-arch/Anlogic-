"""Subscriber timing tests use synthetic packets, never hardware evidence."""
import json
import unittest
from unittest.mock import patch
import test_local_display as fixtures

class AdvisoryRefreshTests(unittest.TestCase):
    setUp = fixtures.LocalDisplayTests.setUp
    tearDown = fixtures.LocalDisplayTests.tearDown
    packet = fixtures.LocalDisplayTests.packet
    process = fixtures.LocalDisplayTests.process

    def test_real_input_is_published_before_learning_and_keeps_its_timestamp(self):
        original=self.observer.learner.observe
        observed=[]
        def observe(*args,**kwargs):
            document=json.loads((self.root/'view/npu_input.json').read_text())
            observed.append(document['observation'])
            return original(*args,**kwargs)
        with patch.object(self.observer.learner,'observe',side_effect=observe):self.process()
        self.assertEqual(len(observed),1)
        latest=json.loads((self.root/'view/state.json').read_text())['observation']
        for key in ('received_at','boot','sequence','frame','status','feature_words','bench','normal_reference_guard'):
            self.assertEqual(observed[0][key],latest[key])
        before=(self.root/'view/npu_input.json').read_bytes()
        self.observer.refresh_advisories(self.now+.03)
        self.assertEqual((self.root/'view/npu_input.json').read_bytes(),before)

    def test_offline_is_published_to_both_consumers(self):
        self.process();self.observer.offline('COLLECTOR_STALE')
        inference=json.loads((self.root/'view/npu_input.json').read_text())
        self.assertIsNone(inference['observation'])
        self.assertEqual(inference['display'],{'link':'ERROR','message':'COLLECTOR_STALE'})
        self.assertIsNone(json.loads((self.root/'view/state.json').read_text())['observation'])

    def test_backlog_processes_every_packet_but_only_publishes_the_latest_view(self):
        first=self.packet();second=self.packet()
        second['sequence']=first['sequence']+1
        second['received_at']=first['received_at']+.01
        self.observer.submit(first);self.observer.submit(second)
        original=self.observer.learner.observe
        with patch.object(self.observer.learner,'observe',wraps=original) as observe, \
             patch.object(self.observer,'compose_advisories',wraps=self.observer.compose_advisories) as compose:
            self.observer.step(self.observer.queue.get_nowait(),self.now)
            self.assertEqual(observe.call_count,1)
            self.assertEqual(compose.call_count,0)
            self.assertFalse((self.root/'view/state.json').exists())
            self.observer.step(self.observer.queue.get_nowait(),self.now+.01)
            self.assertEqual(observe.call_count,2)
            self.assertEqual(compose.call_count,1)
        displayed=json.loads((self.root/'view/state.json').read_text())['observation']
        self.assertEqual(displayed['sequence'],second['sequence'])
        self.assertEqual(displayed['received_at'],second['received_at'])

    def test_continuously_busy_queue_cannot_starve_display_publication(self):
        first=self.packet();pending=self.packet()
        self.observer.submit(pending)
        self.observer.step(first,self.now)
        self.assertFalse((self.root/'view/state.json').exists())
        later=self.packet();later['sequence']=first['sequence']+1
        later['received_at']=first['received_at']+.25
        self.observer.step(later,self.now+.25)
        self.assertFalse(self.observer.queue.empty())
        latest=json.loads((self.root/'view/state.json').read_text())['observation']
        self.assertEqual(latest['received_at'],later['received_at'])

    def test_result_arrives_between_packets_without_refreshing_the_measurement(self):
        response={'panel_nn_present':'1','panel_nn_valid':'0','panel_nn_count':'0'}
        def fields(*args,**kwargs):return dict(response)
        with patch('cabinet.local_display.normal_npu_fields',fields),patch.object(self.observer.learner,'observe',wraps=self.observer.learner.observe) as observe:
            self.process()
            before=json.loads((self.root/'view/state.json').read_text());calls=observe.call_count
            response.update(panel_nn_valid='1',panel_nn_count='11',panel_nn_state='BASELINE_MATCH')
            self.observer.poll(self.now+.03)
            after=json.loads((self.root/'view/state.json').read_text())
            self.assertEqual(after['display']['panel_nn_count'],'11')
            self.assertEqual(after['observation'],before['observation'])
            self.assertEqual(after['display']['sequence'],before['display']['sequence'])
            self.assertEqual(observe.call_count,calls)

    def test_offline_clears_cached_advisories_and_cannot_republish_old_packet(self):
        with patch('cabinet.local_display.normal_npu_fields',return_value={'panel_nn_present':'1','panel_nn_valid':'1','panel_nn_count':'12'}):
            self.process();self.observer.poll(self.now+1.1)
            before=(self.root/'view/state.json').read_bytes()
            self.observer.poll(self.now+1.2)
            after=json.loads((self.root/'view/state.json').read_text())
            self.assertIsNone(after['observation']);self.assertEqual(after['display']['link'],'ERROR')
            self.assertIsNone(self.observer.advisory_sample)
            self.assertEqual((self.root/'view/state.json').read_bytes(),before)

    def test_unchanged_result_does_not_republish_or_touch_source_sequence(self):
        with patch('cabinet.local_display.normal_npu_fields',return_value={'panel_nn_present':'1','panel_nn_valid':'0'}):
            self.process()
            with patch('cabinet.local_display.publish') as publish:
                self.observer.poll(self.now+.03);self.observer.poll(self.now+.06)
                publish.assert_not_called()

    def test_pending_sensor_packet_takes_priority_over_advisory_refresh(self):
        self.process()
        self.observer.submit(self.packet())
        with patch('cabinet.local_display.publish') as publish, patch.object(self.observer,'compose_advisories') as compose:
            self.observer.refresh_advisories(self.now+.03)
            compose.assert_not_called();publish.assert_not_called()

    def test_cached_snapshot_is_independent_of_the_producer_and_next_packet(self):
        packet=self.packet()
        packet['feature_words']=list(packet['feature_words'])
        self.observer.submit(packet)
        packet['status']['measured_rpm']=12345
        packet['feature_words'][0]=12345
        self.observer.step(self.observer.queue.get_nowait(),self.now)
        cached=json.loads(json.dumps(self.observer.advisory_sample))
        self.assertNotEqual(cached['status']['measured_rpm'],12345)
        self.assertNotEqual(cached['feature_words'][0],12345)
        with patch('cabinet.local_display.normal_npu_fields',return_value={'panel_nn_valid':'0','panel_nn_count':'9'}):
            self.observer.refresh_advisories(self.now+.03)
        self.assertEqual(self.observer.advisory_sample,cached)
        after=json.loads((self.root/'view/state.json').read_text())
        self.assertEqual(after['observation'],cached)

