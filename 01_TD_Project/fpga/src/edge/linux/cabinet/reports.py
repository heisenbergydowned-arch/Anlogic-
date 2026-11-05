"""Bounded monitoring summaries use the existing durable, interface-bound uplink."""
import hashlib
import json
import math
import time


class MonitorReports:
    def __init__(self,store,device,config=None):
        config={} if config is None else config
        if type(config) is not dict or set(config)-{'enabled','interval_s'} or type(config.get('enabled',False)) is not bool:
            raise ValueError('Invalid monitoring report policy')
        self.enabled=config.get('enabled',False);self.interval=config.get('interval_s',60)
        if type(self.interval) is not int or not 10<=self.interval<=3600:raise ValueError('Report interval must be 10..3600 seconds')
        self.store=store;self.device=device;self.rows=[];self.started=None;self.boot=None;self.last_identity=None;self.omitted=0

    def observe(self,document):
        if not self.enabled:return None
        now=time.monotonic();boot=document.get('boot_id')
        if boot!=self.boot:
            self.rows=[];self.started=now;self.boot=boot;self.last_identity=None;self.omitted=0
        if not document.get('valid') or document.get('test') is not False or not boot:return None
        identity=(boot,document.get('frame_id'))
        if identity==self.last_identity:return None
        self.last_identity=identity
        if len(self.rows)>=256:self.rows.pop(0);self.omitted+=1
        self.rows.append(document)
        if self.started is None:self.started=now
        if now-self.started<self.interval:return None
        statistics={}
        units=dict(rpm='RPM',target_rpm='RPM',temperature='degC',current='A',pressure='kPa')
        for name,unit in units.items():
            values=[row['values'][name] for row in self.rows if row.get('measurement_validity',{}).get(name) is True
                    and type(row.get('values',{}).get(name)) in (int,float) and math.isfinite(row['values'][name])]
            statistics[name]=dict(count=len(values),minimum=min(values) if values else None,maximum=max(values) if values else None,
                mean=sum(value/len(values) for value in values) if values else None,unit=unit)
        identity=hashlib.sha256(json.dumps([self.device,boot,self.rows[0]['frame_id'],self.rows[-1]['frame_id']],separators=(',',':')).encode()).hexdigest()
        report=dict(event_id=identity,event_revision=1,device_id=self.device,boot_id=boot,source='MONITOR_REPORT',code='PERIODIC_MONITOR_REPORT',
            state='RECORDED',notify=True,severity_peak=0,severity_current=0,acknowledged=False,
            monitoring=dict(schema='cabinet-monitor-report-v1',samples=len(self.rows),omitted_older_samples=self.omitted,
                first_recorded=self.rows[0]['recorded'],last_recorded=self.rows[-1]['recorded'],recording_clock='PS_WALL_CLOCK_UNVERIFIED',
                statistics=statistics,live_now=False,classification_qualification_granted=False))
        if self.store.storage_health()['state']!='OK':return None
        self.store.event(report);self.rows=[];self.started=now;self.omitted=0
        return identity
