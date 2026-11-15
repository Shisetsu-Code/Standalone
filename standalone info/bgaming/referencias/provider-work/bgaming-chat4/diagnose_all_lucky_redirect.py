"""Offline classification and parent-controlled ONE-GET redirect observation.

No init, wager, launch, retry, or shared-state writes. The parent supplies an
active VariantGate and a durable, once-only PRIVATE checkpoint sink. That sink
must retain payload/cookies before opening the one already-owned lobby GET.
Running this file directly only summarizes the two saved checkpoints offline.
"""
import base64
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs,urlsplit
from all_lucky_variants import official_url,VARIANTS

def _digest(raw):return hashlib.sha256(raw).hexdigest()

def public_url(url):
 u=urlsplit(url);allowed={'AllLuckyClover',*VARIANTS,'FUN','launch','play','lobby','api'}
 parts=[]
 for part in u.path.split('/'):
  if part in allowed or part=='':parts.append(part)
  else:parts.append('{id}')
 query=parse_qs(u.query)
 selection={key:value[0] for key,value in query.items() if key in ('game','from') and len(value)==1 and value[0] in {'AllLuckyClover',*VARIANTS}}
 keys=sorted({key if key in ('game','from','server','currency','token','session') else '{key}' for key in query})
 return dict(origin=u.scheme+'://'+str(u.hostname or ''),path_pattern='/'.join(parts),query_keys=keys,selection=selection)

def _headers(response):
 value=getattr(response,'headers',{})
 return [(str(k),str(v)) for k,v in (value.raw_items() if hasattr(value,'raw_items') else value.items())]

def _record(url,status,headers,body):
 return dict(url=url,http_status=status,headers=headers,headers_sha256=_digest(json.dumps(headers,separators=(',',':')).encode()),body_bytes=len(body),body_sha256=_digest(body),body_base64=base64.b64encode(body).decode(),body_utf8=body.decode('utf8',errors='replace'))

def _public(record):
 content_type=next((v.split(';',1)[0].strip().lower() for k,v in record['headers'] if k.lower()=='content-type'),None)
 return dict(url=public_url(record['url']),http_status=record['http_status'],header_names=sorted({k for k,v in record['headers']}),headers_sha256=record['headers_sha256'],content_type=content_type if content_type in ('application/json','text/json','text/html','text/plain') else 'other',body_bytes=record['body_bytes'],body_sha256=record['body_sha256'])

def parse_body(raw):
 """Parse data only; never execute returned HTML/JavaScript."""
 try:text=raw.decode('utf8')
 except UnicodeDecodeError:return 'non_utf8',None
 try:value=json.loads(text)
 except ValueError:
  match=re.search(r'window\.__OPTIONS__\s*=\s*',text)
  if match:
   try:value,_=json.JSONDecoder().raw_decode(text[match.end():])
   except ValueError:return 'html_unparsed_bootstrap',None
   if isinstance(value,dict):return 'bootstrap_options_html',value
  return ('html' if re.search(r'<(?:!doctype|html|script)\b',text,re.I) else 'non_json'),None
 if isinstance(value,dict) and {'identifier','currency','api'}<=value.keys():return 'bootstrap_options_json',value
 return 'json_other',value

def classify_checkpoint(checkpoint):
 body=checkpoint.get('response_body')
 local=checkpoint.get('error_type')=='ValueError' and 'redirect' in str(checkpoint.get('error','')).lower() and checkpoint.get('http_status') is None and not body
 classification='local_redirect_guard_body_not_read' if local else 'received_body_not_retained_cause_unrecorded' if not body and 'response' not in checkpoint else 'saved_response_available_for_private_review'
 return dict(method=checkpoint.get('method'),url=public_url(checkpoint.get('url','')),checkpoint_status=checkpoint.get('status'),error_type=checkpoint.get('error_type'),http_status=checkpoint.get('http_status'),classification=classification,provider_rejection_proved=False,reason='A callback URL-equality exception is not a provider error response; final URL/body were discarded.' if local else 'Saved evidence does not establish the final redirected URL or a provider error.')

class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
 def __init__(self,persist,guard=None):super().__init__();self.persist=persist;self.records=[];self.guard=guard or (lambda:None)
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  body=fp.read();item=_record(req.full_url,code,[(str(k),str(v)) for k,v in headers.items()],body);item['redirect_target']=newurl
  try:official_url(newurl)
  except ValueError:
   self.persist('blocked_redirect',item);raise ValueError('Redirect target is outside official HTTPS origins') from None
  if req.get_method()!='GET':raise ValueError('Diagnostic follows GET redirects only')
  item['origin_changed']=urlsplit(req.full_url).netloc!=urlsplit(newurl).netloc
  self.persist('official_redirect_received',item);self.records.append(item)
  self.guard()
  redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
  if redirected is not None:
   if item['origin_changed']:
    redirected.headers={k:v for k,v in redirected.headers.items() if k.lower() in ('accept','accept-language','user-agent')}
   else:
    # urllib's generic redirect path removes Content-Type. The selector's
    # same-origin fetch retains its bootstrap headers, including CSRF.
    redirected.headers.update(req.headers)
  return redirected

