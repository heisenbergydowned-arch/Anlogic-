"""Durable event upload, HTTPS verification, exact receipt before queue delete."""
import json
import os
import urllib.parse
import urllib.request
from hmi_daily.cabinet.learning_web import strict_json

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,response,code,message,headers,new_url):return None

class Uplink:
    def __init__(self,config,store):
        self.c=config;self.store=store;self.last_error=None
        self.url=config.get('url')
        self.opener=urllib.request.build_opener(NoRedirect())
        self.backhaul = None
        if config.get('backhaul'):
            from .backhaul import Backhaul
            self.backhaul = Backhaul(config['backhaul'])
            self.opener = self.backhaul
        if self.url:
            u=urllib.parse.urlparse(self.url)
            if not u.hostname or u.username is not None or u.password is not None or u.fragment:
                raise ValueError('Invalid event uplink URL')
            local=u.hostname in ('127.0.0.1','localhost','::1')
            if u.scheme!='https' and not (u.scheme=='http' and local and config.get('loopback_test')):
                raise ValueError('Live event uplink requires HTTPS; HTTP is loopback test only')
            if not local and not os.environ.get(config.get('token_env','CABINET_UPLINK_TOKEN')):
                raise ValueError('Live uplink requires device token from environment')
    def once(self):
        if not self.url:return 0
        count=0
        for item in self.store.pending():
            try:
                headers={'Content-Type':'application/json','Idempotency-Key':item['event_id']+':'+str(item['revision'])}
                token=os.environ.get(self.c.get('token_env','CABINET_UPLINK_TOKEN'))
                if token:headers['Authorization']='Bearer '+token
                data=json.dumps(item['payload'],ensure_ascii=False,allow_nan=False).encode('utf-8')
                request=urllib.request.Request(self.url,data=data,headers=headers,method='POST')
                with self.opener.open(request,timeout=self.c.get('timeout_s',2)) as response:
                    if response.status!=200 or response.headers.get_content_type()!='application/json':
                        raise ValueError('Invalid server receipt response')
                    result=strict_json(response.read(65537),limit=65536)
                if type(result) is not dict or result.get('accepted') is not True or type(result.get('event_revision')) is not int or (result.get('event_id'),result.get('event_revision'))!=(item['event_id'],item['revision']):
                    raise ValueError('Mismatched server receipt')
                self.store.delivered(item['event_id'],item['revision']);count+=1;self.last_error=None
                if self.backhaul:self.backhaul.status['state']='RECEIPT_ACCEPTED'
            except Exception as e:
                self.last_error=type(e).__name__+': '+str(e)
                self.store.retry(item['event_id'],item['revision'],item['attempts']+1)
                break
        return count
