"""Explicit fresh FUN revalidation; historical failed evidence is never rewritten."""
import copy,hashlib,json,time,sys
from run_demo_qa import Demo,ROOT,PRIVATE,save,now,modes_from_init,completion_status,retain_launch_evidence
from checkpoint_guard import acquire,require_inactive
from bonus_choices_extra import metadata as choice_metadata,prepare,check_event
from legacy_metadata import load_client
from lucky_dragon_controls import plan as dragon_plan
from finish_lucky_dragon_controls import _proof as dragon_proof,_receipt

TARGETS=('TheGodfather3PillarsOfPower','RocketEruptionTripleBlast','LuckyDragonMultiDiceX','DigDigDigger')
class FreshSlot(Demo):
 def __init__(self,game,private_path):
  super().__init__(game);self.private_session_path=private_path;self.verified_choices=[];self.card_budget_used=0
 def launch(self):
  initial=super().launch();gid=self.game['game_id']
  if gid in ('DigDigDigger','LuckyDragonMultiDiceX'):
   info,source=load_client(gid,self.opener)
   if gid=='DigDigDigger':
    self.choice_proof=choice_metadata(gid,source);self.protocol_metadata.update(dig_choices_helper_verified=True,dig_choice_source=self.choice_proof)
   else:
    self.protocol_metadata.update(dragon_proof(source.encode('utf8'),initial));self.fresh_context_protocol_metadata=self.protocol_metadata
  return initial
 def call(self,command,options=None):
  before=copy.deepcopy(getattr(self,'last_response',None));gid=self.game['game_id']
  if before is not None:
   if command not in before.get('flow',{}).get('available_actions',[]):raise ValueError('Fresh action not advertised')
   if gid=='DigDigDigger' and command in ('gamble','close'):
    choice='collect' if command=='close' else (options or {}).get('bet')
    expected=prepare(before,self.choice_proof,choice);request={'command':command}
    if options is not None:request['options']=options
    if request!=expected:raise ValueError('Fresh semantic choice differs from source')
  response=super().call(command,options)
  if before is None or command=='init':return response
  index=len(self.events)-1
  if gid=='DigDigDigger' and command in ('gamble','close'):
   request={'command':command}
   if options is not None:request['options']=options
   checked=check_event(before,dict(request=request,response=response,status=200),self.choice_proof)
   if command=='gamble':self.verified_choices.append(options['bet']);self.card_budget_used+=before['balance']['game']
  else:
   old=before['balance'];cost=self.active_mode['cost_native'] if command=='spin' else 0
   expected=old['wallet']+(old['game'] if before['flow']['state']=='closed' else 0)-cost;actual=response['balance']['wallet']
   checked=dict(kind='fresh_native_debit_or_continuation',cost_native=cost,expected=expected,actual=actual,ok=expected==actual)
   if not checked['ok']:self.money_checks.append(checked);raise ValueError('Fresh native wallet differs; original receipt retained')
  self.money_checks.append(dict(event=index,**checked))
  if gid=='LuckyDragonMultiDiceX' and command=='spin' and options.get('purchased_feature'):
   receipt=_receipt(response,options['purchased_feature'],self.protocol_metadata);self.money_checks.append(dict(event=index,**receipt))
   if not receipt['ok']:raise ValueError('Fresh source receipt tier differs')
  return response
 def settle(self,response):
  gid=self.game['game_id']
  if gid not in ('DigDigDigger','LuckyDragonMultiDiceX'):return super().settle(response)
  choice_used=False
  for _ in range(500):
   flow=response['flow'];actions=[a for a in flow['available_actions'] if a!='init']
   if flow['state']=='closed':return response
   if gid=='DigDigDigger' and flow['state']=='gamble':
    target=self.active_mode.get('gamble_choice')
    if target and not choice_used and self.card_budget_used+response['balance']['game']<=5000:
     response=self.call('gamble',{'bet':target});choice_used=True
    else:response=self.call('close')
   elif len(actions)==1 and actions[0] in ('freespin','respin','play_bonus'):
    response=self.call(actions[0],self.continuation_options(actions[0]))
   else:raise ValueError('Unknown fresh slot continuation; no input sent')
  raise ValueError('Fresh bonus exceeds finite bound')
 def run_mode(self,mode,initial):
  if self.game['game_id']!='LuckyDragonMultiDiceX':return super().run_mode(mode,initial)
  before=self.prev or initial
  if before['balance']['wallet']+before['balance']['game']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
  self.active_mode=mode;start=len(self.events);response=self.call('spin',mode['options']);response=self.settle(response);self.prev=response
  return dict(mode=mode,status='closed',first_event=start,last_event=len(self.events)-1,final_balance=response['balance'],final_state=response['flow']['state'])

