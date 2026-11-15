"""Serial public-demo QA. Fresh sessions, native contracts, durable no-retry journal."""
import hashlib,json,msvcrt,os,pathlib,re,time,datetime
from urllib.parse import urlsplit,urljoin
import requests
from contracts import identify,roll_continuation,next_action,bonus_choice,opened_positions
from native import audit_packets,number
ROOT=pathlib.Path(__file__).resolve().parent.parent
ALLOWED={'cu.thunderspin.net','stage-cu.thunderspin.net','games.thunderspin.com'}
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)
def clean(x):
 if isinstance(x,dict):return {k:('[REDACTED]' if re.fullmatch('sid|sessionid|token|cookie|authorization|password|secret',k,re.I) else clean(v)) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 return x
class Campaign:
 def __init__(self):
  self.session=requests.Session();self.session.trust_env=False;self.state={'pid':os.getpid(),'status':'running','completed_games':[],'pending':[],'current':None};self.last_launch=time.monotonic()
 def checkpoint(self):save(ROOT/'private/checkpoint.json',self.state)
 def request(self,url,*,data=None,json_body=None,journal):
  record={'status':'sending','url':url,'method':'POST' if data is not None or json_body is not None else 'GET','request':clean(json_body if json_body is not None else data),'sent_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};save(journal,record)
  try:r=self.session.post(url,json=json_body,timeout=30) if json_body is not None else self.session.post(url,data=data,timeout=30) if data is not None else self.session.get(url,timeout=30)
  except Exception as exc:record.update(status='unknown_do_not_repeat',error=type(exc).__name__);save(journal,record);raise
  record.update(http_status=r.status_code,response_sha256=hashlib.sha256(r.content).hexdigest(),status='received');save(journal,record)
  if r.status_code in (403,429,503):save(ROOT/'private/remote-block.json',record);raise RuntimeError('remote_block_'+str(r.status_code))
  if r.status_code!=200:raise RuntimeError('unconfirmed_http_'+str(r.status_code))
  return r,record
 def prepare(self,g):
  slug=g['slug'];url=g['demo_url'];u=urlsplit(url)
  if u.scheme!='https' or u.hostname not in ALLOWED or (u.hostname!='games.thunderspin.com' and not u.path.startswith('/games/')) or u.query:raise ValueError('public_demo_not_supported')
  time.sleep(max(0,10-(time.monotonic()-self.last_launch)));self.last_launch=time.monotonic()
  folder=ROOT/'private/references'/slug;folder.mkdir(parents=True,exist_ok=True)
  r,_=self.request(url,journal=folder/'launch-journal.json');(folder/'launch.html').write_bytes(r.content)
  scripts=[urljoin(url,p) for p in re.findall(r'<script[^>]+src=["\x27]([^"\x27]+)',r.text)]
  scripts=[p for p in scripts if urlsplit(p).hostname==u.hostname and re.fullmatch(r'index(?:\.[a-f0-9]+)?(?:\.chunk)?\.js',pathlib.PurePosixPath(urlsplit(p).path).name)]
  if len(scripts)!=1:raise ValueError('native_client_not_unique')
  r,_=self.request(scripts[0],journal=folder/'client-journal.json');(folder/'client.js').write_bytes(r.content);contract=identify(r.text);save(folder/'contract.json',contract)
  sid='dev_'+str(time.time_ns()//1000000);fp=hashlib.sha256(sid.encode()).hexdigest()[:16];session_dir=ROOT/'private/sessions'/('own-'+fp)
  cfg={'sid':sid,'host':u.scheme+'://'+u.netloc,'service_base':contract['service_base'] or u.scheme+'://'+u.netloc+'/service','slotcode':contract['slotcode'],'source_client':str(folder/'client.js'),'contract':contract};save(session_dir/'credentials.json',cfg)
  init_path=session_dir/'init-journal.json';r,j=self.request(cfg['service_base']+'/_Initialise',data={'sid':sid,'slotcode':cfg['slotcode']},journal=init_path);x=clean(r.json());j.update(endpoint='_Initialise',game=cfg['slotcode'],session_fingerprint=fp,response=x);save(init_path,j)
  if x.get('Error') or x.get('ErrorCode') or x.get('Balance',{}).get('Demo') is not True or x.get('LastResult') is not None:raise ValueError('fresh_demo_not_idle')
  if x.get('GameCode') and x['GameCode']!=cfg['slotcode']:raise ValueError('native_game_mismatch')
  return cfg,fp,j,init_path
 def run_case(self,cfg,fp,init,init_path,mode,expected,denom,level,lines,resume=False,buy_code=None,stop_at_gamble_offer=False):
  game=cfg['slotcode'];p=ROOT/'private/rounds'/game/(mode+'.json')
  source=pathlib.Path(cfg['source_client']).read_text(encoding='utf-8')
  if resume:
   c=json.loads(p.read_text());last=c['journal'][-1]
   recognized_error=c.get('error','').startswith('unknown_continuation_') or c.get('error') in ("'roundWin'",'native_choice_not_confirmed_no_retry')
   if c['status']!='hold_do_not_repeat' or not recognized_error or (c.get('recovery_started') and len(c['journal'])<=c.get('recovery_packet_count',1)) or any(p.get('http_status')!=200 for p in c['journal']) or not next_action(last['response'],source,opened_positions(c['journal'])):raise ValueError('case_not_safe_for_continuation')
   c['recovery_started']=True;c['recovery_packet_count']=len(c['journal']);init=dict(init,response=dict(init['response'],Balance=dict(init['response']['Balance'],ScoreCents=c['balance_before_cents'])));save(p,c)
   audit_packets([init]+c['journal'])
  else:
   if p.exists():raise ValueError('case_exists_no_retry')
   before=init['response']['Balance']['ScoreCents'];c={'game':game,'mode':mode,'purpose':'preparation_for_conditional_gamble' if mode.startswith('GAMBLE_PREP_') else 'direct_mode_case','status':'started','session_fingerprint':fp,'source_init_reference':str(init_path),'balance_before_cents':before,'expected_cost_cents':expected,'journal':[]};save(p,c)
  action='_BuyBonus' if mode.startswith('BUY_') else '_Roll';expected_mode='root'
  if resume:action=next_action(last['response'],source,opened_positions(c['journal']));expected_mode=last['response']['NextMode'];lines=last['response']['LinesCount']
  current_state=last['response'] if resume else init['response']
  try:
   for step in range(500):
    q={'sid':cfg['sid'],'denomination':denom,'betlevel':level,'data':0}
    if action=='_BuyBonus':
     if cfg['contract'].get('buy_fixed_level_one') and level!=1:raise ValueError('legacy_buy_requires_level_one')
     if cfg['contract'].get('buy_lines',True):q['lines']=len(init['response'].get('Lines') or [])
    elif cfg['contract']['roll_lines']:q['lines']=lines
    if action=='_BuyBonus' and buy_code is not None:
     price=init['response'].get('BuyFeatures',{}).get(buy_code,{});base=number(init['response'].get('DefaultBet',init['response']['Balance']['DefaultBet']))*number(denom)*number(level);native_price=price.get('costs',{}).get(str(int(base)),{})
     if not cfg['contract'].get('named_buy_contract') or price.get('code')!=buy_code or native_price.get('allowed') is not True or number(native_price.get('buyValue'))!=number(expected):raise ValueError('named_buy_not_advertised')
     q['buyBonusCode']=buy_code
    if action=='_AcceptWin':q={'sid':cfg['sid']}
    choice=bonus_choice(current_state,source,opened_positions(c['journal'])) if action=='_Roll' else None
    if choice is not None:
     if any(p['request'].get('user_input')==choice for p in c['journal']):raise ValueError('native_choice_not_confirmed_no_retry')
     q['user_input']=choice
    journal=ROOT/'private/journals'/game/(mode+'-'+str(step)+'.json')
    packet={'endpoint':action,'session_fingerprint':fp,'game':game,'request':clean(q),'status':'sending','http_status':None,'transport_journal':str(journal)};c['journal'].append(packet);save(p,c)
    r,_=self.request(cfg.get('service_base',cfg['host']+'/service')+'/'+action,data=None if choice is not None else q,json_body=q if choice is not None else None,journal=journal);x=clean(r.json());packet.update(http_status=200,status='received',response=x);save(p,c)
    current_state=x
    if (action!='_AcceptWin' and x.get('Mode')!=expected_mode) or x.get('ErrorCode') or x.get('Error'):raise ValueError('native_state_mismatch')
    if len(c['journal'])==1 and number(x['Balance']['TotalBetCents'])!=number(expected):raise ValueError('native_cost_mismatch')
    audited=audit_packets([init]+c['journal'])
    if audited['closed_rounds']:
     c['audit']=audited['closed_rounds'][0];c['status']='verified';save(p,c)
     new_init=dict(init,response=dict(init['response'],Balance=dict(init['response']['Balance'],ScoreCents=x['Balance']['ScoreCents'])))
     print(json.dumps({'game':game,'mode':mode,'status':'verified','requests':len(c['journal'])}),flush=True);return new_init,x.get('LinesCount',lines)
    expected_mode=x['NextMode']
    # Only continuation contracts reproduced from native captured packets.
    action=next_action(x,source,opened_positions(c['journal']))
    if stop_at_gamble_offer and action=='_AcceptWin':
     c.update(status='gamble_offer_ready',preparation_for='GAMBLE');save(p,c);return init,lines
    if not action:raise ValueError('unknown_continuation_'+str(expected_mode))
    lines=x['LinesCount']
   raise ValueError('continuation_bound_reached')
  except Exception as exc:c.update(status='hold_do_not_repeat',error=str(exc));save(p,c);raise
 def main(self):
  games=json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8'))
  for g in games:
   self.state['current']={'slug':g['slug'],'stage':'native_contract_discovery'};self.checkpoint()
   hold=ROOT/'private/holds'/(g['slug']+'.json')
   if hold.exists():self.state['pending'].append({'slug':g['slug'],'reason':'existing_hold_no_operations','evidence':str(hold)});continue
   # Preserve original verified Dragon Hunt cases; never repeat them.
   if g['slug']=='dragon-hunt-megaways':self.state['completed_games'].append({'slug':g['slug'],'source':'existing_two_verified_cases'});continue
   old=ROOT/'private/plans'/(g['slug']+'.json')
   if old.exists():
    plan=json.loads(old.read_text());paths=[ROOT/'private/rounds'/plan['game']/(m['mode']+'.json') for m in plan['modes']]
    if any(p.exists() and json.loads(p.read_text()).get('status')!='verified' for p in paths):raise ValueError('existing_uncertain_game_no_retry')
    if paths and all(p.exists() for p in paths):self.state['completed_games'].append({'slug':g['slug'],'source':'existing_verified_cases'});continue
   cfg,fp,init,init_path=self.prepare(g);x=init['response'];b=x['Balance'];denom=min(b['CoinValue']);level=min(b['BetLevel']);base=number(x.get('DefaultBet',b['DefaultBet']))*number(denom)*number(level);lines=b.get('CurrentLinesCount',0);modes=[{'mode':'NORMAL','cost_cents':str(base)}];pending=[]
   feature=x.get('Features',{}).get('BuyBonus');buys=x.get('BuyFeatures')
   if feature:
    costs=feature.get('Costs',{}).get('costs',{});price=costs.get(str(int(base)))
    if cfg['contract']['buy_bonus_contract'] and price and price.get('allowed') is True:modes.append({'mode':'BUY_BONUS','cost_cents':str(price['buyValue'])})
    else:pending.append({'mode':'BUY_BONUS','reason':'native_price_or_client_contract_not_verified'})
   if buys:pending.append({'mode':'BuyFeatures','reason':'selectors_require_native_contract_review','native_definition':buys})
   if x.get('GameSettings',{}).get('IsGambleAllowed'):pending.append({'mode':'gamble','reason':'conditional_native_contract_required'})
   plan={'slug':g['slug'],'game':cfg['slotcode'],'modes':modes,'pending_modes':pending,'native_modes':x.get('Modes'),'source_init':str(init_path),'client_contract':cfg['contract']};save(old,plan)
   for m in modes:
    self.state['current']={'game':cfg['slotcode'],'mode':m['mode'],'stage':'native_case'};self.checkpoint();init,lines=self.run_case(cfg,fp,init,init_path,m['mode'],m['cost_cents'],denom,level,lines)
   self.state['completed_games'].append({'game':cfg['slotcode'],'modes':len(modes),'pending_modes':pending});self.checkpoint()
  self.state['status']='first_pass_finished_pending_mode_audit';self.checkpoint()
def main():
 lock=open(ROOT/'private/campaign.lock','a+b');lock.seek(0)
 if not lock.read(1):lock.write(b'0');lock.flush()
 lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);c=Campaign()
 try:c.main()
 except Exception as exc:c.state.update(status='stopped_for_review',error=str(exc));c.checkpoint();print(json.dumps({k:c.state.get(k) for k in ['pid','status','current','error']}),flush=True)
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
