"""FCB1 command owner and immutable FRM1 mailbox receiver.

MMIO uses a tiny volatile 32-bit C accessor, never Python bytewise memcpy on
ARM device memory. Hardware opening is explicit; the default backend is mock.
"""
import ctypes
import importlib.util
import os
import secrets
from pathlib import Path
import threading
from .protocol import Frame

def load_fcb1():
    # Source tree layout, or the self-contained delivery package layout.
    root=Path(__file__).resolve().parents[1]
    candidates=[root/'fcb1_client.py']
    path=next((p for p in candidates if p.exists()),None)
    if path is None:raise RuntimeError('Missing frozen FCB1 client')
    spec=importlib.util.spec_from_file_location('fcb1_client',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

FCB1=load_fcb1()

class MMIO:
    def __init__(self, device, library, base=0x80400000):
        if os.name!='posix':raise RuntimeError('MMIO backend requires board Linux')
        if base!=0x80400000:raise ValueError('This bitstream ABI uses base 0x80400000')
        if device.startswith('/dev/uio'):
            sysmap=Path('/sys/class/uio')/Path(device).name/'maps/map0'
            if int((sysmap/'addr').read_text().strip(),0)!=base or int((sysmap/'size').read_text().strip(),0)<65536:
                raise ValueError('UIO resource does not match cabinet MMIO page')
        self.lib=ctypes.CDLL(str(library),use_errno=True)
        self.lib.edge_open.argtypes=[ctypes.c_char_p,ctypes.c_uint64];self.lib.edge_open.restype=ctypes.c_void_p
        self.lib.edge_read.argtypes=[ctypes.c_void_p,ctypes.c_uint32];self.lib.edge_read.restype=ctypes.c_uint32
        self.lib.edge_write.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32];self.lib.edge_write.restype=None
        self.lib.edge_close.argtypes=[ctypes.c_void_p];self.lib.edge_close.restype=None
        self.handle=self.lib.edge_open(os.fsencode(device),base if device=='/dev/mem' else 0)
        if not self.handle:raise OSError(ctypes.get_errno(),'MMIO mapping/ownership failed')
        self.lock=threading.RLock()
    def read(self,address):
        if address%4 or not 0<=address<65536:raise ValueError('MMIO address')
        return self.lib.edge_read(self.handle,address)
    def write(self,address,value):
        if address%4 or not 0<=address<65536 or not 0<=value<=0xffffffff:raise ValueError('MMIO write')
        self.lib.edge_write(self.handle,address,value)
    def close(self):
        if self.handle:self.lib.edge_close(self.handle);self.handle=None

class Controller:
    def __init__(self, registers):
        self.io=registers;self.lock=threading.RLock();self.command_id=None
    def identify(self):
        if (self.io.read(0),self.io.read(4))!=(0x46434231,0x10000):raise RuntimeError('FCB1 identity/version mismatch')
        if (self.io.read(0x1000),self.io.read(0x1004))!=(0x45444731,0x10000):raise RuntimeError('Build lacks EDG1/FRM1 feature link')
        self.boot_cookie=self.io.read(0x1050)
        if self.boot_cookie==0:
            self.boot_cookie=secrets.randbelow(0xffffffff)+1;self.io.write(0x1050,self.boot_cookie)
        if self.io.read(0x1050)!=self.boot_cookie:raise RuntimeError('PL boot-cookie ownership failed')
    def command(self,opcode,payload=0):
        with self.lock:
            if self.command_id is None:self.command_id=self.io.read(0x20)
            self.command_id=(self.command_id+1)&0xffffffff
            self.io.write(0xc,self.command_id);self.io.write(0x10,payload);self.io.write(0x14,opcode)
            status=self.io.read(8)&255
            if status:raise RuntimeError('PL rejected command: '+FCB1.ERRORS.get(status,str(status)))
    def status(self):
        with self.lock:
            self.command(7)
            return FCB1.decode_status([self.io.read(0x700+4*i) for i in range(32)])
    def frame(self):
        with self.lock:
            if not self.io.read(0x1008)&3:return None
            if self.io.read(0x1050)!=self.boot_cookie:raise RuntimeError('PL restarted during receive')
            fid=self.io.read(0x1010)
            header=[self.io.read(0x1100+4*i) for i in range(32)]
            words=[self.io.read(0x1200+4*i) for i in range(39)]
            if header[3]!=fid or self.io.read(0x1010)!=fid or self.io.read(0x1050)!=self.boot_cookie:
                raise RuntimeError('Mailbox/PL boot changed; concurrent reader is forbidden')
            # Validate before ACK. Malformed frames are released with explicit
            # error by the owner so one corrupt frame cannot wedge the link.
            try:return Frame.from_words(header,words)
            finally:self.io.write(0x1010,fid)
    def event(self):
        with self.lock:
            if self.io.read(0x144)==0:return None # status word17, FIFO occupancy
            return [self.io.read(0x80+4*i) for i in range(8)]
    def close(self):self.io.close()

def open_controller(config):
    transport=config['transport']
    if transport['kind']=='uart':
        registers=FCB1.Client(transport['port'])
    elif transport['kind']=='mmio':
        registers=MMIO(transport.get('device','/dev/uio0'),transport['library'])
    else:raise ValueError('Hardware requires explicit uart/mmio backend')
    controller=Controller(registers)
    try:controller.identify();return controller
    except BaseException:registers.close();raise
