"""Serial native WS demo campaign, durable no-retry cases and exclusive lock."""
import json,pathlib,re,time,msvcrt,os,hashlib,importlib,traceback
from urllib.parse import urlsplit,urlunsplit,urljoin,parse_qs,urlencode
import websocket
from discover import ROOT,HTTP,save,clean
import native

def checkpoint(**x):save(ROOT/'private/checkpoint.json',{'pid':os.getpid(),**x})
def client_contract(source):
 from wire_contract import action_fields
 required=['requests.InitRequest','requests.ActionRequest','features.slot.action.SpinAction','JSON.stringify']
 if not all(t in source for t in required) or not action_fields(source):raise ValueError('current_client_contract_not_recognized')
 return {'sha256':hashlib.sha256(source.encode()).hexdigest(),'spin':'features.slot.action.SpinAction','bets':'bet*multiplier*denomination','buy':'buyInId native; price times base bet','buy_supported':action_fields(source)['buy_supported'],'version':'native-v1'}

class Socket:
 def __init__(self,launch,folder):
  if (ROOT/'private/remote-block.json').exists():raise RuntimeError('remote_block_preserved_no_new_network')
  self.folder=folder;self.id=0
  params=parse_qs(urlsplit(launch['resourcesLocation']).query);u=urlsplit(launch['endpoint']);assert u.hostname=='sdemo.amigogaming.cloud'
  url=urlunsplit(('wss',u.netloc,u.path,urlencode({k:params[k][0] for k in ['session','sign']}),''));save(folder/'ws-connection.json',{'status':'connecting','host':u.hostname,'path':u.path})
  try:self.w=websocket.create_connection(url,timeout=35,origin='https://demo.amigogaming.cloud',http_proxy_host=None)
  except websocket.WebSocketBadStatusException as exc:
   if exc.status_code in [403,429,503]:save(ROOT/'private/remote-block.json',{'phase':'ws_connect','status':exc.status_code})
   raise
 def send(self,request,p):
  assert not p.exists();request=dict(request,id=self.id);self.id+=1;packet={'status':'sending','request':request};save(p,packet)
  self.w.send(json.dumps(request));events=[]
  while True:
   a=json.loads(self.w.recv())
   if a.get('id')==request['id'] or a.get('@type')=='responses.ErrorResponse':break
   events.append(clean(a));save(p,dict(packet,unsolicited_events=events))
   if len(events)>30:raise ValueError('unexpected_unsolicited_sequence')
  packet.update(status='received',response=clean(a),unsolicited_events=events);save(p,packet)
  if a.get('@type')=='responses.ErrorResponse':raise ValueError('native_error_'+str(a.get('code')))
  return packet

def native_action(state,init,source,bet):
 from live_actions import continuation
 return continuation(state,init,source,bet)

