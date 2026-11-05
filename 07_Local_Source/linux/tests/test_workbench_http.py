import copy,http.client,json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from cabinet.web import server
from commissioning.workbench import Workbench
from commissioning.fit import save

class WorkbenchHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.base=root/'base.json';save(self.base,{'device_id':'UNIT'})
        self.service=SimpleNamespace(workbench=Workbench(root/'work',self.base))
        self.http=server('127.0.0.1',0,self.service,token='unit-read',control_token='unit-control-'+32*'x')
        threading.Thread(target=self.http.serve_forever,daemon=True).start();self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
    def request(self,path,body=None,auth=True,control=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_address[1],timeout=3)
        h={'Content-Type':'application/json'}
        if auth:h['Authorization']='Bearer unit-read'
        if control:h['X-Cabinet-Control-Token']='unit-control-'+32*'x'
        if origin:h['Origin']=origin
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers=h)
        r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
    def test_page_read_write_and_cross_origin_boundaries(self):
        self.assertEqual(self.request('/commissioning',auth=False)[0],200)
        self.assertEqual(self.request('/api/commissioning/status',auth=False)[0],401)
        state=json.loads(self.request('/api/commissioning/status')[1]);body=dict(revision=state['revision'],name='settings.json',content=state['documents']['settings.json'])
        self.assertEqual(self.request('/api/commissioning/inputs',body,control=False)[0],403)
        self.assertEqual(self.request('/api/commissioning/inputs',body,origin='https://foreign.invalid')[0],403)
        self.assertEqual(self.request('/api/commissioning/inputs',body)[0],200)
        body['name']='../escape';self.assertEqual(self.request('/api/commissioning/inputs',body)[0],409)
    def test_missing_measurements_fail_job_and_never_create_pass(self):
        state=json.loads(self.request('/api/commissioning/status')[1])
        self.assertEqual(self.request('/api/commissioning/fit',dict(revision=state['revision']))[0],200)
        for _ in range(100):
            state=json.loads(self.request('/api/commissioning/status')[1])
            if state['jobs'][0]['state']!='RUNNING':break
            time.sleep(.01)
        self.assertEqual(state['jobs'][0]['state'],'FAILED')
        self.assertFalse(state['physical_closed_loop_accepted'])
        status,data=self.request('/api/commissioning/download');self.assertEqual(status,200);self.assertTrue(data.startswith(b'PK'))
    def test_unknown_operations_and_offline_bench_start_are_refused(self):
        for action in ('shell','apply','arm','reset-protection'):
            self.assertEqual(self.request('/api/commissioning/'+action,{})[0],409)
        self.assertEqual(self.request('/api/commissioning/bench-start',{'preview_id':'x','start_controlled_trial':True})[0],409)
    def test_npu_learning_authorization_and_offline_boundary(self):
        self.assertEqual(self.request('/api/npu-learning/status',auth=False)[0],401)
        state=json.loads(self.request('/api/npu-learning/status')[1])
        self.assertFalse(state['ready']);self.assertFalse(state['manual_export_required'])
        self.assertEqual(self.request('/api/npu-learning/start',{},control=False)[0],403)
        self.assertEqual(self.request('/api/npu-learning/start',{},origin='https://foreign.invalid')[0],403)
        self.assertEqual(self.request('/api/npu-learning/start',{})[0],409)
        self.assertEqual(self.request('/api/npu-learning/shell',{})[0],404)
        self.assertEqual(state['jobs'],[])

if __name__=='__main__':unittest.main()
