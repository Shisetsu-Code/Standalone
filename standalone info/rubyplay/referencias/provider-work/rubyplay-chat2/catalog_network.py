"""Read public catalogue pages only; no sessions, wagers or retries."""
from datetime import datetime,timezone
import hashlib,json,os,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import subprocess
import ssl
from har_probe import ROOT,safe_url

ALLOWED={'rubyplay.com','www.rubyplay.com','slotcatalog.com','www.slotcatalog.com','www.slotstemple.com','slotstemple.com'}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def verified_catalog_context(host):
    block=ROOT/'private'/'network'/(host+'.blocked.json')
    if block.exists():
        reason=json.loads(block.read_text(encoding='utf8'))
        if reason.get('block_type')!='tls_identity_validation_failed' or host!='rubyplay.com':
            raise RuntimeError('source_block_retained:'+host)
        proof=json.loads((ROOT/'private/network/rubyplay-tls-chain-fixed.json').read_text(encoding='utf8'))
        ca=ROOT/proof['ca_file']
        required=('passed','hostname_validation','wrong_hostname_rejected','intermediate_alone_rejected_without_trusted_roots')
        if not all(proof.get(k) is True for k in required) or proof.get('added_trust_roots')!=0:
            raise RuntimeError('TLS_correction_not_verified')
        if not ca.resolve().is_relative_to(ROOT) or hashlib.sha256(ca.read_bytes()).hexdigest()!=proof['ca_sha256']:
            raise RuntimeError('TLS_bundle_pin_mismatch')
        ctx=ssl.create_default_context(cafile=str(ca))
        if not ctx.check_hostname or ctx.verify_mode!=ssl.CERT_REQUIRED or ctx.verify_flags & getattr(ssl,'VERIFY_X509_PARTIAL_CHAIN',0):
            raise RuntimeError('TLS_validation_must_remain_strict')
        return ctx
    return ssl.create_default_context()

def durable(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def fetch(source,key,url,data=None,headers=None,follow_redirects=True):
    host=urlsplit(url).hostname
    if urlsplit(url).scheme!='https':raise ValueError('catalogue_requires_verified_HTTPS')
    if host not in ALLOWED:raise ValueError('catalogue_host_not_allowed')
    block=ROOT/'private'/'network'/(host+'.blocked.json')
    ctx=verified_catalog_context(host)
    folder=ROOT/'private'/'catalog-snapshots'/source
    folder.mkdir(parents=True,exist_ok=True)
    meta=folder/(key+'.meta.json');bodypath=folder/(key+'.body')
    if meta.exists():
        old=json.loads(meta.read_text(encoding='utf8'))
        if old.get('status')==200 and bodypath.exists():
            payload=bodypath.read_bytes()
            if hashlib.sha256(payload).hexdigest()!=old.get('sha256'):raise ValueError('cached_catalogue_hash_changed')
            return old,payload
        raise RuntimeError('prior_non_success_preserved:'+str(meta))
    intent={'source':source,'key':key,'url':safe_url(url),'method':'POST' if data else 'GET',
            'started_at':datetime.now(timezone.utc).isoformat(),'state':'intent_before_send'}
    durable(meta,intent)
    req=Request(url,data=data,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/json',**(headers or {})})
    redirect_location=None
    pagination={}
    try:
        response_context=urlopen(req,timeout=45,context=ctx) if follow_redirects else build_opener(HTTPSHandler(context=ctx),NoRedirect()).open(req,timeout=45)
        with response_context as response:
            payload=response.read(20_000_001)
            if len(payload)>20_000_000:raise ValueError('catalogue_body_too_large')
            status=response.status;final=response.url;ctype=response.headers.get('Content-Type','')
            for header,keyname in (('X-WP-Total','total'),('X-WP-TotalPages','pages')):
                value=response.headers.get(header,'')
                if value.isdigit():pagination[keyname]=int(value)
    except HTTPError as e:
        status=e.code;payload=e.read(1_000_000);final=e.url;ctype=e.headers.get('Content-Type','')
        if e.headers.get('Location'):redirect_location=safe_url(e.headers['Location'])
    except (URLError,TimeoutError) as e:
        durable(meta,{**intent,'state':'transport_error_no_retry','error_type':type(e).__name__,'reason':str(getattr(e,'reason',e))[:300]})
        raise
    bodypath.write_bytes(payload)
    result={**intent,'state':'received','status':status,'final_url':safe_url(final),'content_type':ctype,
            'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'finished_at':datetime.now(timezone.utc).isoformat()}
    if redirect_location:result['redirect_location']=redirect_location
    if pagination:result['catalogue_pagination']=pagination
    durable(meta,result)
    if status in (403,429,503):durable(block,result)
    print(json.dumps({'source':source,'key':key,'status':status,'bytes':len(payload)},ensure_ascii=False),flush=True)
    return result,payload

def fetch_windows(source,key,url,data=None,headers=None):
    """Schannel validates TLS with Windows trust; never use insecure TLS flags."""
    host=urlsplit(url).hostname
    if host not in ALLOWED:raise ValueError('catalogue_host_not_allowed')
    block=ROOT/'private'/'network'/(host+'.blocked.json')
    if block.exists():raise RuntimeError('source_block_retained:'+host)
    folder=ROOT/'private'/'catalog-snapshots'/source;folder.mkdir(parents=True,exist_ok=True)
    meta=folder/(key+'.meta.json');path=folder/(key+'.body')
    if meta.exists():
        old=json.loads(meta.read_text(encoding='utf8'))
        if old.get('status')==200 and path.exists():return old,path.read_bytes()
        raise RuntimeError('prior_non_success_preserved')
    intent={'source':source,'key':key,'url':safe_url(url),'started_at':datetime.now(timezone.utc).isoformat(),
            'state':'intent_before_send','transport':'curl_schannel_tls_verified'}
    durable(meta,intent)
    args=['curl.exe','--silent','--show-error','--proto','=https','--max-time','60','--output',str(path),
          '--dump-header',str(folder/(key+'.headers.private')),'--write-out','%{http_code}',url]
    if data is not None:
        post=folder/(key+'.request.private');post.write_bytes(data)
        args+=['--data-binary','@'+str(post)]
    for k,v in (headers or {}).items():args+=['--header',k+': '+v]
    completed=subprocess.run(args,capture_output=True)
    stdout=completed.stdout.decode('ascii','replace')
    stderr=completed.stderr.decode('mbcs','replace')
    if completed.returncode:
        durable(meta,{**intent,'state':'transport_error_no_retry','curl_exit':completed.returncode,'error':stderr[:400]})
        print(json.dumps({'source':source,'key':key,'curl_exit':completed.returncode}),flush=True)
        return json.loads(meta.read_text(encoding='utf8')),b''
    status=int(stdout);payload=path.read_bytes()
    result={**intent,'state':'received','status':status,'bytes':len(payload),
            'sha256':hashlib.sha256(payload).hexdigest(),'finished_at':datetime.now(timezone.utc).isoformat()}
    durable(meta,result)
    if status in (403,429,503):durable(block,result)
    print(json.dumps({'source':source,'key':key,'status':status,'bytes':len(payload)}),flush=True)
    return result,payload

if __name__=='__main__':
    for source,url in (
        ('rubyplay','https://rubyplay.com/reel-winners/'),
        ('slotcatalog','https://slotcatalog.com/es/soft/Ruby-Play'),
        ('slotstemple','https://www.slotstemple.com/ca/free-slots/rubyplay/')):
        try:fetch(source,'page-1',url)
        except Exception as e:print(json.dumps({'source':source,'error_type':type(e).__name__}),flush=True)
