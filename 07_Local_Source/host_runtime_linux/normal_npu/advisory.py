"""Display-only temporal confirmation. Raw scores and acceptance gates stay intact."""
import json
import math

SCHEMA='cabinet-normal-advisory-v1'
STATES=('UNKNOWN','NORMAL','PENDING','WARN','RECOVERING')
MASK=0xffffffff
DEFAULT_WARNING_MS=2000


class Advisory:
    def __init__(self,warning_ms=DEFAULT_WARNING_MS):
        if type(warning_ms) is not int or not 1<=warning_ms<=10000:raise ValueError('Invalid warning confirmation time')
        self.warning_ms=warning_ms
        self.context=None;self.last_id=None;self.last_end=None;self.last_received=None
        self.warning=False;self.normal=False;self.bad_since=None;self.good_since=None
        self.bad_count=0;self.good_count=0
        self.value=self._value('UNKNOWN','NO_VALID_FRAME')

    def _value(self,state,reason,elapsed=0,required=0,samples=0):
        return dict(schema=SCHEMA,state=state,reason=reason,elapsed_ms=elapsed,
                    required_ms=required,samples=samples,warning_latched=self.warning,
                    normal_latched=self.normal and not self.warning)

    def _reset_evidence(self):
        self.normal=False;self.bad_since=self.good_since=None;self.bad_count=self.good_count=0

    def invalidate(self,reason):
        self._reset_evidence()
        self.value=self._value('UNKNOWN',str(reason))
        return dict(self.value)

    def observe(self,result,now):
        if result.get('baseline_eligible') is False:
            # Execute and expose the real reconstruction, but a different PWM
            # operating point is not evidence of health or a confirmed fault.
            self.context=None;self.last_id=self.last_end=self.last_received=None
            self.warning=False
            return self.invalidate('OPERATING_CONDITION_OUTSIDE_BASELINE')
        try:
            received=result['received_at'];updated=result['updated_at'];score=result['score']
            fid=result['frame_id'];end=result['frame_end_ms']
            if (result.get('valid') is not True or result.get('status')!='RUNNING' or
                    any(type(v) not in (int,float) or not math.isfinite(v) for v in (now,received,updated,score)) or
                    not 0<=now-received<=.5 or not 0<=now-updated<=.5 or score<0):
                return self.invalidate('INPUT_STALE_OR_INVALID')
            if any(type(v) is not int or not 0<=v<=MASK for v in (fid,end)):
                return self.invalidate('FRAME_IDENTITY_INVALID')
            context=json.dumps([result['model_sha256'],result['os_boot_id'],result['collector_boot'],result['input_contract']],
                               sort_keys=True,allow_nan=False,separators=(',',':'))
        except (KeyError,TypeError,ValueError):return self.invalidate('ADVISORY_INPUT_MALFORMED')
        changed=self.context is not None and context!=self.context
        if context!=self.context:
            self.context=context;self.last_id=self.last_end=self.last_received=None
            self.warning=False;self._reset_evidence()
        if fid==self.last_id:
            if end!=self.last_end:return self.invalidate('DUPLICATE_FRAME_CHANGED')
            if not 0<=now-self.last_received<=.5:return self.invalidate('DUPLICATE_FRAME_STALE')
            return dict(self.value)
        gap=(self.last_id is not None and
             (((fid-self.last_id)&MASK)!=1 or not 0<((end-self.last_end)&MASK)<=500))
        # Keep confirmed-normal history across at most one second of missed
        # deliveries. A new deviation is still PENDING/WARN, never NORMAL;
        # only a fresh matching inference can return the display to green.
        # Explicit invalidation, changed identity and long gaps still reset it.
        retain_confirmation=(gap and self.normal and not self.warning
                             and 1<((fid-self.last_id)&MASK)<=8 and 0<((end-self.last_end)&MASK)<=1000)
        if gap:
            pending=(self.bad_since,self.bad_count) if retain_confirmation and self.value['state']=='PENDING' else None
            self._reset_evidence()
            if retain_confirmation:
                self.normal=True
                # Bounded missed deliveries do not restart the two-second
                # warning timer while all observed results remain deviating.
                if pending is not None:self.bad_since,self.bad_count=pending
        self.last_id=fid;self.last_end=end;self.last_received=received
        if score>1:
            self.good_since=None;self.good_count=0
            if self.bad_since is None:self.bad_since=end
            self.bad_count+=1;elapsed=(end-self.bad_since)&MASK
            if elapsed>=self.warning_ms and self.bad_count>=3:self.warning=True
            self.value=self._value('WARN' if self.warning else 'PENDING',
                'SUSTAINED_DEVIATION' if self.warning else 'SHORT_DEVIATION',elapsed,self.warning_ms,self.bad_count)
        else:
            self.bad_since=None;self.bad_count=0
            recovering=score<=(.9 if self.warning else 1.)
            if recovering:
                if self.good_since is None:self.good_since=end
                self.good_count+=1;elapsed=(end-self.good_since)&MASK
                if elapsed>=1000:
                    self.warning=False;self.normal=True
            else:self.good_since=None;self.good_count=0;elapsed=0
            if self.normal and not self.warning:self.value=self._value('NORMAL','NORMAL_CONFIRMED')
            else:self.value=self._value('RECOVERING' if self.warning else 'UNKNOWN',
                'NORMAL_RECOVERY' if recovering else 'RECOVERY_THRESHOLD_NOT_MET',elapsed,1000,self.good_count)
        if changed or (gap and not retain_confirmation):
            self.value=self._value('UNKNOWN','CONTEXT_CHANGED' if changed else 'SOURCE_GAP')
        elif retain_confirmation and score<=1 and result.get('state')=='BASELINE_MATCH':
            self.value=self._value('NORMAL','FRESH_MATCH_AFTER_SHORT_GAP')
        return dict(self.value)


def panel_fields(result):
    """Missing/unknown producers never inherit NORMAL from a raw match."""
    out=dict(panel_nn_advisory_valid='0',panel_nn_advisory_state='UNKNOWN',
             panel_nn_advisory_reason='ADVISORY_UNAVAILABLE',panel_nn_advisory_elapsed_ms='0',
             panel_nn_advisory_required_ms='0',panel_nn_advisory_samples='0',
             panel_nn_advisory_normal_latched='0')
    a=result.get('advisory')
    if type(a) is not dict:return out
    if (a.get('schema')!=SCHEMA or a.get('state') not in STATES or type(a.get('reason')) is not str or
            type(a.get('warning_latched')) is not bool or
            any(type(a.get(k)) is not int or not 0<=a[k]<=MASK for k in ('elapsed_ms','required_ms','samples'))):return out
    if a['state']=='NORMAL' and (a['warning_latched'] or result.get('state')!='BASELINE_MATCH' or result.get('score',2)>1):return out
    if a['state'] in ('WARN','RECOVERING') and not a['warning_latched']:return out
    if a['state']=='PENDING' and (a['warning_latched'] or result.get('state')!='BASELINE_DEVIATION'):return out
    out['panel_nn_advisory_valid']='1'
    if (a.get('normal_latched') is True and not a['warning_latched'] and
            (a['state']=='NORMAL' or (a['state']=='PENDING' and 0<=a['elapsed_ms']<a['required_ms']<=DEFAULT_WARNING_MS))):
        out['panel_nn_advisory_normal_latched']='1'
    for key in ('state','reason','elapsed_ms','required_ms','samples'):out['panel_nn_advisory_'+key]=str(a[key])
    return out
