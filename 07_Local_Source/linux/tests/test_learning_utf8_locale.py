"""Regress the board's C-locale HTTP failure without changing its locale or data."""
import codecs
import http.client
import io
import json
import locale
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]

def locale_worker():
    # This must really exercise ASCII defaults. UTF-8 mode/coercion would hide
    # the exact Python 3.6 systemd failure that this regression guards.
    assert codecs.lookup(locale.getpreferredencoding(False)).name=='ascii'
    assert getattr(sys.flags,'utf8_mode',0)==0
    from test_labeled_learning import LabeledLearningTests
    from normal_npu.learning import save,environment
    from normal_npu.live import publish,read_state
    from normal_npu.learning_deploy import run
    from commissioning.workbench import Workbench
    from commissioning.control_jobs import document
    from commissioning.fit import save as fit_save
    from cabinet.web import server
    fixture=LabeledLearningTests();fixture.setUp();web=None
    try:
        phrase='正常工况：风机与全部传感器已连接'
        save(fixture.root/'edge.json',dict(device_id='UNIT',description='中文配置'))
        save(fixture.root/'platform.json',dict(device_id='UNIT',pl_build_id=fixture.h[26],bitstream_sha256='a'*64,description='真实平台说明'))
        workroot=fixture.root/'workbench';jobdir=workroot/'jobs'/'old';jobdir.mkdir(parents=True)
        save(jobdir/'job.json',dict(id='old',state='FAILED',error='历史中文记录'))
        work=Workbench(workroot,fixture.root/'edge.json',state_path=fixture.root/'state.json')
        assert work.jobs['old']['error']=='历史中文记录'
        work.learning=fixture.normal;work.labeled_learning=fixture.store
        service=SimpleNamespace(workbench=work,bench=SimpleNamespace(snapshot=lambda record_limit=None:dict(state='IDLE',controls_enabled=False)),
            public_state=lambda:dict(link='ONLINE',status=fixture.st))
        work.service=service
        web=server('127.0.0.1',0,service,token='r'*32,control_token='w'*32)
        thread=threading.Thread(target=web.serve_forever,daemon=True);thread.start();responses=[]

        def request(method,path,body=None,expected=200):
            headers={'Authorization':'Bearer '+'r'*32,'X-Cabinet-Control-Token':'w'*32,'Content-Type':'application/json'}
            raw=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
            connection=http.client.HTTPConnection('127.0.0.1',web.server_port,timeout=5)
            try:
                connection.request(method,path,body=raw,headers=headers)
                response=connection.getresponse();data=json.loads(response.read().decode('utf-8'))
                assert response.status==expected,(path,response.status,data)
                assert response.headers['Content-Type'].startswith('application/json')
                responses.append(dict(path=path,status=response.status));return data
            finally:connection.close()

        first=request('GET','/api/commissioning/status')
        settings=json.loads(first['documents']['settings.json']);settings['fan_id']='十二伏测试风机'
        request('POST','/api/commissioning/inputs',dict(revision=first['revision'],name='settings.json',content=json.dumps(settings,ensure_ascii=False)))
        later=request('GET','/api/commissioning/status')
        assert json.loads(later['documents']['settings.json'])['fan_id']==settings['fan_id']
        reopened=Workbench(workroot,fixture.root/'edge.json',state_path=fixture.root/'state.json')
        assert json.loads(reopened.documents()['settings.json'])['fan_id']==settings['fan_id']

        status=request('GET','/api/labeled-learning/status')
        body=fixture.body();body['note']=phrase;body['context_fingerprint']=status['labels']['normal']['context_fingerprint']
        job=request('POST','/api/labeled-learning/start',body);assert job['note']==phrase
        path=fixture.store.folder(job['id'])/'job.json'
        assert phrase.encode('utf-8') in path.read_bytes()
        request('GET','/api/labeled-learning/status');request('GET','/api/npu-learning/status');request('GET','/api/commissioning/status')
        cancelled=request('POST','/api/labeled-learning/cancel',{'job_id':job['id']})
        assert cancelled['state']=='CANCELLED' and cancelled['note']==phrase

        # The normal channel must read the same UTF-8 shared job inventory.
        normal=request('GET','/api/npu-learning/status')
        import uuid
        started=request('POST','/api/npu-learning/start',dict(request_id=str(uuid.uuid4()),healthy_confirmed=True,
            context_fingerprint=normal['context_fingerprint']))
        assert request('POST','/api/npu-learning/cancel',{'job_id':started['id']})['state']=='CANCELLED'

        # Claimed ownership, failure and cancellation also deserialize the note.
        body=fixture.body();body['note']='第二次采样：中文备注'
        second=request('POST','/api/labeled-learning/start',body);fixture.store.claim(fixture.worker)
        assert fixture.store.owned(second['id'],fixture.worker)['note']==body['note']
        request('POST','/api/labeled-learning/cancel',{'job_id':second['id']})
        fixture.store.fail(second['id'],fixture.worker,'中文取消原因')
        checked=request('GET','/api/labeled-learning/status')
        assert checked['jobs'][-1]['error']=='中文取消原因'

        # Corrupt persisted bytes must produce HTTP JSON, not a dropped socket
        # that the gateway mistakes for board/network unavailability.
        before=path.read_bytes();path.write_bytes(b'\xff')
        try:
            for route in ('/api/labeled-learning/status','/api/npu-learning/status'):
                result=request('GET',route,expected=503)
                assert result['error']=='learning_status_unavailable' and 'reason' in result
        finally:path.write_bytes(before)
        request('GET','/api/labeled-learning/status')

        # Shared structured I/O must not reintroduce ASCII on another stage.
        publish(fixture.root/'published.json',dict(note=phrase))
        assert read_state(fixture.root/'published.json')['note']==phrase
        fit_save(fixture.root/'fit.json',dict(note=phrase))
        assert document(fixture.root/'fit.json')['note']==phrase
        env=fixture.root/'six.env'
        env.write_bytes(('# 中文环境说明\n'+''.join(k+'=unit\n' for k in ('BUNDLE','BUNDLE_SHA256','LIBRARY','LIBRARY_SHA256','ADMISSION','ADMISSION_SHA256'))).encode('utf-8'))
        assert len(environment(env))==6
        command='import sys;sys.stdout.buffer.write(bytes.fromhex('+repr(phrase.encode('utf-8').hex())+'))'
        result=run([sys.executable,'-c',command],output=fixture.root/'command.log')
        assert result.stdout==phrase and (fixture.root/'command.log').read_bytes()==phrase.encode('utf-8')

        # Private CLI transports also read/write UTF-8 bytes under the same
        # ASCII process locale, without depending on SSH's locale forwarding.
        import npu_learning_cli,labeled_learning_cli
        for module in (npu_learning_cli,labeled_learning_cli):
            payload=json.dumps(dict(operation='status',note=phrase),ensure_ascii=False).encode('utf-8')
            incoming=SimpleNamespace(buffer=io.BytesIO(payload));outgoing=SimpleNamespace(buffer=io.BytesIO())
            with patch.object(module,'Learning',return_value=SimpleNamespace(status=lambda:dict(note=phrase))),\
                    patch.object(sys,'stdin',incoming),patch.object(sys,'stdout',outgoing),patch.object(sys,'argv',['unit-cli']):
                module.main()
            assert json.loads(outgoing.buffer.getvalue().decode('utf-8'))['result']['note']==phrase
        return dict(status='PASS_C_LOCALE_UTF8_IO',default_encoding=locale.getpreferredencoding(False),
            utf8_mode=getattr(sys.flags,'utf8_mode',0),http_requests=len(responses),physical_hardware_used=False,
            chinese_label_note_preserved=True,both_learning_channels=True,structured_corrupt_storage_errors=True,
            workbench_persist_and_reopen=True,cli_utf8_protocol=True)
    finally:
        if web is not None:web.shutdown();web.server_close()
        fixture.doCleanups()

class LearningUTF8LocaleTests(unittest.TestCase):
    def test_chinese_http_lifecycle_under_c_locale_without_utf8_coercion(self):
        env=os.environ.copy();env.update(LC_ALL='C',LANG='C',LANGUAGE='C',PYTHONUTF8='0',PYTHONCOERCECLOCALE='0',
            PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join([str(ROOT/'linux'),str(ROOT/'linux/tests')]))
        env.pop('PYTHONIOENCODING',None)
        completed=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--locale-worker'],
            cwd=str(ROOT),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr.decode('utf-8',errors='replace'))
        report=json.loads(completed.stdout.decode('utf-8'))
        self.assertEqual(report['status'],'PASS_C_LOCALE_UTF8_IO');self.assertEqual(report['utf8_mode'],0)
        self.assertGreaterEqual(report['http_requests'],18)

if __name__=='__main__':
    if sys.argv[1:]==['--locale-worker']:
        print(json.dumps(locale_worker(),ensure_ascii=True))
    else:unittest.main()
