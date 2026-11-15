"""Parent-executed second Lucky Dragon UI control, with a fresh native baseline.

This module performs no I/O on import and never writes reports/session files.
The parent owns runner.lock/STOP via VariantGate, the official FUN launcher,
source GET transport, and a PRIVATE checkpoint callback that saves cookies and
credentials. Historical sessions/HARs must never be restored for fresh_launch.
"""
import copy
import hashlib
import json
from urllib.parse import urlsplit
from lucky_dragon_controls import metadata,plan

GID='LuckyDragonMultiDiceX'
BASE='https://cdn.bgaming-network.com/html/'+GID+'/'
VERSION='v0.0.101_v14.19.2'
SOURCE_SHA256='7239c8d43ffd29336dd4e4a9b18052fd1f4c03eec3d5319664bdf2459c51122b'
LOADER_SHA256='96f8ecb3587818254dc7f7e14ee48fff47d789928ff93307bf7024b17d640e6e'

def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _native_balance(response):
 balance=response.get('balance',{})
 if set(balance)!= {'wallet','game'} or any(type(balance[k]) is not int or balance[k]<0 for k in balance):raise ValueError('Unverified native wallet/game observation')
 return copy.deepcopy(balance)

def _proof(source_raw,initial):
 if not isinstance(source_raw,bytes) or hashlib.sha256(source_raw).hexdigest()!=SOURCE_SHA256:raise ValueError('Lucky Dragon source differs from pinned official client')
 source=source_raw.decode('utf8');meta=metadata(source)
 tokens=['reCalcIsBonusBought(t,e=!1){var i,n=null===(i=t.flow.purchased_feature)','this._setActiveFeature(n,t.flow.purchased_feature.level)','playGame(t,e=!1,i=!1,n=!1,r=!1,a={})','e&&(h.command="freespin"),n&&(h.command="respin")','var{purchased_feature:t,purchased_feature_level:e,...i}=this.additionalSpinOptions;return i']
 if not all(t in source for t in tokens):raise ValueError('Native receipt display/automatic continuation source not proved')
 fm=initial['options']['feature_options']['feature_multipliers'];tiers=fm.get('bonus_buy',{})
 aliases={}
 for index in (0,1):
  feature=f'bonus_buy_{index}_chance';level=f'bonus_buy_{index}'
  if type(fm.get(feature)) is not int or fm[feature]<=0 or fm[feature]!=tiers.get(level):raise ValueError('Source UI/native price tier correspondence changed')
  aliases[feature]={'name':'bonus_buy','level':level}
 meta.update(client_version=VERSION,source_url=BASE+VERSION+'/bundle.js',loader_sha256=LOADER_SHA256,receipt_aliases=aliases,receipt_alias_basis='Literal paired UI controls, matching native price registry tiers, accepted historical tier0 anchor; actual tier1 receipt is checked after the one requested spin.',automatic_continuations=['respin','freespin'])
 return meta

def _receipt(response,feature,meta):
 expected=meta['receipt_aliases'][feature];actual=response.get('flow',{}).get('purchased_feature')
 return dict(kind='lucky_dragon_receipt',requested_control=feature,expected=copy.deepcopy(expected),actual=copy.deepcopy(actual),ok=actual==expected)

def normalize_received(report,source_raw):
 """Return a derived report; preserve every original event/check/metadata field.

 Event3 is already closed. Its stale-context wallet check remains false and
 its financial result remains unverified. This function sends no requests.
 """
 result=copy.deepcopy(report);events=report.get('events',[])
 if report.get('game',{}).get('game_id')!=GID or len(events)!=4 or len(report.get('modes',[]))!=1 or report['modes'][0].get('status')!='closed':raise ValueError('Expected historical normal/rejection/first-control evidence differs')
 initial=events[0]['response'];meta=_proof(source_raw,initial);modes=plan(initial,meta)
 if [m['cost_native'] for m in modes]!=[10,300,1000]:raise ValueError('Historical native UI prices differ')
 rejected=events[2]
 if rejected.get('status')!=422 or rejected['request'].get('options')!={'bet':10,'purchased_feature':'bonus_buy','purchased_feature_level':'bonus_buy_0'} or rejected['response'].get('errors')!=[{'code':203,'desc':'invalid_options'}]:raise ValueError('Exact historical rejected generic purchase must remain preserved')
 accepted=events[3];response=accepted['response'];flow=response.get('flow',{})
 if accepted.get('status')!=200 or accepted['request'].get('command')!='spin' or accepted['request'].get('options')!=modes[1]['options'] or flow.get('state')!='closed' or response.get('outcome',{}).get('bet')!=10:raise ValueError('Already-received first control is not the expected closed native spin')
 receipt=_receipt(response,modes[1]['name'],meta)
 if not receipt['ok']:raise ValueError('Historical tier0 native receipt anchor differs')
 old=_native_balance(events[1]['response']);actual=_native_balance(response);expected=old['wallet']+old['game']-300
 failed=dict(expected=expected,actual=actual['wallet'],ok=False)
 if expected==actual['wallet'] or not report.get('checks') or report['checks'][-1]!=failed:raise ValueError('Historical failed financial check must not be replaced or reinterpreted')
 result['modes'].append(dict(mode=copy.deepcopy(modes[1]),status='closed',first_event=3,last_event=3,final_balance=actual,final_state='closed',financial_verified=False,financial_status='unverified_prior_context_baseline',failed_check_index=len(report['checks'])-1,receipt_check=receipt,no_resend=True))
 result['historical_control_normalization']=dict(event=3,closed=True,financial_verified=False,source_sha256=SOURCE_SHA256,reason='Native response already closed; stale-context financial check retained without repair. New work must use a separate fresh initialization baseline.')
 result['status']='needs_review'
 return result

