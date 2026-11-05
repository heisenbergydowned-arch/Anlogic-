"""Private local operator RPC; the display never owns MMIO or command staging."""
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
import threading
import time
from hmi_daily.cabinet.learning_web import strict_json


def peer_uid(connection):
    if sys.platform.startswith('linux'):
        return struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
    if sys.platform=='darwin':
        uid=ctypes.c_uint();group=ctypes.c_uint();function=ctypes.CDLL(None).getpeereid
        function.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)];function.restype=ctypes.c_int
        if function(connection.fileno(),ctypes.byref(uid),ctypes.byref(group))!=0:raise ValueError('Peer identity unavailable')
        return uid.value
    raise ValueError('Verified local peer credentials unavailable')


def context_token(context):
    return hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class ParameterRPC:
    def __init__(self,service,path):
        self.service=service;self.path=Path(path);self.stopping=threading.Event();self.workers=[];self.slots=threading.BoundedSemaphore(4)
        if not self.path.is_absolute() or len(os.fsencode(str(self.path)))>100:raise ValueError('Short absolute private operator socket required')
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        info=self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise ValueError('Private owned operator directory required')
        self.owner_fd=os.open(str(self.path)+'.owner.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        self.identity=None;self.listener=None
        try:
            owner=os.fstat(self.owner_fd)
            if not stat.S_ISREG(owner.st_mode) or owner.st_uid!=os.geteuid() or owner.st_mode&0o077:
                raise ValueError('Private regular operator ownership lock required')
            try:fcntl.flock(self.owner_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('An operator owner is still active')
            self.remove_stale_socket()
            self.listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            self.listener.bind(str(self.path));self.path.chmod(0o600)
            info=self.path.lstat();self.identity=(info.st_dev,info.st_ino)
            self.listener.listen(4);self.listener.settimeout(0.1)
            self.thread=threading.Thread(target=self.serve,name='cabinet-local-operator',daemon=True);self.thread.start()
        except BaseException:
            if self.listener is not None:self.listener.close()
            self.unlink_owned_socket();os.close(self.owner_fd);raise

    def unlink_owned_socket(self):
        try:
            info=self.path.lstat()
            if self.identity==(info.st_dev,info.st_ino):self.path.unlink()
        except FileNotFoundError:pass

    def remove_stale_socket(self):
        if not os.path.lexists(str(self.path)):return
        info=self.path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise ValueError('Untrusted existing operator socket')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
            probe.settimeout(0.1)
            try:probe.connect(str(self.path))
            except OSError as failure:
                if failure.errno not in (errno.ECONNREFUSED,errno.ENOENT):raise ValueError('Existing socket owner cannot be excluded')
            else:raise ValueError('An operator listener is still active')
        if os.path.lexists(str(self.path)):
            current=self.path.lstat()
            if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('Operator socket changed during recovery')
            self.path.unlink()

    def dispatch(self,request):
        if (type(request) is not dict or set(request)!={'schema','call_id','operation','payload'}
                or request['schema']!='cabinet-parameter-local-v1' or not re.fullmatch('[a-f0-9]{32}',str(request['call_id']))
                or type(request['payload']) is not dict or self.stopping.is_set()):raise ValueError('Invalid local operator request')
        parameters=self.service.parameters;payload=request['payload'];operation=request['operation'];result=None
        if operation=='status':
            if payload:raise ValueError('Status payload must be empty')
        elif operation=='preview':
            if set(payload)!={'request_id','revision','context_token','setpoint_tenths'} or type(payload['setpoint_tenths']) is not int:
                raise ValueError('Invalid local preview payload')
            context=parameters.context()
            if payload['context_token']!=context_token(context):raise ValueError('Local context changed')
            result=parameters.preview(dict(request_id=payload['request_id'],expected_revision=payload['revision'],context=context,setpoint_C=payload['setpoint_tenths']/10))
        elif operation=='commit':
            result=parameters.commit(payload)
        else:raise ValueError('Unsupported local operation')
        summary=parameters.summary();recent=summary['recent'][-1] if summary['recent'] else {}
        bounds=summary['bounds'];value=summary['setpoint_C'];enabled=summary['enabled'] and type(value) in (int,float)
        fields=dict(schema='parameter-local-v1',call_id=request['call_id'],state=result['state'] if result else 'STATUS',
            enabled=int(enabled),revision=summary['revision'],current_tenths=round(value*10) if enabled else 0,
            minimum_tenths=math.ceil(bounds[0]*10) if enabled else 0,maximum_tenths=math.floor(bounds[1]*10) if enabled else 0,
            context_token=context_token(summary['context']),request_id=(result or recent).get('request_id','-'),
            nonce=result.get('nonce','-') if result else '-',last_state=recent.get('state','NONE'))
        return ''.join(str(key)+'\t'+str(value)+'\n' for key,value in fields.items()).encode()+b'\n'

    def handle(self,connection):
        with connection:
            connection.settimeout(0.5);data=b''
            try:
                if peer_uid(connection)!=os.geteuid():raise ValueError('Local owner required')
                deadline=time.monotonic()+0.5
                while b'\n' not in data:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise ValueError('Request expired')
                    connection.settimeout(remaining);part=connection.recv(1024)
                    if not part or len(data)+len(part)>4096:raise ValueError('Invalid operator message length')
                    data+=part
                line,trailing=data.split(b'\n',1)
                if trailing.strip():raise ValueError('One request per connection required')
                response=self.dispatch(strict_json(line,limit=4096))
            except Exception:
                response=b'schema\tparameter-local-v1\nstate\tREJECTED_NOT_APPLIED\n\n'
            try:connection.sendall(response)
            except OSError:pass
        self.slots.release()

    def serve(self):
        while not self.stopping.is_set():
            try:connection,unused=self.listener.accept()
            except socket.timeout:continue
            except OSError:return
            if not self.slots.acquire(False):connection.close();continue
            self.workers=[worker for worker in self.workers if worker.is_alive()]
            worker=threading.Thread(target=self.handle,args=(connection,),daemon=True);self.workers.append(worker);worker.start()

    def close(self):
        self.stopping.set();self.listener.close();self.thread.join(timeout=1)
        for worker in self.workers:worker.join(timeout=2)
        if self.thread.is_alive() or any(worker.is_alive() for worker in self.workers):raise RuntimeError('Operator RPC did not stop; retain socket for inspection')
        self.unlink_owned_socket();os.close(self.owner_fd)
