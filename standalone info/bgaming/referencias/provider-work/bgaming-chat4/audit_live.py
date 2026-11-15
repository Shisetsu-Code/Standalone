"""Independent read-only audit of sanitized live evidence; no network or replay."""
import json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent

def audit(report):
 events=report.get('events',[]);checks=[];previous=None;options={}
 if report.get('protocol')=='lucky-lady-finite-contexts':
  from run_lucky_lady_cards import audit_context
  old,child=report['contexts'];original=audit(old['report']);added=audit_context(child['report'],report['protocol_metadata']['finite_card_source'])
  combined=[dict(check,context_id=old['context_id']) for check in original['checks']]+[dict(check,context_id=child['context_id']) for check in added['checks']]
  return dict(game_id=report['game']['game_id'],status=report['status'],events=original['events']+len(child['report'].get('events',[])),checks=combined,passed=sum(c.get('ok') is True for c in combined),failed=sum(c.get('ok') is not True for c in combined),modes_closed=sum(m.get('status')=='closed' for m in report['modes']),finite_card_coverage=added)
 if report.get('protocol')=='jsonrpc-four-modern-slots':
  from four_modern_slots import audit as audit_four
  checks,rounds=audit_four(events[0]['response'],events,report['protocol_metadata'])
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(c['ok'] for c in checks),failed=sum(not c['ok'] for c in checks),modes_closed=sum(m.get('status')=='closed' for m in report['modes']))
 if report.get('protocol')=='all-lucky-selector-contexts':
  from all_lucky_catalog_report import audit_parent
  return audit_parent(report)
 if report.get('protocol')=='wild-moon-manual-contexts':
  from run_wild_moon_manual import audit_manual_context
  old,manual=report['contexts'];original=audit(old['report']);added=audit_manual_context(manual['report'],report['protocol_metadata']['manual_door_source'])
  combined=[dict(check,context_id=old['context_id']) for check in original['checks']]+[dict(check,context_id=manual['context_id']) for check in added['checks']]
  return dict(game_id=report['game']['game_id'],status=report['status'],events=original['events']+added['events'],checks=combined,passed=sum(c.get('ok') is True for c in combined),failed=sum(c.get('ok') is not True for c in combined),modes_closed=sum(m.get('status')=='closed' for m in report['modes']),manual_door_coverage=added)
 if report.get('protocol')=='jsonrpc-final-pair':
  from final_rpc_pair import audit_report
  return audit_report(report)
 if report.get('protocol')=='blackjack-extra':
  from blackjack_extra import audit as audit_blackjack
  return audit_blackjack(report)
 if report.get('protocol_metadata',{}).get('dig_choices_helper_verified'):
  from bonus_choices_extra import audit_dig
  return audit_dig(report)
 if report.get('protocol')=='native-modes-extra':
  from native_modes_extra import audit as audit_native
  return audit_native(report)
 if report.get('protocol') in ['native-rocket-dice','native-mine-ladder']:
  from native_tables_extra import reconcile,_available
  for i,event in enumerate(events):
   q=event['request'];command=q.get('command')
   if command=='init':previous=event['response'];continue
   if event.get('status')!=200:continue
   if command not in ['roll','risk','finish','start','step','stop']:raise ValueError('Unknown native table audit command')
   cost=q.get('options',{}).get('bet',0) if command in ['roll','start'] else 0;checks.append(dict(event=i,kind='native_command_allowed',ok=_available(previous,command)));before=previous if report['protocol']=='native-rocket-dice' else previous['balance'];checks.append(dict(event=i,**reconcile(before,event['response'],cost,protocol=report['protocol'],command=command)));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='jsonrpc-rpc-extra':
  from rpc_extra import audit as audit_extra
  checks,rounds=audit_extra(events[0]['response'],events,report['protocol_metadata'])
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol') in ['jsonrpc-lucky-birds','jsonrpc-flat']:
  if report['protocol']=='jsonrpc-lucky-birds':
   from lucky_birds import audit as audit_custom
  else:
   from flat_rpc import audit as audit_custom
  checks,rounds=audit_custom(events[0]['response'],events)
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='classic-roulette':
  from classic_roulette import spin_result,finish_result
  for i,event in enumerate(events):
   command=event.get('request',{}).get('command')
   if command=='init':previous=event['response'];continue
   if event.get('status')!=200:continue
   if command=='spin':check=spin_result(previous['balance'],event['response'],sum(b['amount'] for b in event['request']['options']))
   elif command=='finish':check=finish_result(previous,event['response'])
   else:raise ValueError('Unknown roulette action')
   checks.append(dict(event=i,**check));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol') in ['legacy-limbo','native-play-modes','royal-roulette']:
  if report['protocol']=='legacy-limbo':
   from limbo import settled
   command='spin'
  elif report['protocol']=='native-play-modes':
   from native_play_modes import settled
   command='play'
  else:
   from royal_roulette import settled
   command='play'
  for i,event in enumerate(events):
   if event.get('request',{}).get('command')=='init':previous=event['response'];continue
   if event.get('status')!=200:continue
   if event['request'].get('command')!=command:raise ValueError('Unknown native mode action')
   args=event['request']['options'];cost=sum(b['amount'] for b in args['bets']) if report['protocol']=='royal-roulette' else args['bet'];checked=settled(previous['balance'],event['response'],cost);checks.append(dict(event=i,**checked['check']));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='classic-heads':
  from classic_heads import settled
  for i,event in enumerate(events):
   if event.get('request',{}).get('command')=='init':previous=event.get('response');continue
   if event.get('status')!=200:continue
   if event.get('request',{}).get('command')!='flip':raise ValueError('Unverified coin audit action')
   checked=settled(previous['balance'],event['response'],event['request']['options']['bet']);checks.append(dict(event=i,**checked['check']));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='legacy-plinko':
  from classic_plinko import closed_result
  for i,event in enumerate(events):
   if event.get('request',{}).get('command')=='init':previous=event.get('response');continue
   if event.get('status')!=200:continue
   if event.get('request',{}).get('command')!='play':raise ValueError('Unverified classic Plinko audit action')
   checked=closed_result(previous['balance'],event['response'],event['request']['options']['bet']);checks.append(dict(event=i,**checked['check']));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='legacy-v1-slots':
  from old_slots import paid_result,free_result
  for i,event in enumerate(events):
   if event.get('request',{}).get('command')=='init':previous=event.get('response');options=previous.get('options',{});continue
   if event.get('status')!=200:continue
   command=event.get('request',{}).get('command')
   if command=='check_card':
    from classic_gamble import check_event
    checks.append(dict(event=i,**check_event(previous,event,report['protocol_metadata'])));previous=event['response'];continue
   if command=='finish':
    from classic_gamble import check_finish
    checks.append(dict(event=i,**check_finish(previous,event['response'],report['protocol_metadata'])));previous=event['response'];continue
   if command!='spin':raise ValueError('Unverified V1 audit continuation')
   args=event['request']['options']
   if previous.get('game',{}).get('state')=='freespin':
    checked=free_result(previous,event['response'],args,report['protocol_metadata']);checks.append(dict(event=i,**checked['check']));previous=event['response'];continue
   bets=event['request']['options']['bets'];cost=sum(bets.values())
   if args.get('buy_feature'):
    if not report['protocol_metadata'].get('v1_buy_feature_verified') or type(options.get('buy_feature_value')) is not int:raise ValueError('Unverified V1 purchase price')
    cost*=options['buy_feature_value']
   checked=paid_result(previous,event['response'],{'cost_native':cost},report['protocol_metadata']);checks.append(dict(event=i,**checked['check']));previous=event['response']
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='jsonrpc-product-round':
  from product_round_rpc import audit as audit_products
  checks,rounds=audit_products(report.get('initial') or events[0]['response'],events,report['protocol_metadata'])
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='jsonrpc-cocos':
  from cocos_audit import audit as audit_cocos
  checks,rounds=audit_cocos(report.get('initial') or events[0]['response'],events,report['protocol_metadata'])
  return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 if report.get('protocol')=='jsonrpc' or report.get('bootstrap',{}).get('protocol')=='jsonrpc':
  from rpc_audit_hotrocket import audit_rpc
  gid=report['game']['game_id'];initial=report.get('initial') or events[0]['response'];play=[e for e in events if e['request'].get('method')=='play'];metadata=report.get('protocol_metadata',{})
  if not metadata and (ROOT/'protocols'/(gid+'.json')).exists():metadata=json.loads((ROOT/'protocols'/(gid+'.json')).read_text(encoding='utf8'))
  factors={None:'1',**metadata.get('features',{})}
  if gid=='HotRocketMegaPotz':
   from rpc_audit_hotrocket import FACTORS
   factors=FACTORS
  checks,rounds=audit_rpc(initial,play,factors,metadata.get('variants'))
  return dict(game_id=gid,status=report['status'],events=len(events),checks=checks,rounds=rounds,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
 for i,event in enumerate(events):
  r=event.get('response',{});q=event.get('request',{});cmd=q.get('command');b=r.get('balance');flow=r.get('flow',{})
  if cmd=='init':options=r.get('options',{});previous=r if b else None;continue
  if not b or not previous:continue
  old=previous['balance'];args=q.get('options',{});cost=0
  if isinstance(b,(int,float)) and isinstance(old,(int,float)):
   cost=sum(x.get('amount',0) for x in args.get('bets',[])) if 'bets' in args else args.get('bet',0)
   bets_result=r.get('bets',{});win=bets_result.get('win_amount') if isinstance(bets_result,dict) else None
   if 'freespin_buy_miltipliers' in options and isinstance(args.get('purchased_feature'),dict):
    from fractions import Fraction
    surcharge=sum((Fraction(str(options['freespin_buy_miltipliers'][f])) for f in args['purchased_feature']),Fraction(0));cost=int(Fraction(args['bet'])*(1+surcharge))
    outcome=r.get('game',{}).get('outcome',[])
    if outcome and all(isinstance(x,list) and x for x in outcome):win=sum(x[0] for x in outcome)
   if isinstance(win,(int,float)):checks.append(dict(event=i,kind='scalar_balance',expected=old-cost+win,actual=b,ok=old-cost+win==b,cost_native=cost,win_native=win))
   checks.append(dict(event=i,kind='allowed_command',ok=cmd in previous.get('available_commands',[])))
   previous=r;continue
  if report.get('protocol_metadata',{}).get('scratch_packs_verified'):
   from scratch_packs import cost as scratch_cost
   from fractions import Fraction
   cost=scratch_cost(args,options,cmd);win=r.get('outcome',{}).get('win');allowed=previous.get('flow',{}).get('available_actions',[])
   if type(win) not in [int,float]:raise ValueError('Scratch native win missing')
   expected=Fraction(str(old['wallet']))+Fraction(str(old['game']))-cost+Fraction(str(win));actual=Fraction(str(b['wallet']))+Fraction(str(b['game']));checks.append(dict(event=i,kind='scratch_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_ratio=[actual.numerator,actual.denominator],cost_native=cost,win_native=win,ok=expected==actual));checks.append(dict(event=i,kind='allowed_command',ok=cmd in allowed));previous=r;continue
  if cmd=='spin' or (cmd=='play' and report.get('protocol_metadata',{}).get('fixed_play_verified')):
   cost=args['bet'];feature=args.get('purchased_feature')
   if feature:
    confirmation=r.get('flow',{}).get('purchased_feature',{})
    if report['game']['game_id']=='LuckyDragonMultiDiceX' and report.get('fresh_context_protocol_metadata'):
     from finish_lucky_dragon_controls import _receipt,SOURCE_SHA256
     meta=report['fresh_context_protocol_metadata']
     if meta.get('source_sha256')!=SOURCE_SHA256:raise ValueError('Lucky Dragon receipt source differs')
     checks.append(dict(event=i,**_receipt(r,feature,meta)))
    else:checks.append(dict(event=i,kind='purchased_feature_name',expected=feature,actual=confirmation.get('name'),ok=confirmation.get('name')==feature))
    if 'purchased_feature_level' in args:
     level=confirmation.get('level');checks.append(dict(event=i,kind='purchased_feature_level',expected=args['purchased_feature_level'],actual=level,ok=level is not None and str(level)==str(args['purchased_feature_level'])))
   if report.get('protocol_metadata',{}).get('gold_symbols_factors'):
    cost*=report['protocol_metadata']['gold_symbols_factors'][args['gold_symbols_count']]
   if report.get('protocol_metadata',{}).get('line_count_modes'):
    cost*=report['protocol_metadata']['line_count_modes'][args['mode']]
   variants=report.get('protocol_metadata',{}).get('native_variants')
   if variants:
    from fractions import Fraction
    selected=variants[int(args['mode'])];cost=Fraction(cost)*Fraction(str(selected['base_bet']))/Fraction(str(variants[0]['base_bet']))
    if feature and feature!=selected.get('request_options',{}).get('purchased_feature'):cost*=Fraction(next(b['price'] for b in selected['buys'] if b['name']==feature))
    if cost.denominator!=1:raise ValueError('Fractional native variant cost')
    cost=int(cost)
   elif feature:
    fm=options['feature_options']['feature_multipliers'];factor=fm[feature]
    if isinstance(factor,dict):factor=factor[args['purchased_feature_level']]
    numerator=cost*factor;denominator=fm.get('base_bet') or report.get('protocol_metadata',{}).get('feature_default_base_bet')
    if not denominator:checks.append(dict(event=i,kind='cost',ok=False,reason='Unverified omitted price denominator'));continue
    quotient,remainder=divmod(numerator,denominator)
    if remainder:
     kind='antebet' if feature.endswith('_chance') else 'purchase'
     if report.get('protocol_metadata',{}).get('price_rounding',{}).get(kind)!='ceil':checks.append(dict(event=i,kind='cost',ok=False,reason='Fractional cost not verified'));continue
    cost=quotient+(1 if remainder else 0)
   elif args.get('rows') is not None and report.get('protocol_metadata',{}).get('rows_normal_factors'):
    from fractions import Fraction
    value=Fraction(cost)*Fraction(report['protocol_metadata']['rows_normal_factors'][args['rows']]);assert value.denominator==1;cost=int(value)
  elif cmd=='buy_extra_bonus':
   cost=previous['features']['bonus_data']['bonus_game_prices'][args['bonus_type']]
   checks.append(dict(event=i,kind='extra_bonus_wallet',expected=old['wallet']-cost,actual=b['wallet'],cost_native=cost,ok=old['wallet']-cost==b['wallet']))
  oldtotal=old['wallet']+old['game'];newtotal=b['wallet']+b['game'];win=r.get('outcome',{}).get('win')
  if isinstance(win,int):checks.append(dict(event=i,kind='total_balance',expected=oldtotal-cost+win,actual=newtotal,ok=oldtotal-cost+win==newtotal,cost_native=cost,win_native=win))
  allowed=previous.get('flow',{}).get('available_actions',[]);checks.append(dict(event=i,kind='allowed_command',ok=cmd in allowed))
  previous=r
 return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),modes_closed=sum(x['status']=='closed' for x in report.get('modes',[])))
if __name__=='__main__':
 reports=[]
 for p in sorted((ROOT/'live').glob('*.json')):
  try:
   report=json.loads(p.read_text(encoding='utf8'));checked=audit(report)
   if report.get('revalidation'):
    import hashlib
    history=ROOT/report['revalidation']['historical_report_archive'];raw=history.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=report['revalidation']['historical_report_sha256']:raise ValueError('Historical report digest mismatch')
    prior=audit(json.loads(raw));checked['historical_failed_checks']=prior.get('failed',0);checked['historical_report_archive']=str(history.relative_to(ROOT));checked['fresh_revalidation_verified']=checked.get('failed')==0
   reports.append(checked)
  except Exception as e:reports.append(dict(game_id=p.stem,audit_error=type(e).__name__))
 result=dict(audited_at=datetime.now(timezone.utc).isoformat(),reports=reports,passed=sum(x.get('passed',0) for x in reports),failed=sum(x.get('failed',0) for x in reports))
 result['historical_failed_checks_preserved']=sum(r.get('historical_failed_checks',0) for r in reports)
 (ROOT/'live-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 print('Live audit:',result['passed'],'passed;',result['failed'],'failed;',len(reports),'game reports')
 for r in reports:
  if r.get('failed') or r.get('audit_error'):print('Review:',r['game_id'],r.get('audit_error'),r.get('failed'))
