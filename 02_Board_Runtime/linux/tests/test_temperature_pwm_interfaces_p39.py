"""Actual HTTP authorization and renderer source/freshness boundaries."""
import copy
import http.client
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cabinet.web import server
from cabinet.control_display import ControlDisplay

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.controller=SimpleNamespace(snapshot=Mock(return_value={'state':'RUNNING'}),save=Mock(return_value={'saved':True,'state':'PENDING'}),alarm_test=Mock(return_value={'status':'ALARM_TEST_SCHEDULED','pwm_changed':False}))
        self.http=server(getattr(self,'bind_host','127.0.0.1'),0,SimpleNamespace(temperature_pwm=self.controller),token='read',control_token='c'*32)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
    def request(self,body=None,auth=True,control=True,origin=None,route=None):
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer read'
        if control:headers['X-Cabinet-Control-Token']='c'*32
        if origin:headers['Origin']=origin
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_address[1],timeout=2)
        c.request('GET' if body is None else 'POST','/api/commissioning/'+(route or ('temperature-pwm-'+('status' if body is None else 'save'))),None if body is None else json.dumps(body),headers)
        r=c.getresponse();result=r.status,json.loads(r.read()),dict(r.getheaders());c.close();return result
    def test_read_requires_auth_and_does_not_mutate(self):
        self.assertEqual(self.request(auth=False)[0],401)
        status,value,headers=self.request();self.assertEqual((status,value),(200,{'state':'RUNNING'}))
        self.assertEqual(headers['Cache-Control'],'no-store');self.controller.save.assert_not_called()
    def test_write_requires_separate_authorization_and_same_origin(self):
        for options,expected in [({'auth':False},401),({'control':False},403),({'origin':'https://foreign.invalid'},403)]:
            self.assertEqual(self.request({},**options)[0],expected)
        self.controller.save.assert_not_called()
        self.assertEqual(self.request({'expected_revision':1})[0],202)
        self.controller.save.assert_called_once_with({'expected_revision':1})
    def test_alarm_test_requires_authorization_and_does_not_save_curve(self):
        self.assertEqual(self.request({'duration_s':5},control=False,route='alarm-test')[0],403)
        status,value,_=self.request({'duration_s':5},route='alarm-test')
        self.assertEqual(status,202);self.assertFalse(value['pwm_changed'])
        self.controller.save.assert_not_called()
    def test_save_conflict_and_storage_failure_not_reported_as_applied(self):
        self.controller.save.side_effect=ValueError('CONFIG_CHANGED');self.assertEqual(self.request({})[0],409)
        self.controller.save.side_effect=OSError('SD failure');self.assertEqual(self.request({})[0],503)

class WildcardHTTPTests(HTTPTests):
    bind_host='0.0.0.0'
    def test_remote_peer_rejected_even_with_both_tokens(self):
        original=self.http.get_request
        def remote_peer():
            sock,address=original()
            return sock,('192.0.2.1',address[1])
        self.http.get_request=remote_peer
        self.assertEqual(self.request({})[0],403)
        self.controller.save.assert_not_called()

class DisplayTests(unittest.TestCase):
    def sample(self):
        raw=[0]*32;raw[7]=1600
        return dict(boot='b1',received_at=100,link='ONLINE',frame={},status=dict(raw_words=raw,applied_pwm_counts=1600),control=dict(
            temperature_pwm=dict(settings=dict(low_C=25,high_C=80,revision=2),state='RUNNING',hardware_armed=True,
                target_pwm_percent=50,target_source='FPGA_TPW1_READBACK',feedback_valid=True,observed_at=99.8)))
    def test_actual_target_and_original_deadline_are_distinct(self):
        p=ControlDisplay().fields(self.sample(),100.1)
        self.assertEqual(p['panel_control_pwm_percent'],'40.00');self.assertEqual(p['panel_temperature_pwm_target_percent'],'50.00')
        self.assertEqual(p['panel_temperature_pwm_deadline_ms'],'100800');self.assertEqual(p['panel_control_enabled'],'0')
        self.assertEqual(p['panel_control_settled'],'0')
    def test_stale_or_unverified_target_cannot_become_curve(self):
        for edit in ({'observed_at':98},{'target_source':'WEB_SETTING'},{'hardware_armed':False},{'feedback_valid':False},{'target_pwm_percent':float('nan')}):
            sample=self.sample();sample['control']['temperature_pwm'].update(edit)
            p=ControlDisplay().fields(sample,100.1);self.assertEqual(p['panel_temperature_pwm_target_valid'],'0')
    def test_fault_remains_visible_without_a_target(self):
        sample=self.sample();sample['control']['temperature_pwm'].update(state='FAULT_LATCHED',faults=['CURRENT_MEAN'])
        p=ControlDisplay().fields(sample,100.1)
        self.assertEqual(p['panel_temperature_pwm_faults'],'CURRENT_MEAN');self.assertEqual(p['panel_temperature_pwm_target_valid'],'0')
    def test_no_thermal_config_preserves_legacy_mode(self):
        sample=self.sample();sample['control']['temperature_pwm']['settings']=None
        self.assertEqual(ControlDisplay().fields(sample,100.1)['panel_temperature_pwm_present'],'0')

if __name__=='__main__':unittest.main()