def _validate_fresh(demo,initial):
 bootstrap=getattr(demo,'bootstrap',{})
 if getattr(demo,'game',{}).get('game_id')!=GID or any(bootstrap.get(k)!=v for k,v in [('identifier',GID),('currency','FUN'),('server_id','demo')]):raise ValueError('Independent official FUN launch identity not established')
 u=urlsplit(demo.game.get('demo_url',''))
 if u.scheme!='https' or u.hostname!='demo.bgaming-network.com' or u.path!='/play/'+GID+'/FUN' or u.query!='server=demo':raise ValueError('Fresh launcher must use the official catalog FUN URL')
 events=getattr(demo,'events',[])
 if len(events)!=1 or events[0].get('request',{}).get('command')!='init' or initial.get('api_version')!='2' or initial.get('flow',{}).get('state')!='ready' or 'spin' not in initial['flow'].get('available_actions',[]):raise ValueError('Fresh context must contain only its authoritative ready init')
 if getattr(demo,'prev',None) is not None:raise ValueError('Fresh context already carries previous game state')
 _native_balance(initial)

def _run_remaining(demo,initial,meta,gate,checkpoint):
 modes=plan(initial,meta)
 remaining=[m for m in modes if m['name']=='bonus_buy_1_chance']
 if len(remaining)!=1 or remaining[0]['options']!={'bet':10,'purchased_feature':'bonus_buy_1_chance'} or remaining[0]['cost_native']!=1000:raise ValueError('Fresh init no longer proves the remaining minimum native control')
 mode=remaining[0];before=_native_balance(initial)
 if before['wallet']<1000:raise ValueError('Fresh FUN balance insufficient for source-native remaining control')
 demo.protocol_metadata={**copy.deepcopy(getattr(demo,'protocol_metadata',{})),**meta};demo.active_mode=copy.deepcopy(mode)
 start=len(demo.events);gate.check();checkpoint('before_remaining_control',dict(mode=mode,native_initial=copy.deepcopy(initial),native_baseline=before))
 response=demo.call('spin',copy.deepcopy(mode['options']))
 checkpoint('remaining_control_received',dict(response=copy.deepcopy(response),events=copy.deepcopy(demo.events)))
 actual=_native_balance(response);expected=before['wallet']-1000
 check=dict(kind='lucky_dragon_fresh_native_debit',baseline_authority='fresh_official_FUN_init',expected=expected,actual=actual['wallet'],cost_native=1000,ok=actual['wallet']==expected)
 demo.money_checks.append(check)
 if not check['ok']:raise RuntimeError('Fresh native remaining-control debit mismatch; no retry')
 receipt=_receipt(response,mode['name'],meta);demo.money_checks.append(receipt)
 if not receipt['ok']:raise RuntimeError('Actual remaining-control receipt differs; no retry')
 if response.get('outcome',{}).get('bet')!=10:raise RuntimeError('Actual remaining-control native bet differs; no retry')
 for step in range(500):
  flow=response.get('flow',{})
  if flow.get('state')=='closed':break
  actions=[a for a in flow.get('available_actions',[]) if a!='init']
  if len(actions)!=1 or actions[0] not in meta['automatic_continuations']:raise RuntimeError('Unproved Lucky Dragon continuation/choice preserved for review')
  command=actions[0];old=_native_balance(response);gate.check();checkpoint('before_automatic_continuation',dict(command=command,response=copy.deepcopy(response)))
  response=demo.call(command)
  checkpoint('automatic_continuation_received',dict(command=command,response=copy.deepcopy(response),events=copy.deepcopy(demo.events)))
  current=_native_balance(response);check=dict(kind='lucky_dragon_native_continuation_wallet',command=command,expected=old['wallet'],actual=current['wallet'],ok=current['wallet']==old['wallet']);demo.money_checks.append(check)
  if not check['ok']:raise RuntimeError('Native automatic continuation wallet changed; stop for review')
 else:raise RuntimeError('Lucky Dragon automatic continuation bound reached')
 demo.prev=response
 return dict(mode=copy.deepcopy(mode),status='closed',first_event=start,last_event=len(demo.events)-1,final_balance=_native_balance(response),final_state='closed',financial_verified=True,receipt_check=receipt)

