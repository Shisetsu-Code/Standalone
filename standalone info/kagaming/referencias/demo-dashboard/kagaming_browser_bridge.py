"""Loopback-only browser transport for official public demo requests."""
import json,re,time,uuid,threading,queue,secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qsl
from pathlib import Path
import requests
from kagaming_layout import batch_folder,batch_name,scope_policy,is_excluded

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parent/'kagaming-private'
BATCH=batch_folder()
PORT=8792
PENDING=queue.Queue();JOBS={};WORKER=secrets.token_urlsafe(32);BACKEND=secrets.token_urlsafe(32)
LAST_POLL=0.0;PROCESSED=0;LAST_STATUS=None

def canonical_host(value):return value=='127.0.0.1:8792'

def validate_job(job):
    u=urlsplit(job['url']);method=job.get('method','POST')
    if u.scheme!='https' or u.netloc!='rmpdemo.kaga88.com' or u.fragment:raise ValueError('only_official_public_demo')
    pairs=parse_qsl(u.query,keep_blank_values=True);q=dict(pairs)
    if len(q)!=len(pairs):raise ValueError('duplicate_query_keys')
    if method=='GET':
        if u.path!='/kaga/publicGameList' or q not in ({'lang':'es'},{'lang':'en'},{}):raise ValueError('only_public_catalog_read')
        return job
    if method!='POST' or u.path not in ('/kaga/rmp/startGame','/kaga/command/spin','/kaga/command/ping','/kaga/rmp/gameRecall','/kaga/command/bonusPick'):raise ValueError('unreviewed_demo_operation')
    if set(q)!=set(('ak','cr','m','u')) or q['ak']!='accessKey' or q['cr']!='USD' or q['m']!='0' or not re.fullmatch('[0-9]{9}',q['u']):raise ValueError('only_anonymous_demo_identity')
    body=job['body']
    if not isinstance(body,dict):raise ValueError('invalid_demo_body')
    if 'body_text' in job and (not isinstance(job['body_text'],str) or json.loads(job['body_text'])!=body):raise ValueError('body_text_mismatch')
    if u.path.endswith('/bonusPick'):
        from kagaming_bonus_pick import CHOICE_COUNTS
        choices=dict(CHOICE_COUNTS,BonusPoker=32)
        if set(body)!={'gn','p','sid'} or body.get('gn') not in choices or type(body.get('p')) is not int or not 0<=body['p']<choices[body['gn']] or type(body.get('sid')) is not int or body['sid']<0:raise ValueError('unreviewed_native_bonus_choice')
    if u.path.endswith('/gameRecall') and (set(body)!={'g','n','tz'} or body['n']!=10 or body['tz']!=0):raise ValueError('only_bounded_native_history')
    if u.path.endswith('/startGame') and (body.get('pn')!='demo' or body.get('ak')!='accessKey' or body.get('un')!=q['u'] or body.get('to')!='123' or body.get('gm')!=0 or body.get('cr')!='USD'):raise ValueError('only_demo_launch')
    if not u.path.endswith('/ping'):
        games=json.loads((BATCH/'catalog.json').read_text(encoding='utf8'))
        gid=body.get('g' if u.path.endswith('/gameRecall') else 'gn')
        game=next((g for g in games if g['id']==gid),None)
        if game is None:raise ValueError('game_outside_authorized_batch')
        if is_excluded(game,scope_policy(BATCH)):raise ValueError('game_outside_current_scope')
    if job.get('ctx') is not None and (not isinstance(job['ctx'],str) or len(job['ctx'])>16384 or not isinstance(json.loads(job['ctx']),dict)):raise ValueError('invalid_context')
    return job

HTML='''<!doctype html><html lang="es"><meta charset="utf-8"><title>Cliente local · demos KA Gaming</title><style>body{background:#101827;color:#e2e8f0;font:18px system-ui;max-width:800px;margin:50px auto;padding:24px}button{padding:16px;font-size:18px}a{color:#7dd3fc}</style><h1>Cliente local de demos · KA Gaming</h1><p>Transporte del navegador para las pruebas con saldo ficticio de demo. Las solicitudes se limitan al servidor oficial de demostración.</p><button id="start">Iniciar transporte</button><p id="state">Detenido</p><p id="count">Solicitudes completadas: 0</p><a href="http://127.0.0.1:8787/kagaming/batches/1-100/index.html">Ver el informe de pruebas</a><script>
let running=false,count=0;const state=document.querySelector('#state');
document.querySelector('#start').onclick=async()=>{if(running)return;running=true;document.querySelector('#start').disabled=true;state.textContent='Conectado · esperando solicitudes';while(running){try{const response=await fetch('/next',{cache:'no-store'});if(!response.ok)throw Error('Conexión local no autorizada');const job=await response.json();if(!job.id){await new Promise(r=>setTimeout(r,250));continue;}state.textContent='Enviando solicitud demo · '+(job.body?.command||'lectura pública');let result;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),35000);try{const init={method:job.method||'POST',credentials:'omit',redirect:'error',signal:controller.signal};if(init.method==='POST'){init.headers={'Content-Type':'application/json'};init.body=job.body_text??JSON.stringify(job.body);if(job.ctx)init.headers.ctx=job.ctx;}const reply=await fetch(job.url,init);const body=await reply.text();result={status:reply.status,body,headers:{}};for(const key of ['Content-Type','Retry-After','Server']){const value=reply.headers.get(key);if(value)result.headers[key]=value;}}catch(e){result={error:String(e.name)+': '+String(e.message)}}finally{clearTimeout(timer)}await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:job.id,result})});count++;document.querySelector('#count').textContent='Solicitudes completadas: '+count;state.textContent=result.error?'Solicitud sin respuesta confirmada · consultar informe':'Respuesta recibida · HTTP '+result.status;}catch(e){state.textContent='Transporte detenido: '+e.message;running=false;}}};
</script></html>'''

