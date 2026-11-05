"""Bounded display averaging of distinct, fresh collector observations."""
import math
from collections import deque


class SampleMean5s:
    def __init__(self):self.reset()

    def reset(self):
        self.rows=deque();self.total=0.0;self.identity=None;self.stamp=None;self.received=None

    def push(self,value,received,stamp,identity,now):
        if (type(value) not in (int,float) or not math.isfinite(value)
                or type(received) not in (int,float) or not math.isfinite(received)
                or type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-received<=1
                or type(stamp) is not int or not 0<=stamp<=0xffffffff or not identity):
            self.reset();return None
        if (identity!=self.identity or (self.received is not None and
                (received<self.received or received-self.received>1))):self.reset()
        if self.stamp is not None and ((stamp-self.stamp)&0xffffffff)>=0x80000000:
            self.reset();return None
        if stamp!=self.stamp:
            self.rows.append((received,value));self.total+=value
            self.received=received;self.stamp=stamp;self.identity=identity
        if self.received is None or now-self.received>1:
            self.reset();return None
        while self.rows and (self.rows[0][0]<received-5 or len(self.rows)>256):
            self.total-=self.rows.popleft()[1]
        span=self.rows[-1][0]-self.rows[0][0]
        return dict(count=len(self.rows),span_s=span,ready=len(self.rows)>=3 and span>=.5,
                    mean=self.total/len(self.rows),received_at=self.received)
