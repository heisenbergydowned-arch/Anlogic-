"""Loopback-only workbench bridge using the user's existing pinned SSH identity."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import subprocess
import threading
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen


def serve(worker,port,upstream):
    # Credentials stay in this process. The page receives no board secrets.
    r=subprocess.run(['ssh']+worker.options+[worker.target,'cat /etc/cabinet/web.env'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=20, encoding='utf-8')
    if r.returncode:raise RuntimeError('Workbench authorization unavailable')
    values=dict(line.split('=',1) for line in r.stdout.splitlines() if line and not line.startswith('#'))
    read=values['CABINET_HMI_TOKEN'].strip('"\'');control=values['CABINET_CONTROL_TOKEN'].strip('"\'')
    def start_tunnel():
        return subprocess.Popen(['ssh']+worker.options+['-o','ExitOnForwardFailure=yes','-N','-L',
            '127.0.0.1:%d:127.0.0.1:8766'%upstream,worker.target],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    worker.start_tunnel=start_tunnel;worker.tunnel=start_tunnel()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def fail(self,status,message):
            raw=json.dumps(dict(error=message)).encode('utf-8');self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def forward(self):
            host='127.0.0.1:%d'%port
            if self.headers.get('Host')!=host:return self.fail(403,'loopback_host_required')
            if self.headers.get('Origin') not in (None,'http://'+host):return self.fail(403,'cross_origin_forbidden')
            # A user click may open this authorized UI from the board's page.
            # Only top-level read-only documents can cross origins; API reads,
            # mutation requests and embedded documents keep the existing gate.
            navigation=(self.command=='GET' and self.path in ('/','/commissioning','/recording')
                        and self.headers.get('Sec-Fetch-Mode')=='navigate'
                        and self.headers.get('Sec-Fetch-Dest')=='document'
                        and self.headers.get('Origin') is None)
            if self.headers.get('Sec-Fetch-Site')=='cross-site' and not navigation:
                return self.fail(403,'cross_site_forbidden')
            data=None
            if self.command=='POST':
                if len(self.headers.get_all('Content-Length',[]))!=1 or self.headers.get('Transfer-Encoding'):
                    return self.fail(400,'invalid_framing')
                try:length=int(self.headers.get('Content-Length','0'))
                except ValueError:return self.fail(400,'invalid_length')
                if not 0<length<=65536:return self.fail(413,'request_size')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.fail(415,'json_required')
                data=self.rfile.read(length)
                if len(data)!=length:return self.fail(400,'truncated_body')
            if not self.path.startswith('/') or self.path.startswith('//'):return self.fail(400,'invalid_path')
            headers={'Authorization':'Bearer '+read,'X-Cabinet-Control-Token':control,'Content-Type':'application/json'}
            if self.command=='POST':headers['Origin']='http://127.0.0.1:%d'%upstream
            try:
                response=urlopen(Request('http://127.0.0.1:%d'%upstream+self.path,data=data,headers=headers,method=self.command),timeout=20)
            except HTTPError as e:response=e
            except (URLError,OSError):return self.fail(503,'board_connection_unavailable')
            with response:
                raw=response.read(8*1024*1024);kind=response.headers.get('Content-Type','application/octet-stream')
                if response.status==200 and self.path=='/commissioning' and 'text/html' in kind:
                    script='''<script>document.querySelectorAll('.connect label').forEach(e=>e.style.display='none');document.getElementById('read-token').value='local-session';document.getElementById('control-token').value='local-session';document.getElementById('connect').textContent='重新连接';document.getElementById('connect').click();</script>'''.encode('utf-8')
                    raw=raw.replace(b'</body>',script+b'</body>')
                self.send_response(response.status);self.send_header('Content-Type',kind)
                for k in ('Content-Security-Policy','X-Content-Type-Options','Content-Disposition'):
                    if response.headers.get(k):self.send_header(k,response.headers[k])
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
        do_GET=forward
        do_POST=forward
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