HTML=HTML.replace('kagaming/batches/1-100/', 'kagaming/batches/'+batch_name()+'/')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,data,html=False,cookie=False):
        body=data.encode('utf8') if html else json.dumps(data).encode('utf8');self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','DENY')
        if cookie:self.send_header('Set-Cookie','ka_worker='+WORKER+'; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers();self.wfile.write(body)
    def worker_ok(self):return ('ka_worker='+WORKER) in self.headers.get('Cookie','') and self.headers.get('Origin','http://127.0.0.1:8792')=='http://127.0.0.1:8792'
    def do_GET(self):
        global LAST_POLL
        if not canonical_host(self.headers.get('Host')):return self.reply(403,{'error':'invalid_host'})
        if self.path=='/':return self.reply(200,HTML,html=True,cookie=True)
        if self.path=='/health':return self.reply(200,{'connected':time.time()-LAST_POLL<10,'processed':PROCESSED,'last_status':LAST_STATUS})
        if self.path!='/next' or not self.worker_ok():return self.reply(403,{'error':'not_authorized'})
        LAST_POLL=time.time()
        while True:
            try:ident=PENDING.get_nowait()
            except queue.Empty:return self.reply(200,{})
            job=JOBS.get(ident)
            if job and job['deadline']>time.time():job['dispatched']=True;return self.reply(200,dict(id=ident,**job['request']))
    def do_POST(self):
        global PROCESSED,LAST_STATUS
        if not canonical_host(self.headers.get('Host')) or self.headers.get('Origin') not in (None,'http://127.0.0.1:8792'):return self.reply(403,{'error':'invalid_host_or_origin'})
        if int(self.headers.get('Content-Length','0'))>8*1024*1024:return self.reply(413,{'error':'too_large'})
        try:data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        except Exception:return self.reply(400,{'error':'invalid_json'})
        if self.path=='/request':
            if self.headers.get('X-Bridge-Key')!=BACKEND:return self.reply(403,{'error':'not_authorized'})
            if time.time()-LAST_POLL>10:return self.reply(503,{'error':'browser_worker_not_connected'})
            try:validate_job(data)
            except Exception:return self.reply(400,{'error':'not_official_demo'})
            ident=uuid.uuid4().hex;event=threading.Event();job={'request':data,'event':event,'deadline':time.time()+45,'dispatched':False};JOBS[ident]=job;PENDING.put(ident)
            ready=event.wait(45);JOBS.pop(ident,None)
            if not ready:return self.reply(504,{'error':'uncertain_browser_response'})
            return self.reply(200,job['result'])
        if self.path=='/result' and self.worker_ok():
            job=JOBS.get(data.get('id'))
            if not job:return self.reply(409,{'error':'expired_request'})
            job['result']=data['result'];job['event'].set();PROCESSED+=1;LAST_STATUS=data['result'].get('status');return self.reply(200,{'ok':True})
        return self.reply(403,{'error':'not_authorized'})

def browser_request(url,body=None,method='POST',ctx=None):
    job={'url':url,'body':body,'method':method,'ctx':ctx};
    if method=='POST':job['body_text']=json.dumps(body,separators=(',',':'),ensure_ascii=False)
    validate_job(job);key=(PRIVATE/'browser-bridge-key.txt').read_text(encoding='utf8')
    response=requests.post('http://127.0.0.1:8792/request',json=job,headers={'X-Bridge-Key':key},timeout=50);response.raise_for_status();wrapped=response.json()
    if wrapped.get('error'):raise IOError('browser_response_uncertain:'+wrapped['error'])
    result=requests.Response();result.status_code=wrapped['status'];result._content=wrapped['body'].encode('utf8');result.encoding='utf8';result.url=url;result.headers.update(wrapped.get('headers',{}));return result

def browser_post(url,body,ctx=None):return browser_request(url,body,ctx=ctx)
def browser_get(url):return browser_request(url,method='GET')

if __name__=='__main__':
    PRIVATE.mkdir(exist_ok=True);(PRIVATE/'browser-bridge-key.txt').write_text(BACKEND,encoding='utf8')
    print('BROWSER_TRANSPORT http://127.0.0.1:8792/',flush=True);ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
