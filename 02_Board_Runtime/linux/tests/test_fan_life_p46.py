import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from cabinet import fan_life as life
from cabinet.web import server


def observation(t,rpm=6000,pwm=4000,temp=30,boot='fan/collector',latched=None,active=None):
    return {'observation':{'link':'ONLINE','received_at':t,'boot':boot,
        'frame':{'state':'RECEIVED_REAL','test':False},
        'status':{'uptime_ms':int(round(t*1000)), 'measured_rpm':rpm,'applied_pwm_counts':pwm,
                  'requested_rpm':6000,'temp_raw_1_16_C':temp*16,'latched':latched or [],
                  'active':active or [],'input_validity':{'rpm':True,'temperature':True}}}}

class LifeTests(unittest.TestCase):
    def setUp(self):
        self.c=life.initial_config('fan');self.t=life.Tracker(copy.deepcopy(self.c));self.clock=10.
    def sample(self,**kwargs):
        self.clock=round(self.clock+.2,2)
        return self.t.update(observation(self.clock,**kwargs),self.clock,1700000000+self.clock)
    def plateau(self,**kwargs):
        for i in range(26):s=self.sample(**kwargs)
        return s
    def test_nominal_is_not_measured_estimate(self):
        s=self.sample(pwm=0);e=s['estimate']
        self.assertIsNone(e['estimated_remaining_h']);self.assertEqual(e['kind'],'NOMINAL_ONLY')
        self.assertFalse(s['control_authority']);self.assertFalse(s['lifetime_qualified'])
    def test_actual_pwm_not_requested_rpm(self):
        self.plateau(pwm=3999);self.assertEqual(len(self.t.ledger['points']),0)
    def test_manual_notification_does_not_create_life_fault(self):
        d=observation(11,pwm=2000,active=['SOFT_PS'])
        d['observation']['status']['raw_words']=[0]*31+[0x00520116]
        self.t.update(d,11,1700000011)
        self.assertEqual(self.t.ledger['events'],[])
        d=observation(12,pwm=2000,active=['SOFT_PS','OVERSPEED'])
        d['observation']['status']['raw_words']=[0]*31+[0x00520116]
        self.t.update(d,12,1700000012)
        self.assertEqual(self.t.ledger['events'][0]['causes'],['OVERSPEED'])
    def test_other_notification_sources_remain_visible(self):
        d=observation(11,pwm=2000,active=['SOFT_PS'])
        d['observation']['status']['raw_words']=[0]*31+[0x00510116]
        self.t.update(d,11,1700000011)
        self.assertEqual(self.t.ledger['events'][0]['causes'],['SOFT_PS'])
    def test_reference_and_linear_decay(self):
        e=self.plateau()['estimate'];self.assertEqual(e['reference_rpm'],6000)
        self.sample(pwm=0);e=self.plateau(rpm=5400)['estimate']
        self.assertAlmostEqual(e['estimated_remaining_h'],2500,places=6)
        self.assertAlmostEqual(e['speed_loss_percent'],10)
    def test_endpoint(self):
        self.plateau();self.sample(pwm=0);e=self.plateau(rpm=4800)['estimate']
        self.assertEqual(e['estimated_remaining_h'],0)
    def test_faster_measurement_does_not_add_hours(self):
        self.plateau();self.sample(pwm=0);e=self.plateau(rpm=6100)['estimate']
        self.assertLess(e['estimated_remaining_h'],5000)
    def test_latest_three_rechecks_reject_single_spike(self):
        self.plateau()
        for rpm in [5400,5400,4800]:self.sample(pwm=0);s=self.plateau(rpm=rpm)
        self.assertEqual(s['estimate']['latest_rpm'],5400)
    def test_no_reference_from_invalid_stale_test_or_protected_data(self):
        for variant in ['stale','test','fg','protected']:
            self.setUp()
            for i in range(30):
                self.clock+=.2;d=observation(self.clock)
                if variant=='stale':d['observation']['received_at']-=2
                elif variant=='test':d['observation']['frame']['test']=True
                elif variant=='fg':d['observation']['status']['input_validity']['rpm']=False
                else:d['observation']['status']['latched']=['OVERCURRENT']
                self.t.update(d,self.clock,1700000000+self.clock)
            self.assertEqual(self.t.ledger['points'],[],variant)
    def test_unstable_window(self):
        for i in range(40):self.sample(rpm=4800 if i%2 else 6000)
        self.assertEqual(self.t.ledger['points'],[])
    def test_duplicate_and_boot_gap_do_not_invent_hours(self):
        self.sample(pwm=0);self.sample(pwm=0)
        before=self.t.ledger['operating_seconds'];d=observation(self.clock,pwm=0)
        self.t.update(d,self.clock+.1,1700000000);self.assertEqual(self.t.ledger['operating_seconds'],before)
        self.clock+=100;self.sample(pwm=0);self.assertEqual(self.t.ledger['operating_seconds'],before)
        self.sample(boot='fan/new',pwm=0);self.assertEqual(self.t.ledger['operating_seconds'],before)
    def test_budget_counts_fan_rotating_even_at_zero_pwm(self):
        for i in range(10):self.sample(pwm=0,rpm=1000)
        self.assertAlmostEqual(self.t.ledger['operating_seconds'],1.8)
    def test_protected_alarm_waits_for_comparable_sample(self):
        self.plateau();self.sample(pwm=0,latched=['OVERCURRENT'])
        event=self.t.ledger['events'][-1];self.assertEqual(event['state'],'WAIT_FULL_SPEED_SAMPLE')
        self.plateau(rpm=5700)
        self.assertEqual(event['state'],'FULL_SPEED_SAMPLE_RECORDED')
        self.assertEqual(self.t.ledger['points'][-1]['event_id'],event['id'])
    def test_timeout_keeps_alarm_evidence(self):
        self.sample(pwm=0,active=['OVERTEMP']);self.clock+=601
        self.sample(pwm=0)
        self.assertEqual(self.t.ledger['events'][-1]['state'],'NO_COMPARABLE_FULL_SPEED_SAMPLE')
    def test_restart_keeps_baseline_hours_no_duplicate_plateau(self):
        self.plateau();before=copy.deepcopy(self.t.ledger)
        self.t=life.Tracker(copy.deepcopy(self.c),json.loads(json.dumps(before)))
        s=self.plateau();self.assertEqual(len(self.t.ledger['points']),1)
        self.assertGreater(s['operating_hours'],before['operating_seconds']/3600)
        self.assertEqual(s['estimate']['reference_rpm'],6000)
    def test_new_reference_preserves_history_and_hours(self):
        self.plateau();hours=self.t.ledger['operating_seconds']
        c=copy.deepcopy(self.c);c.update(revision=2,reference_request=2);self.t.reload_config(c)
        self.assertTrue(self.t.snapshot(self.clock,True)['estimate']['reference_pending'])
        self.plateau(rpm=5900)
        self.assertEqual(len(self.t.ledger['points']),2);self.assertGreater(self.t.ledger['operating_seconds'],hours)
        self.assertEqual(self.t.ledger['reference']['rpm'],5900)
    def test_settings_revision_and_durable_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'config.json';life.atomic(p,self.c)
            r=life.configure(dict(expected_revision=1,nominal_hours=6000,end_speed_ratio=.75),'configure',p)
            self.assertEqual(life.read(p)['revision'],2);self.assertFalse(r['actuator_command_sent'])
            with self.assertRaises(ValueError):life.configure(dict(expected_revision=1),'reference',p)
            life.configure(dict(expected_revision=2),'reference',p)
            self.assertEqual(life.read(p)['reference_request'],2)
    def test_corrupt_ledger_fails_without_reset(self):
        self.plateau();self.t.ledger['points'][0]['rpm']=float('nan')
        with self.assertRaises(ValueError):life.Tracker(self.c,self.t.ledger)
    def test_configuration_status_is_not_a_life_alarm(self):
        self.sample(pwm=0,active=['CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'])
        self.assertEqual(self.t.ledger['events'],[])
    def test_overlapping_causes_are_separate_events_with_shared_full_point(self):
        self.sample(pwm=0,active=['TEMP_WARN'])
        self.sample(pwm=0,active=['TEMP_WARN','CURRENT_HIGH'])
        self.assertEqual(len(self.t.ledger['events']),2)
        self.plateau()
        self.assertTrue(all(e['state']=='FULL_SPEED_SAMPLE_RECORDED' for e in self.t.ledger['events']))
        self.assertEqual(self.t.ledger['points'][-1]['event_ids'],[1,2])
    def test_prior_configuration_record_preserved_but_excluded(self):
        ledger=copy.deepcopy(self.t.ledger)
        ledger['events']=[dict(id=1,time=1700000000,causes=['CONFIG_UNQUALIFIED'],state='WAIT_FULL_SPEED_SAMPLE')]
        ledger['next_id']=2
        t=life.Tracker(self.c,ledger)
        self.assertEqual(t.ledger['events'][0]['state'],'IGNORED_CONFIGURATION_STATUS')
        self.assertIsNone(t.event_pending)
    def test_sensitive_api_keeps_authorization(self):
        token='read-secret';control='c'*40
        srv=server('127.0.0.1',0,object(),token=token,control_token=control)
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        try:
            with patch('cabinet.fan_life.configure',return_value={'state':'SAVED_TO_SD'}) as configure:
                for headers,expected in [({},401),({'Authorization':'Bearer '+token},403),
                    ({'Authorization':'Bearer '+token,'X-Cabinet-Control-Token':control,'Origin':'http://evil'},403),
                    ({'Authorization':'Bearer '+token,'X-Cabinet-Control-Token':control},200)]:
                    conn=http.client.HTTPConnection(*srv.server_address)
                    conn.request('POST','/api/commissioning/fan-life-reference',json.dumps({'expected_revision':1}),dict(headers,**{'Content-Type':'application/json'}))
                    res=conn.getresponse();self.assertEqual(res.status,expected);res.read();conn.close()
                self.assertEqual(configure.call_count,1)
        finally:srv.shutdown();srv.server_close();thread.join()

if __name__=='__main__':unittest.main()