def run_case(sock,g,init,source,mode,quote,folder,initial,case_filename=None,case_init_reference=None):
 if mode!='NORMAL' and not client_contract(source)['buy_supported']:raise ValueError('purchase_not_declared_by_current_native_client')
 p=ROOT/'private/rounds'/str(g['id'])/(case_filename or mode+'.json')
 if p.exists():raise ValueError('case_exists_no_retry')
 bet=native.minimum_bet(init);case={'game_id':g['id'],'slug':g['slug'],'mode':mode,'status':'started','init_reference':str((folder/'init.json').relative_to(ROOT)),'source_client_reference':str((folder/'client.js').relative_to(ROOT)),'balance_before':initial['balance']['amount'],'price_multiplier':str(quote),'journal':[]};save(p,case);state=initial
 if case_init_reference:case['init_reference']=str(case_init_reference.relative_to(ROOT));save(p,case)
 if native.D(case['balance_before'])<native.D(bet['denomination'])*native.D(str(bet['bet']))*native.D(str(bet['multiplier']))*native.D(str(quote)):
  case.update(status='preflight_no_funds',error='native_balance_below_case_cost_no_wager_sent');save(p,case);raise ValueError('preflight_no_funds')
 for n in range(1000):
  if n==0:
   action={'@type':'features.slot.action.SpinAction','betParams':bet}
   if mode!='NORMAL':action['buyInId']=mode.removeprefix('BUY_')
  else:
   while True:
    try:action=native_action(state,init,source,bet);break
    except ValueError as exc:
     checkpoint(status='paused_live_unknown_continuation',game=g['slug'],mode=mode,error=str(exc),case=str(p.relative_to(ROOT)))
     flag=ROOT/'private/resume-live.flag'
     while not flag.exists():time.sleep(2)
     flag.unlink();importlib.reload(native)
     import live_actions
     importlib.reload(live_actions)
  packet_path=folder/(mode+'-'+str(n)+'.json');case['journal'].append({'status':'sending','request':dict({'@type':'requests.ActionRequest','id':sock.id},action=action),'packet_reference':str(packet_path.relative_to(ROOT))});save(p,case)
  try:
   packet=sock.send({'@type':'requests.ActionRequest','action':action},packet_path);case['journal'][-1]=dict(packet,packet_reference=str(packet_path.relative_to(ROOT)));state=packet['response'];save(p,case)
   if native.terminal(state):
    bound=dict(init,balance=dict(init['balance'],amount=case['balance_before']));case['audit']=native.audit(bound,case['journal'],quote);case['status']='verified';save(p,case);print(json.dumps({'game':g['slug'],'mode':mode,'status':'verified','audit':case['audit']}),flush=True);return state
  except Exception as exc:
   if packet_path.exists():
    receipt=json.loads(packet_path.read_text(encoding='utf-8'))
    if receipt.get('status')=='received':case['journal'][-1]=dict(receipt,packet_reference=str(packet_path.relative_to(ROOT)))
   case.update(status='hold_do_not_repeat',error=str(exc));save(p,case);raise
 raise ValueError('continuation_limit')

