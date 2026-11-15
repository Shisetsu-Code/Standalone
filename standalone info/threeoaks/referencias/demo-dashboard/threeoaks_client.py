"""Fresh official 3 Oaks FUN demos. Credentials stay outside the HTTP root."""
import json,re,time,uuid,hashlib,math,threading,os
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
import requests
from threeoaks_core import sanitize
from endorphina_run import write_json
from threeoaks_layout import batch_folder

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parent/'threeoaks-private'
RATE_STATE=ROOT/'threeoaks/rate-limit.json'
_lock=threading.Lock()
_next_request=0.0

class RateLimited(Exception):pass

def retry_after_seconds(value,now=None):
    now=time.time() if now is None else now
    try:return max(1,int(value))
    except (ValueError,TypeError):
        try:return max(1,math.ceil(parsedate_to_datetime(value).timestamp()-now))
        except (ValueError,TypeError,OverflowError):return 120

def throttle():
    global _next_request
    with _lock:
        if RATE_STATE.exists():
            state=json.loads(RATE_STATE.read_text(encoding='utf8'))
            if state.get('until',0)>time.time():raise RateLimited('provider_cooldown_active')
        delay=_next_request-time.monotonic()
        if delay>0:time.sleep(delay)
        _next_request=time.monotonic()+1.5

def validated_state(trace):
    state={'context':None,'start':None}
    for step in trace:
        req=step['request'];res=step.get('response',{})
        if step.get('status')!='received' or step.get('http_status')!=200 or req.get('request_id')!=res.get('request_id') or req.get('command')!=res.get('command') or res.get('status',{}).get('code')!='OK' or res.get('user',{}).get('currency')!='FUN':raise ValueError('unvalidated_response_cannot_resume')
        if res.get('context') is not None:state['context']=res['context']
        if req['command']=='start':state['start']=res
    return state

def validate_launcher(config,gid):
    if not re.fullmatch('[a-z0-9_]+',gid):raise ValueError('invalid_game_id')
    o=config['options'];desktop=config['desktop'];queue=o.get('queue','')
    if o.get('provider')!='3oaks' or o.get('project_name')!='betman-demo' or o.get('wl')!='demo' or o.get('game_name')!=gid:raise ValueError('not_exact_official_demo')
    expected='//betman-demo.head.3oaks.com/betman-demo/gs/'+gid+'/desktop/{QUEUE}/demo/'
    if desktop['server_url']!=expected or not re.fullmatch('[0-9a-f]{32}',queue) or not isinstance(o.get('token'),str) or not o['token']:raise ValueError('demo_endpoint_or_credentials_invalid')
    u=urlsplit(desktop['client_url']);pattern=r'/gs/(clients_[a-z0-9_]+)/'+re.escape(gid)+r'/[a-zA-Z0-9_.-]+/'
    match=re.fullmatch(pattern,u.path)
    if u.scheme!='https' or u.netloc!='static.3oaks.com' or u.query or u.fragment or not match:raise ValueError('unverified_public_client_source')
    return {'endpoint':'https:'+expected.replace('{QUEUE}',queue),'client_base':desktop['client_url'],'family':match[1]}

