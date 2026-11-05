"""Local HMI plus an optional loopback/platform ingestion endpoint."""
import hmac
import ipaddress
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import json
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from hmi_daily.cabinet.learning_web import strict_json


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    def __init__(self,*arguments,**keywords):
        self.worker_slots=threading.BoundedSemaphore(16)
        super().__init__(*arguments,**keywords)
    def get_request(self):
        connection,address=super().get_request();connection.settimeout(2)
        return connection,address
    def process_request(self,request,client_address):
        if not self.worker_slots.acquire(False):
            self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.worker_slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.worker_slots.release()

def server(host,port,service,*,collector=False,token=None,control_token=None):
    local=host in ('127.0.0.1','localhost','::1')
    if not local and not token:raise ValueError('Non-loopback API requires configured authentication')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def authorized(self):
            return not token or hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
        def do_GET(self):
            route = urlsplit(self.path)
            if route.path in ('/','/history','/parameters','/pressure-calibration','/recording','/diagnostics','/commissioning'):
                name={'/':'index.html','/history':'history.html','/parameters':'parameters.html','/pressure-calibration':'pressure-calibration.html','/recording':'recording.html','/diagnostics':'diagnostics.html','/commissioning':'commissioning.html'}[route.path]
                raw=(Path(__file__).resolve().parents[1]/'static'/name).read_bytes()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                return
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            if route.path=='/api/commissioning/fan-life-status':
                from .fan_life import public_status
                try:return self.reply(200,public_status())
                except (OSError,ValueError,KeyError,TypeError) as error:
                    return self.reply(503,{'error':'fan_life_unavailable','reason':str(error)})
            if route.path=='/api/commissioning/temperature-pwm-status':
                if not hasattr(service,'temperature_pwm'):return self.reply(404,{'error':'not_available'})
                return self.reply(200,service.temperature_pwm.snapshot())
            if route.path=='/api/commissioning/bench-status':
                if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                try:
                    # Snapshot only: never acquire the workspace lock or read
                    # models/documents on the browser's short lease path.
                    bench=getattr(service,'bench',None)
                    value=bench.snapshot() if bench is not None else dict(
                        state='LOCAL_ONLY',hardware_supported=False,controls_enabled=False)
                    return self.reply(200,value)
                except (OSError,ValueError,KeyError,TypeError) as error:
                    return self.reply(503,{'error':'bench_status_unavailable','reason':str(error)})
            if route.path in ('/api/npu-learning/status','/api/labeled-learning/status'):
                if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                try:
                    learning=service.workbench.labeled_learning if route.path.startswith('/api/labeled-') else service.workbench.learning
                    return self.reply(200,learning.status())
                except (OSError,ValueError,KeyError,TypeError) as error:
                    return self.reply(503,{'error':'learning_status_unavailable','reason':str(error)})
            if route.path in ('/api/commissioning/status','/api/commissioning/download'):
                if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                try:
                    if route.path.endswith('/status'):return self.reply(200,service.workbench.status())
                    raw=service.workbench.archive()
                    self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Disposition','attachment; filename="commissioning-evidence.zip"')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                except ValueError as e:return self.reply(409,{'error':str(e)})
                except (OSError,KeyError,TypeError) as e:return self.reply(503,{'error':'workbench_status_unavailable','reason':str(e)})
            if route.path=='/api/capture/status':
                from .capture_web import status
                return self.reply(200,status(service))
            if route.path.startswith('/api/capture/download/'):
                from .capture_web import archive
                try:stream,size=archive(service,route.path.split('/')[-1])
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'invalid_or_unfinalized_recording'})
                except OSError:return self.reply(503,{'error':'recording_storage_unavailable'})
                with stream:
                    self.send_response(200);self.send_header('Content-Type','application/zip')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Disposition','attachment; filename="recording-'+route.path.split('/')[-1]+'.zip"')
                    self.send_header('Content-Length',str(size));self.end_headers();shutil.copyfileobj(stream,self.wfile,65536)
                return
            from .pressure_calibration import PREFIX
            if route.path.startswith(PREFIX+'/'):
                try:
                    if route.query:raise ValueError('Query not supported')
                    return self.reply(200,service.pressure.read(route.path[len(PREFIX):]))
                except KeyError:return self.reply(404,{'error':'not_found'})
                except (ValueError,TypeError):return self.reply(400,{'error':'invalid_pressure_request'})
            if route.path=='/api/parameters':
                if not hasattr(service,'parameters'):return self.reply(404,{'error':'not_available'})
                return self.reply(200,service.parameters.summary())
            if route.path.startswith('/api/history/'):
                try:
                    query=parse_qs(route.query,keep_blank_values=True)
                    if any(len(value)!=1 for value in query.values()):raise ValueError('Duplicate query')
                    if route.path in ('/api/history/samples','/api/history/waveforms'):
                        if set(query)-{'start','end','after','limit'}:raise ValueError('Unknown query')
                        window=dict(start=float(query.get('start',['0'])[0]),end=float(query.get('end',['253402300799'])[0]),
                                    after=int(query.get('after',['0'])[0]),limit=int(query.get('limit',['200'])[0]))
                        return self.reply(200,service.store.history.query(service.config['device_id'],waveforms=route.path.endswith('waveforms'),**window))
                    if route.path == '/api/history/waveform':
                        if set(query)-{'id','format'}:raise ValueError('Unknown query')
                        document=service.store.history.get_waveform(service.config['device_id'],query.get('id',[''])[0])
                        output=query.get('format',['json'])[0]
                        if output=='json':return self.reply(200,document)
                        if output!='csv':raise ValueError('Unknown export format')
                        from .history import csv_replay
                        raw=csv_replay(document).encode('utf-8')
                        self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
                        self.send_header('Content-Disposition','attachment; filename="waveform.csv"')
                        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                        return
                    return self.reply(404,{'error':'not_found'})
                except KeyError:return self.reply(404,{'error':'not_found'})
                except (ValueError,TypeError,OverflowError):return self.reply(400,{'error':'invalid_history_request'})
            if self.path=='/api/status':self.reply(200,service.public_state())
            elif self.path=='/api/events':self.reply(200,service.store.events())
            elif self.path=='/api/reports':self.reply(200,[item for item in (service.store.received() if collector else service.store.events(1000)) if item.get('source')=='MONITOR_REPORT'])
            elif self.path=='/api/maintenance':self.reply(200,service.public_state().get('maintenance') or {'state':'DISABLED','remaining_life_s':None})
            elif self.path=='/api/workorders' and collector:
                self.reply(200,[item for item in service.store.received() if item.get('source') in ('MODEL','PREDICTION')])
            elif self.path=='/api/received' and collector:self.reply(200,service.store.received())
            elif self.path=='/health':self.reply(200,{'alive':True,'link':service.public_state().get('link')})
            else:self.reply(404,{'error':'not_found'})
        def do_POST(self):
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:return self.reply(413,{'error':'length'})
                if len(self.headers.get_all('Content-Length',[]))!=1 or self.headers.get('Transfer-Encoding') is not None:
                    return self.reply(400,{'error':'ambiguous_framing'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'content_type'})
                body=self.rfile.read(length)
                if len(body)!=length:raise ValueError('Truncated request')
                raw=strict_json(body,limit=65536)
                if type(raw) is not dict:raise ValueError('JSON object required')
                from .pressure_calibration import PREFIX
                if self.path in ('/api/parameters/preview','/api/parameters/commit','/api/capture/start','/api/capture/stop') or self.path.startswith(PREFIX+'/') or self.path.startswith('/api/commissioning/') or self.path.startswith('/api/npu-learning/') or self.path.startswith('/api/labeled-learning/'):
                    if (not ipaddress.ip_address(self.client_address[0]).is_loopback
                            or not token or not control_token or control_token==token or len(control_token)<32
                            or not hmac.compare_digest(self.headers.get('X-Cabinet-Control-Token',''),control_token)):
                        return self.reply(403,{'error':'separate_local_control_authorization_required'})
                    origin=self.headers.get('Origin')
                    if origin is not None and origin!='http://'+self.headers.get('Host',''):
                        return self.reply(403,{'error':'cross_origin_write_forbidden'})
                    if self.path in ('/api/npu-learning/start','/api/npu-learning/cancel'):
                        if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                        try:return self.reply(200,service.workbench.action('npu-'+self.path.rsplit('/',1)[1],raw))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path.startswith('/api/npu-learning/'):return self.reply(404,{'error':'unsupported_learning_operation'})
                    if self.path in ('/api/labeled-learning/start','/api/labeled-learning/cancel'):
                        if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                        try:return self.reply(200,service.workbench.action('labeled-'+self.path.rsplit('/',1)[1],raw))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path.startswith('/api/labeled-learning/'):return self.reply(404,{'error':'unsupported_learning_operation'})
                    if self.path in ('/api/commissioning/fan-life-configure','/api/commissioning/fan-life-reference'):
                        from .fan_life import configure
                        try:return self.reply(200,configure(raw,self.path.rsplit('-',1)[-1]))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path=='/api/commissioning/alarm-test':
                        if not hasattr(service,'temperature_pwm'):return self.reply(404,{'error':'not_available'})
                        try:return self.reply(202,service.temperature_pwm.alarm_test(raw))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path=='/api/commissioning/temperature-pwm-save':
                        if not hasattr(service,'temperature_pwm'):return self.reply(404,{'error':'not_available'})
                        try:return self.reply(202,service.temperature_pwm.save(raw))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path.startswith('/api/commissioning/'):
                        if not getattr(service,'workbench',None):return self.reply(404,{'error':'workbench_not_configured'})
                        try:return self.reply(200,service.workbench.action(self.path[len('/api/commissioning/'):],raw))
                        except ValueError as failure:return self.reply(409,{'error':str(failure)})
                    if self.path in ('/api/capture/start','/api/capture/stop'):
                        from .capture_web import command
                        try:result=command(service,self.path.split('/')[-1],raw)
                        except ValueError as failure:return self.reply(400,{'error':'capture_rejected','reason':str(failure)})
                        except RuntimeError:return self.reply(503,{'error':'recorder_rpc_unavailable'})
                        return self.reply(200,result)
                    if self.path.startswith(PREFIX+'/'):
                        try:result=service.pressure.write(self.path[len(PREFIX):],raw)
                        except ValueError as failure:return self.reply(400,{'error':'invalid_pressure_request','reason':str(failure)})
                        return self.reply(202 if result.get('state')=='QUEUED_NOT_APPLIED' else 200,result)
                    if not hasattr(service,'parameters'):raise ValueError('Parameter control unavailable')
                    operation=service.parameters.preview if self.path.endswith('/preview') else service.parameters.commit
                    return self.reply(200,operation(raw))
                elif self.path=='/v1/devices/events' and collector:
                    if raw.get('device_id')!=service.config['device_id']:return self.reply(403,{'error':'device_identity'})
                    self.reply(200,service.store.receive(raw))
                elif self.path=='/api/ack':
                    # Remote ACK is an audit marker. It never silences/resets
                    # PL; current causes/protection stay active.
                    event=service.store.acknowledge(raw['event_id']);self.reply(200,event)
                else:self.reply(404,{'error':'unsupported_command'})
            except (ValueError,KeyError,TypeError,RecursionError,OverflowError):self.reply(400,{'error':'invalid_request'})
            except (OSError,sqlite3.Error):self.reply(503,{'error':'durable_storage_unavailable_command_not_confirmed'})
    return ThreadingHTTPServer((host,port),Handler)