def main():
 lockpath=ROOT/'private/campaign.lock';lockpath.touch(exist_ok=True)
 if lockpath.stat().st_size==0:lockpath.write_bytes(b'0')
 lock=open(lockpath,'r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);last=0;sock=None
 try:
  rows=json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8'));completed=[]
  for g in rows:
   if g['is_coming_soon']:continue
   hold=ROOT/'private/holds'/(str(g['id'])+'.json')
   if hold.exists() and not json.loads(hold.read_text(encoding='utf-8')).get('resolved'):continue
   planpath=ROOT/'private/plans'/(str(g['id'])+'.json')
   if planpath.exists():
    plan=json.loads(planpath.read_text(encoding='utf-8'))
    if plan.get('excluded_non_slot'):continue
    existing=list((ROOT/'private/rounds'/str(g['id'])).glob('*.json'));verified={json.loads(p.read_text(encoding='utf-8')).get('mode'):p for p in existing if json.loads(p.read_text(encoding='utf-8')).get('status')=='verified'}
    paths=[verified.get(m,ROOT/'private/rounds'/str(g['id'])/(m+'.json')) for m in plan['modes']]
    if paths and all(p.exists() and json.loads(p.read_text(encoding='utf-8')).get('status')=='verified' for p in paths):completed.append(g['slug']);continue
    if any(p.exists() for p in paths):raise ValueError('existing_case_review_required_'+g['slug'])
   time.sleep(max(0,10-(time.monotonic()-last)));last=time.monotonic();checkpoint(status='running',stage='new_demo',game=g['slug'],completed_games=len(completed));h=HTTP();label='game-'+str(g['id'])+'-1'
   if (ROOT/'private/sessions'/label).exists():
    recovery=ROOT/'private/recovery/fresh-session-check.json'
    approval=ROOT/'private/recovery/preflight-restarts'/(str(g['id'])+'.json')
    if g['id']==107 and recovery.exists() and json.loads(recovery.read_text(encoding='utf-8')).get('status')=='fresh_public_session_initialized_successfully' and not list((ROOT/'private/rounds'/str(g['id'])).glob('*.json')):label='game-107-campaign-fresh-after-checked-launch'
    elif approval.exists() and not list((ROOT/'private/rounds'/str(g['id'])).glob('*.json')):
     approved=json.loads(approval.read_text(encoding='utf-8'));assert approved['no_financial_actions'] is True and approved['source_contract_verified'] is True;label='game-'+str(g['id'])+'-campaign-fresh-after-preflight'
    else:raise ValueError('existing_session_inspect_before_resume')
    if (ROOT/'private/sessions'/label).exists():raise ValueError('new_authorized_session_already_exists_no_retry')
   portal_journal=f'private/discovery/portal-{g["id"]}.json' if label=='game-'+str(g['id'])+'-1' else f'private/discovery/portal-{label}.json'
   q=h.request('https://amigogaming.com/es/games',path=portal_journal);token=re.search(r'<meta name="csrf-token" content="([^"]+)',q.text);assert token;h.s.headers['X-CSRF-TOKEN']=token.group(1)
   launch=h.launch(g,label);folder=ROOT/'private/sessions'/label;url=launch['resourcesLocation'];html=h.request(url,path=f'private/sessions/{label}/game-document.json');(folder/'game.html').write_bytes(html.content)
   lib=re.search(r'var gameLib\s*=\s*"([^"]+)"',html.text)
   if not lib:raise ValueError('native_game_client_not_identified')
   src=urljoin(url,lib.group(1));q=h.request(src,path=f'private/sessions/{label}/client-fetch.json');source=q.content.decode('utf-8');(folder/'client.js').write_text(source,encoding='utf-8')
   sock=Socket(launch,folder);ip=sock.send({'@type':'requests.InitRequest'},folder/'init.json');init=ip['response'];assert init['@type']=='responses.InitResponse' and init['round']==0
   main=init.get('mainFeature');main_type=init.get('features',{}).get(main,{}).get('@type')
   if main_type in ('features.smash.SmashFeature','features.scratch.ScratchFeature'):
    save(planpath,{'game_id':g['id'],'slug':g['slug'],'modes':[],'excluded_non_slot':True,'main_feature':main,'feature_types':{k:v.get('@type') for k,v in init['features'].items()},'init_reference':str((folder/'init.json').relative_to(ROOT)),'reason':'native_non_slot_genre_not_in_slot_scope'});sock.w.close();sock=None;continue
   assert main=='SLOT' and native.terminal(init)
   contract=client_contract(source);save(folder/'client-contract.json',contract)
   buys=init.get('buyIns',[]);assert isinstance(buys,list)
   if buys and not contract['buy_supported']:raise ValueError('native_offers_but_no_current_purchase_contract')
   modes={'NORMAL':1}
   for b in buys:
    if not isinstance(b.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]+',b['id']) or native.D(str(b['price']))<=0:raise ValueError('unknown_native_buy_definition')
    modes['BUY_'+b['id']]=b['price']
   save(planpath,{'game_id':g['id'],'slug':g['slug'],'modes':list(modes),'buyIns':buys,'feature_types':{k:v.get('@type') for k,v in init['features'].items()},'init_reference':str((folder/'init.json').relative_to(ROOT)),'client':contract})
   current=init
   for mode,price in modes.items():
    checkpoint(status='running',game=g['slug'],mode=mode,completed_games=len(completed));current=run_case(sock,g,init,source,mode,price,folder,current)
   sock.w.close();sock=None;completed.append(g['slug'])
  checkpoint(status='first_pass_finished_pending_audit',completed_games=len(completed))
 except Exception as exc:
  checkpoint(status='stopped_for_review',error=str(exc));print({'status':'stopped_for_review','error':str(exc)},flush=True)
 finally:
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