def finish(report,*,gate,fresh_launch,fetch_source,private_checkpoint,old_private_context=None):
 """Launch/init once, execute ONLY remaining UI chance1, return a derived report.

 fresh_launch() must create an independent Demo/opener/cookie jar from the
 official catalog FUN URL and return (demo, actual_init). Never restore an
 old or HAR session. Parent callback snapshots both contexts privately.
 """
 gate.check()
 private_checkpoint('historical_context_preserved',dict(report=copy.deepcopy(report),private_context=copy.deepcopy(old_private_context),prior_last_launch_epoch=gate.last_launch_epoch))
 gate.check();loader=fetch_source(BASE+'loader.js');gate.check();source=fetch_source(BASE+VERSION+'/bundle.js')
 if not isinstance(loader,bytes) or hashlib.sha256(loader).hexdigest()!=LOADER_SHA256:raise ValueError('Fresh Lucky Dragon loader changed')
 normalized=normalize_received(report,source)
 started=gate.reserve()
 gate.check();private_checkpoint('before_independent_official_FUN_launch',dict(game_id=GID,last_launch_epoch=started))
 demo,initial=fresh_launch()
 try:
  _validate_fresh(demo,initial);meta=_proof(source,initial)
  private_checkpoint('independent_init_received',dict(initial=copy.deepcopy(initial),events=copy.deepcopy(demo.events),last_launch_epoch=started))
  mode=_run_remaining(demo,initial,meta,gate,private_checkpoint)
 except Exception as error:
  private_checkpoint('fresh_control_requires_review',dict(error_type=type(error).__name__,events=copy.deepcopy(getattr(demo,'events',[])),checks=copy.deepcopy(getattr(demo,'money_checks',[])),last_launch_epoch=started))
  raise
 offset=len(normalized['events'])
 old_events=[dict(copy.deepcopy(event),session_context='historical',event_alias_id=f'historical:{index}') for index,event in enumerate(normalized['events'])]
 new_events=[dict(copy.deepcopy(event),session_context='fresh_control1',event_alias_id=f'fresh_control1:{index}') for index,event in enumerate(demo.events)]
 mode['first_event']+=offset;mode['last_event']+=offset;mode['session_context']='fresh_control1';normalized['modes'].append(mode)
 normalized['events']=old_events+new_events
 normalized['checks']+= [dict(copy.deepcopy(check),session_context='fresh_control1') for check in demo.money_checks]
 normalized['session_contexts']=[dict(id='historical',first_event=0,last_event=offset-1,initial_event=0,native_initial_balance=_native_balance(report['events'][0]['response']),financial_continuity_verified=False),dict(id='fresh_control1',first_event=offset,last_event=len(normalized['events'])-1,initial_event=offset,native_initial_balance=_native_balance(initial),baseline_authority='fresh_official_FUN_init',continuity_with_previous_context_required=False,initial_sha256=_hash(initial))]
 normalized['initialization_observations']=[dict(session_context='historical',event=0,balance=_native_balance(report['events'][0]['response'])),dict(session_context='fresh_control1',event=offset,balance=_native_balance(initial),authoritative_for_remaining_control=True,not_a_wallet_transfer=True)]
 normalized['fresh_context_protocol_metadata']=meta;normalized['remaining_control_status']='closed_native_financial_verified';normalized['status']='needs_review'
 normalized['reason']='Historical first UI control is closed with its failed prior-context financial check preserved; remaining control verified independently from fresh native init.'
 private_checkpoint('derived_report_ready',dict(report=copy.deepcopy(normalized),fresh_events=copy.deepcopy(demo.events),fresh_checks=copy.deepcopy(demo.money_checks),last_launch_epoch=started))
 return normalized