def _opener(handler,own_opener):
 cookiejar=next((h.cookiejar for h in getattr(own_opener,'handlers',[]) if isinstance(h,urllib.request.HTTPCookieProcessor)),None)
 if cookiejar is None:raise ValueError('A suite-owned cookie jar is required')
 return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar),handler)

@dataclass(repr=False)
class DiagnosticResult:
 record:dict
 redirects:list
 body_kind:str
 parsed_options:object
 private_body:bytes
 def public_summary(self):
  result=_public(self.record);result['body_kind']=self.body_kind;result['redirects']=[dict(_public(r),target=public_url(r['redirect_target']),origin_changed=r['origin_changed']) for r in self.redirects]
  if isinstance(self.parsed_options,dict):
   identifier=self.parsed_options.get('identifier');result['bootstrap_identifier']=identifier if identifier in {'AllLuckyClover',*VARIANTS} else 'unrecognized';result['bootstrap_FUN']=self.parsed_options.get('currency')=='FUN';result['bootstrap_demo']=self.parsed_options.get('server_id')=='demo'
  result['init_calls']=0;result['wagers']=0;return result

def observe_once(checkpoint,cfg,own_context,own_opener,*,gate,private_checkpoint,opener_factory=None):
 """Reinspect exactly one source-derived own lobby GET; never init or replay POST.

 The PRIVATE sink must enforce a once-only diagnostic attempt archive before
 sending, preserve old checkpoints unchanged, and snapshot the shared own jar.
 gate supplies held runner.lock, STOP semantics and one-minute launch pacing.
 """
 gate.check()
 if checkpoint.get('method')!='GET' or checkpoint.get('body') is not None:raise ValueError('Only the already-owned selector GET may be observed')
 if cfg.get('identifier') not in {'AllLuckyClover',*VARIANTS} or cfg.get('currency')!='FUN' or cfg.get('server_id')!='demo':raise ValueError('Own FUN selector bootstrap required')
 if own_context.get('fresh_demo') is not True or own_context.get('game_id')!='AllLuckyClover' or own_context.get('operation',{}).get('status')!='received' or own_context.get('last_request',{}).get('command')!='init':raise ValueError('Only suite-owned init-only selector context is allowed; never HAR')
 if own_context.get('api')!=cfg.get('api') or own_context.get('csrf_name')!=cfg.get('csrfTokenHeaderName') or own_context.get('csrf_value')!=cfg.get('csrfTokenHeaderValue'):raise ValueError('Bootstrap/private context identity differs')
 url=official_url(checkpoint['url']);query=parse_qs(urlsplit(url).query);variant=query.get('game',[None])[0]
 if variant not in VARIANTS or query.get('from')!=[cfg['identifier']]:raise ValueError('GET variant/from is outside source selector contract')
 base=official_url(cfg['lobby_launch_url']);expected=base+('&' if base.find('?')>0 else '?')+'game='+variant+'&from='+cfg['identifier']
 if url!=expected:raise ValueError('GET does not match the exact source-derived own lobby URL')
 headers=copy.deepcopy(checkpoint.get('headers',{}))
 if headers.get(cfg['csrfTokenHeaderName'])!=cfg['csrfTokenHeaderValue'] or headers.get('Content-Type')!='application/json':raise ValueError('GET bootstrap headers differ')
 started=gate.reserve();private_checkpoint('before_one_owned_GET',dict(original_checkpoint=copy.deepcopy(checkpoint),bootstrap=copy.deepcopy(cfg),private_context=copy.deepcopy(own_context),last_launch_epoch=started,method='GET',url=url,headers=headers,body=None,once_only=True))
 handler=OfficialRedirectHandler(private_checkpoint,gate.check);opener=(opener_factory or _opener)(handler,own_opener)
 request=urllib.request.Request(url,headers=dict(headers,**{'User-Agent':'Mozilla/5.0'}),method='GET');gate.check()
 try:
  try:response=opener.open(request,timeout=45)
  except urllib.error.HTTPError as error:response=error
  with response:
   final_url=official_url(response.url)
   raw=response.read();record=_record(final_url,getattr(response,'status',getattr(response,'code',None)),_headers(response),raw)
  kind,parsed=parse_body(raw);record['body_kind']=kind;record['parsed_value']=parsed
  private_checkpoint('final_owned_GET_received',record)
  return DiagnosticResult(record,handler.records,kind,parsed,raw)
 except Exception as error:
  private_checkpoint('owned_GET_requires_review',dict(error_type=type(error).__name__,redirects=copy.deepcopy(handler.records),last_launch_epoch=started,no_retry=True))
  raise

if __name__=='__main__':
 private=Path(__file__).resolve().parents[2]/'bgaming-private-chat4'
 for name in ('all-lucky-variants','all-lucky-variants-v2'):
  path=private/name/'request-checkpoint.json'
  if path.exists():print(json.dumps(dict(attempt=name,**classify_checkpoint(json.loads(path.read_text(encoding='utf8'))))))
