"""Explicit test device. Never opens serial/MMIO or controls a real actuator."""
import struct
from .io import FCB1
from .protocol import Frame

class MockController:
    boot_cookie=0x54455354
    def __init__(self,rtl_frames=None):
        self.tick=0;self.commands=[];self.fifo=[];self.frames=rtl_frames or [];self.command_id=0
    def identify(self):pass
    def command(self,op,payload=0):
        if op in (1,2):raise RuntimeError('Mock cannot issue actuator commands')
        self.commands.append((op,payload))
        if op==8 and self.fifo and self.fifo[0][0]==payload:self.fifo.pop(0)
    def status(self):
        self.tick+=1;phase=(self.tick//12)%4
        active=0 if phase==0 else 8 if phase==1 else 9 if phase==2 else 0
        latched=active;severity=3 if active else 0;fan_action=3 if active&1 else 1 if active&8 else 0
        words=[0]*32;words[0]=0x5e00;words[1]=self.tick*128
        if self.frames:
            words[1]=self.frames[min(self.tick-1,len(self.frames)-1)].header[4]+10+max(0,self.tick-len(self.frames))*128
        words[2]=severity | (3<<2) | (fan_action<<6) | ((2 if active else 0)<<9) | 0x2000
        words[3]=active;words[4]=latched;words[7]=0 if active&1 else 2000
        words[8]=6000 | (6000<<16);words[15]=self.tick;words[18]=1;words[21]=16
        words[23]=80*16 if active&8 else 30*16;words[17]=len(self.fifo)
        return FCB1.decode_status(words)
    def frame(self):
        if self.frames:return self.frames[self.tick-1] if self.tick<=len(self.frames) else None
        h=[0]*32;h[:5]=[0x46524d31,0x10000,284,self.tick,self.tick*128]
        h[9]=h[10]=1023*25000;h[11]=h[12]=1024;h[13]=12800;h[14]=51
        h[15]=0x5000;h[16]=1;h[17]=0;h[18]=1;h[19]=3;h[20]=4000;h[21]=100000000
        h[22]=50000;h[24]=128;h[26]=0x202610a0;h[27]=1
        values=[0.1]*39
        values[6:9]=[1.5]*3;values[23:26]=[1.5]*3
        values[9:17]=values[26:34]=[0.125]*8;values[34:39]=[2,0.01,30,0.004,6000]
        return Frame.from_words(h,struct.unpack('<39I',struct.pack('<39f',*values)))
    def event(self):return self.fifo[0] if self.fifo else None
    def close(self):pass