def run_one(gid,state):
 if gid not in TARGETS:raise ValueError('Only the four authorized slots may be revalidated')
 original_path=ROOT/'live'/(gid+'.json');original=original_path.read_bytes();old=json.loads(original)
 work=PRIVATE/'fresh-financial-revalidation'/gid;work.mkdir(parents=True,exist_ok=False)
 archive=ROOT/'live/attempts'/(gid+'.before-fresh-financial-revalidation.json')
 if archive.exists():raise ValueError('Existing revalidation attempt; inspect received evidence instead of repeating')
 archive.write_bytes(original);save(work/'attempt.json',dict(game_id=gid,created_at=now(),original_public_sha256=hashlib.sha256(original).hexdigest(),policy='Fresh official FUN only; no captured session reuse'))
 game=next(g for g in json.loads((ROOT/'catalog-live.json').read_text())['games'] if g.get('game_id')==gid)
 if game.get('game_type')!='Slots':raise ValueError('Only slots are authorized')
 while time.time()-state['last_launch_epoch']<60:time.sleep(min(1,60-(time.time()-state['last_launch_epoch'])))
 state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
 d=FreshSlot(game,work/'session.json');path=ROOT/'live/fresh-financial-revalidation'/(gid+'.json');r=dict(game=game,status='starting',started_at=now(),modes=[],events=[],checks=[],historical_report_archive=str(archive.relative_to(ROOT)),historical_report_sha256=hashlib.sha256(original).hexdigest())
 def persist():
  r.update(events=d.events,checks=d.money_checks);retain_launch_evidence(r,d)
  if hasattr(d,'fresh_context_protocol_metadata'):r['fresh_context_protocol_metadata']=d.fresh_context_protocol_metadata
  save(path,r)
 save(path,r)
 try:
  initial=d.launch();meta=d.protocol_metadata;r['declared_modes']=dragon_plan(initial,meta) if gid=='LuckyDragonMultiDiceX' else modes_from_init(initial,meta);r.update(status='running');persist()
  for mode in r['declared_modes']:
   r['modes'].append(d.run_mode(mode,initial));persist()
  if gid=='DigDigDigger':
   from resume_dig_choices import conditional_modes
   targets=conditional_modes(initial,d.choice_proof)
   for target in targets:target.update(maximum_paid_attempts=100,attempt_limit_scope='100 total across the six finite choices')
   r['declared_modes'].extend(targets);r['finite_choice_limits']=dict(max_total_trigger_attempts=100,gross_native_budget=5000);attempts=0
   for mode in targets:
    seen_start=len(d.verified_choices);history=[]
    while attempts<100:
     attempts+=1;d.card_budget_used+=mode['cost_native'];result=d.run_mode(mode,initial);history.append(copy.deepcopy(result))
     if mode['gamble_choice'] in d.verified_choices[seen_start:]:break
     if result['status']!='closed' or d.card_budget_used+mode['cost_native']>5000:break
    else:result=dict(mode=mode,status='needs_trigger',reason='Explicit 100 trigger attempt limit')
    if mode['gamble_choice'] not in d.verified_choices[seen_start:]:result['status']='needs_trigger'
    result['attempts']=history;r['modes'].append(result);persist()
   r['finite_choices_verified']=sorted(set(d.verified_choices));r['card_trigger_attempts']=attempts
  r['status']=completion_status(r,d.protocol_metadata);persist()
  from audit_live import audit
  independent=audit(r);r['independent_audit']=independent
  if independent.get('failed') or independent.get('audit_error'):r['status']='needs_review'
 except Exception as error:r.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
 finally:
  r['finished_at']=now();persist();state.update(active_game=None,updated_at=now());state.setdefault('financial_revalidation',{})[gid]=dict(status=r['status'],report=str(path.relative_to(ROOT)),private_checkpoint='fresh-financial-revalidation/'+gid+'/session.json');save(ROOT/'run-state.json',state)
 print(gid,r['status'],'closed',sum(m.get('status')=='closed' for m in r['modes']),r.get('reason',''),flush=True)

if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text());require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause the main queue before explicit revalidation')
 for gid in (sys.argv[1:] or TARGETS):run_one(gid,state)
