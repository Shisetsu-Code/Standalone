"""Fresh official FANPAGE_DEMO sessions; captured transport credentials are unused."""
import json
import re
import time
import uuid
from urllib.parse import urlencode
import requests
import websocket
from nolimit_protocol import PROTOCOL,rc4_hex,lzw_decode,redact

STATIC='https://demo.nolimitcdn.com/games/'
OPEN='https://demo.nolimitcity.com/EjsFrontWeb/fs'


def valid_public_version(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}(?:[-+.][A-Za-z0-9][A-Za-z0-9.-]*)?',value) is not None


class Nolimit:
    def __init__(self,code):
        if not re.fullmatch('[A-Za-z0-9_]+',code):raise ValueError('invalid_game_code')
        self.code=code;self.http=requests.Session();self.ws=None;self.trace=[];self.number=0;self.uuid=uuid.uuid4().hex[:10];self.remember={};self.on_checkpoint=None
        info=self.http.get(STATIC+code+'/info.json',timeout=25);info.raise_for_status();self.info=info.json();self.version=self.info['version']
        if not valid_public_version(self.version):raise ValueError('unexpected_public_version')
        response=self.http.post(OPEN,data={'action':'open_game','clientString':'FANPAGE_DEMO','language':'en','gameCodeString':code+'@desktop'},timeout=25)
        response.raise_for_status();launch=response.json()
        if launch.get('url')!='https://demo.nolimitcity.com/EjsGameWeb/gs' or not re.fullmatch('[0-9a-f]+',launch.get('key','')):raise ValueError('unrecognized_public_demo_launch')
        self.key=launch['key']
        self.ws=websocket.create_connection('wss://demo.nolimitcity.com/EjsGameWeb/ws/game?'+urlencode({'data':self.key}),origin='https://demo.nolimitcdn.com',timeout=25)
        self.init=self.call('init',{'type':'init'})
        if self.init.get('init')!='ok' or self.init.get('game',{}).get('nextMode')!='NORMAL':raise ValueError('not_a_fresh_public_demo')
        if self.init.get('currency',{}).get('code')!='EUR':raise ValueError('unexpected_demo_currency')
        self.balance=self.init['balance'];self.game=self.init['game']

    def minimum_bet(self,control=None):
        levels=self.init.get('betLevels',{})
        mode=(control or {}).get('game_mode') or self.init['game'].get('playedCapMode')
        if mode in levels:levels=levels[mode]
        levels=levels.get('availableBetLevels',levels.get('betLevels',[]))
        if control and control.get('feature_name'):
            features=self.init.get('featureBetLevels',{})
            if mode in features:features=features[mode]
            levels=features.get(control['feature_name'],levels)
        from decimal import Decimal
        if not levels:raise ValueError('published_bet_levels_missing')
        result=min(levels,key=lambda v:Decimal(str(v)))
        if Decimal(str(result))<=0:raise ValueError('invalid_published_minimum')
        return str(result)

    def call(self,kind,content):
        if kind not in ('init','normal','balance'):raise ValueError('unsupported_native_request')
        request={'type':kind,'content':content,'protocol':PROTOCOL,'id':self.uuid+'-'+str(self.number),'data':dict(self.remember)};self.number+=1
        if kind=='init':request['gameClientVersion']=self.version
        step={'request':redact(request),'responses':[],'started':time.time()};self.trace.append(step)
        if self.on_checkpoint:self.on_checkpoint()
        # One send only. A timeout never retries a potentially accepted wager.
        self.ws.send(rc4_hex(self.key,json.dumps(request,separators=(',',':'))))
        for _ in range(100):
            raw=self.ws.recv()
            if not isinstance(raw,str):raise ValueError('unexpected_binary_frame')
            response=json.loads(lzw_decode(raw));step['responses'].append(redact(response))
            if response.get('extPlayerKey'):self.remember['extPlayerKey']=response['extPlayerKey']
            if response.get('id')==request['id']:
                step['elapsed_ms']=round((time.time()-step['started'])*1000,1)
                if self.on_checkpoint:self.on_checkpoint()
                if response.get('error'):raise ValueError('provider_error:'+str(response['error']))
                if response.get('balance') is not None:self.balance=response['balance']
                if isinstance(response.get('game'),dict):self.game=response['game']
                return response
        raise ValueError('matching_native_reply_missing')

    def close(self):
        if self.ws:self.ws.close(timeout=2)
        self.http.close()
