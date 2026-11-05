"""The NPU input publisher stays independent of the display/learning queue."""
import json
import threading
import time
import unittest
import test_local_display as fixtures

class InputWorkerTests(unittest.TestCase):
    setUp=fixtures.LocalDisplayTests.setUp
    packet=fixtures.LocalDisplayTests.packet

    def tearDown(self):
        self.observer.stopping.set()
        worker=self.observer.input_thread
        if isinstance(worker,threading.Thread):
            worker.join(2)
            self.assertFalse(worker.is_alive())
        fixtures.LocalDisplayTests.tearDown(self)

    def start_worker(self):
        self.observer.input_thread=threading.Thread(target=self.observer.run_input,daemon=True)
        self.observer.input_thread.start()

    def wait_document(self,predicate):
        end=time.monotonic()+2
        while time.monotonic()<end:
            try:
                doc=json.loads((self.root/'view/npu_input.json').read_text())
                if predicate(doc):return doc
            except (OSError,ValueError):pass
            time.sleep(.005)
        self.fail('Input worker publication timed out')

    def test_fresh_input_is_published_without_processing_the_ui_queue(self):
        self.start_worker();packet=self.packet();packet['received_at']=time.monotonic()
        packet['control']={'temperature_pwm':{'actual_pwm_percent':30.,'feedback_valid':True}}
        received=packet['received_at'];rpm=packet['status']['measured_rpm']
        self.observer.submit(packet);packet['status']['measured_rpm']=12345
        packet['control']['temperature_pwm']['actual_pwm_percent']=0.
        doc=self.wait_document(lambda d:d.get('observation') is not None)
        self.assertEqual(self.observer.queue.qsize(),1)
        self.assertFalse((self.root/'view/state.json').exists())
        self.assertEqual(doc['observation']['received_at'],received)
        self.assertEqual(doc['observation']['status']['measured_rpm'],rpm)
        self.assertEqual(doc['observation']['control']['temperature_pwm']['actual_pwm_percent'],30.)

    def test_ui_error_cannot_overwrite_healthy_collector_input(self):
        self.start_worker();packet=self.packet();packet['received_at']=time.monotonic()
        self.observer.submit(packet);before=self.wait_document(lambda d:d.get('observation') is not None)
        self.observer.offline('SUBSCRIBER_ERROR')
        self.assertEqual(json.loads((self.root/'view/npu_input.json').read_text()),before)

    def test_disconnection_and_original_timestamp_expiry_clear_input(self):
        self.start_worker();packet=self.packet();packet['received_at']=time.monotonic()-.9
        self.observer.submit(packet)
        self.wait_document(lambda d:d.get('observation') is not None)
        expired=self.wait_document(lambda d:d.get('observation') is None)
        self.assertEqual(expired['display']['message'],'COLLECTOR_STALE')
        offline=self.packet(link='OFFLINE');offline['received_at']=time.monotonic()
        self.observer.submit(offline)
        self.assertIsNone(self.wait_document(lambda d:d.get('observation') is None)['observation'])

    def test_sensor_invalidity_is_not_held_or_replaced_by_old_data(self):
        self.start_worker();packet=self.packet();packet['received_at']=time.monotonic()
        packet['status']['input_validity']['pressure']=False
        self.observer.submit(packet)
        doc=self.wait_document(lambda d:d.get('observation') is not None)
        self.assertFalse(doc['observation']['status']['input_validity']['pressure'])

    def test_test_source_latch_survives_queue_overflow_until_new_session(self):
        self.observer.input_thread=object()  # Enable the bounded queue without a consumer.
        for index in range(24):
            packet=self.packet(test=index==0);packet['received_at']=time.monotonic()
            self.observer.submit(packet)
        while not self.observer.input_queue.empty():last=self.observer.input_queue.get_nowait()
        self.observer.publish_input_packet(last,time.monotonic())
        self.assertEqual(json.loads((self.root/'view/npu_input.json').read_text())['observation']['frame']['state'],'REJECTED_TEST')
        packet=self.packet(boot='test-device/new-session');packet['received_at']=time.monotonic()
        self.observer.submit(packet)
        self.observer.publish_input_packet(self.observer.input_queue.get_nowait(),time.monotonic())
        self.assertEqual(json.loads((self.root/'view/npu_input.json').read_text())['observation']['frame']['state'],'RECEIVED_REAL')

if __name__=='__main__':unittest.main()