class ThreeOaks:
    def __init__(self,game,save,private_path=None):
        self.game=game;self.save=save;self.http=requests.Session();self.trace=[];self.session_id=None;self.context=None;self.authority={};self.launcher={};self.start=None;self.private_path=Path(private_path) if private_path else None
        if self.private_path and not self.private_path.resolve().is_relative_to(PRIVATE.resolve()):raise ValueError('session_checkpoint_must_be_outside_http_root')

    def checkpoint(self):
        if self.private_path and self.session_id:
            self.private_path.parent.mkdir(parents=True,exist_ok=True)
            write_json(self.private_path,{'game':self.game,'endpoint':self.endpoint,'session_id':self.session_id,'authority':self.authority,'launcher':self.launcher,'start':sanitize(self.start),'trace':self.trace,'context':self.context,'source_proof':getattr(self,'source_proof',None)})
        self.save(self)

    def bootstrap(self):
        gid=self.game['id'];capture=os.environ.get('THREEOAKS_BROWSER_LAUNCHER')
        if capture:
            path=Path(capture).resolve()
            if not path.is_relative_to(PRIVATE.resolve()):raise ValueError('launcher_capture_must_be_private')
            document=json.loads(path.read_text(encoding='utf8'))
            if document['url']!='https://3oaks.com/api/v1/games/'+gid+'/play?lang=en' or not 0<=time.time()-document['captured_at']<600:raise ValueError('browser_launcher_identity_or_freshness')
            config=document['config']
        else:
            r=self.http.get('https://3oaks.com/api/v1/games/'+gid,timeout=30,allow_redirects=False)
            if r.status_code==429:raise RateLimited('public_metadata_rate_limited')
            r.raise_for_status();detail=r.json()['data']
            if detail.get('name')!=gid:raise ValueError('official_game_identity_mismatch')
            if detail.get('is_playable') is not True:raise ValueError('official_demo_not_playable')
            r=self.http.get('https://3oaks.com/api/v1/games/'+gid+'/play?lang=en',timeout=30,allow_redirects=False)
            if r.status_code==429:raise RateLimited('public_launcher_rate_limited')
            r.raise_for_status();marker='})(window, ';at=r.text.rfind(marker+'{')
            if at<0:raise ValueError('official_launcher_config_not_found')
            config,_=json.JSONDecoder().raw_decode(r.text[at+len(marker):])
        native=validate_launcher(config,gid);self.endpoint=native.pop('endpoint');o=config['options']
        self.launcher=dict(native,disable_buy_bonus=o.get('disable_buy_bonus'),disable_gold_bet=o.get('disable_gold_bet'))
        self.authority={'provider':'threeoaks','game_id':gid,'public_demo':True,'fresh_session':True,'launcher_host':'3oaks.com','server_host':'betman-demo.head.3oaks.com','project':'betman-demo','wl':'demo'}
        login=self.call('login',token=o['token'],language='en')
        if login.get('user',{}).get('currency')!='FUN' or not login.get('session_id'):raise ValueError('public_fun_login_not_confirmed')
        self.session_id=login['session_id'];self.authority['currency']='FUN'
        if 'auto' not in login.get('modes',[]):raise ValueError('public_demo_mode_not_published')
        self.start=self.call('start',mode='auto',huid=uuid.uuid4().hex)
        self.context=self.start.get('context');self.checkpoint();return self.start

    def call(self,command,**fields):
        throttle()
        req={'command':command,'request_id':uuid.uuid4().hex,'client_command_timestamp':int(time.time()*1000),**fields}
        if command!='login':req['session_id']=self.session_id
        step={'status':'sending','request':sanitize(req)};self.trace.append(step);self.checkpoint()
        if os.environ.get('THREEOAKS_TRANSPORT')=='browser':
            from threeoaks_browser_bridge import browser_post
            r=browser_post(self.endpoint,req)
        else:r=self.http.post(self.endpoint,json=req,headers={'Origin':'https://3oaks.com','Referer':'https://3oaks.com/'},timeout=40,allow_redirects=False)
        step['http_status']=r.status_code
        if r.status_code==429:
            previous=json.loads(RATE_STATE.read_text(encoding='utf8')) if RATE_STATE.exists() else {};attempts=previous.get('rate_limit_responses',0)+1
            delay=retry_after_seconds(r.headers.get('Retry-After')) if r.headers.get('Retry-After') else min(900,120*2**(attempts-1))
            headers={k:r.headers[k] for k in ['Retry-After','X-RateLimit-Limit','X-RateLimit-Remaining','X-RateLimit-Reset','RateLimit-Reset','Server'] if k in r.headers}
            step.update(status='rejected_http',retry_after_seconds=delay,error='http_rate_limit',rate_limit_headers=headers)
            try:step['rate_limit_body']=sanitize(r.json())
            except ValueError:
                title=re.search(r'<title>([^<]+)</title>',r.text,re.I)
                if title:step['rate_limit_page_title']=title[1][:200]
            write_json(RATE_STATE,{'observed_at':time.time(),'until':time.time()+delay,'retry_after_seconds':delay,'rate_limit_responses':attempts,'headers':headers});self.checkpoint();raise RateLimited('provider_rate_limited_retry_after_'+str(delay))
        r.raise_for_status();response=r.json();step.update(status='received_invalid',response=sanitize(response))
        if response.get('request_id')!=req['request_id'] or response.get('command')!=command:
            self.checkpoint();raise ValueError('native_reply_identity_mismatch')
        if response.get('status',{}).get('code')!='OK':
            step['status']='rejected_native';self.checkpoint();raise ValueError('native_status:'+str(response.get('status',{}).get('code')))
        if response.get('user',{}).get('currency')!='FUN':
            self.checkpoint();raise ValueError('native_currency_not_fun')
        if response.get('context') is not None:self.context=response['context']
        if command=='start':self.start=response
        if command=='login':self.session_id=response['session_id'];self.authority['currency']='FUN'
        step['status']='received'
        self.checkpoint();return response

    def play(self,action):
        return self.call('play',action=action,set_denominator=1,quick_spin=0,sound=False,autogame=False,mobile='0',portrait=False,fullscreen=False,viewportSize='1280x800')

    def source(self):
        url=self.launcher['client_base']+'src/game.js'
        initial=batch_folder()/'initializations'/(self.game['id']+'.json')
        if initial.exists():
            proof=json.loads(initial.read_text(encoding='utf8')).get('source_proof',{});p=ROOT/proof.get('file','missing')
            if proof.get('url')==url and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==proof.get('sha256'):
                self.source_proof=proof;self.checkpoint();return p.read_text(encoding='utf8'),proof
        r=self.http.get(url,timeout=40,allow_redirects=False);r.raise_for_status()
        if not r.text or r.text.lstrip().startswith('<'):raise ValueError('public_game_source_missing')
        path=ROOT/'threeoaks/reference'/(self.game['id']+'.client.js');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(r.content)
        self.source_proof={'file':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(r.content).hexdigest(),'url':url};self.checkpoint();return r.content.decode('utf8'),self.source_proof

    @classmethod
    def resume(cls,private_path,save):
        path=Path(private_path)
        if not path.resolve().is_relative_to(PRIVATE.resolve()):raise ValueError('invalid_private_checkpoint_path')
        d=json.loads(path.read_text(encoding='utf8'));c=cls(d['game'],save,path)
        verified=validated_state(d['trace'])
        gid=d['game']['id'];u=urlsplit(d['endpoint'])
        if u.scheme!='https' or u.netloc!='betman-demo.head.3oaks.com' or not re.fullmatch('/betman-demo/gs/'+re.escape(gid)+r'/desktop/[0-9a-f]{32}/demo/',u.path) or d['authority'].get('currency')!='FUN' or not d['authority'].get('public_demo'):raise ValueError('checkpoint_not_verified_fun_demo')
        for key in ['endpoint','session_id','authority','launcher','start','trace','context','source_proof']:setattr(c,key,d.get(key))
        c.context=verified['context'];c.start=verified['start']
        return c

    def close(self):self.http.close()
