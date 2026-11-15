"""Offline selector aggregation, retaining independent native game contexts."""
import copy,json
from run_demo_qa import ROOT,save,now
from all_lucky_variants import VARIANTS,BUNDLE_SHA256
def audit_variant(report):
 gid=report['game']['game_id'];events=report.get('events',[]);meta=report['protocol_metadata'];checks=[]
 if gid not in VARIANTS or meta.get('source_sha256')!=BUNDLE_SHA256 or not events:raise ValueError('Pinned selector-variant evidence required')
 first=events[0]
 if first.get('status')!=200 or first['request'].get('command')!='init':raise ValueError('Original variant initialization required')
 initial=first['response'];currency=initial['options']['currency']
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Original native FUN units required')
 if initial.get('api_version')!='2':
  from audit_live import audit
  return audit(report)
 before=initial;paid=0;closed=0
 for i,event in enumerate(events[1:],1):
  r=event['response'];q=event['request'];command=q.get('command');allowed=before['flow']['available_actions'];old=before['balance'];new=r['balance']
  if event.get('status')!=200 or command not in allowed or r.get('errors'):raise ValueError('Variant action not accepted/advertised')
  if command=='spin':
   bet=min(initial['options']['available_bets'])
   if q.get('options')!={'bet':bet} or before['flow']['state'] not in ('ready','closed'):raise ValueError('Unproved variant native normal trigger')
   win=r['outcome']['win'];expected=old['wallet']+(old['game'] if before['flow']['state']=='closed' else 0)-bet+win;actual=new['wallet']+new['game'];paid+=1
   checks.append(dict(event=i,kind='selector_native_spin',cost_native=bet,win_native=win,expected=expected,actual=actual,ok=expected==actual))
  elif command=='close':
   if q.get('options') is not None or r['flow']['state']!='closed' or before['flow']['round_id']!=r['flow']['round_id']:raise ValueError('Unproved variant collection identity')
   expected=old['wallet']+old['game'];actual=new['wallet']+new['game'];checks.append(dict(event=i,kind='selector_native_collect',expected=expected,actual=actual,ok=expected==actual))
  else:raise ValueError('Unreviewed selector variant action')
  if r['flow']['state']=='closed':closed+=1
  before=r
 modes=report.get('modes',[]);complete=paid==1 and before['flow']['state']=='closed' and len(modes)==1 and modes[0].get('status')=='closed'
 checks.append(dict(kind='selector_variant_normal_closed',ok=complete))
 return dict(game_id=gid,status=report['status'],events=len(events),checks=checks,passed=sum(c['ok'] for c in checks),failed=sum(not c['ok'] for c in checks),modes_closed=sum(m.get('status')=='closed' for m in modes))
def audit_parent(report):
 checks=[];events=0
 for context in report['contexts']:
  result=audit_variant(context['report']);checks.extend(dict(c,context_id=context['context_id']) for c in result['checks']);events+=result['events']
 return dict(game_id='AllLuckyClover',status=report['status'],events=events,checks=checks,passed=sum(c['ok'] for c in checks),failed=sum(not c['ok'] for c in checks),modes_closed=sum(m.get('status')=='closed' for m in report['modes']))
def derive(original,children):
 if [r['game']['game_id'] for r in children]!=list(VARIANTS):raise ValueError('All four source variants required')
 audits=[audit_variant(r) for r in children]
 if any(a['failed'] for a in audits) or any(r['status']!='complete_declared_modes' for r in children):raise ValueError('Variant audit/closure incomplete')
 contexts=[dict(context_id=gid,report=copy.deepcopy(r)) for gid,r in zip(VARIANTS,children)]
 modes=[dict(copy.deepcopy(m),context_id=gid) for gid,r in zip(VARIANTS,children) for m in r['modes']]
 return dict(game=copy.deepcopy(original['game']),protocol='all-lucky-selector-contexts',status='complete_declared_modes',protocol_metadata=dict(selector_source_sha256=BUNDLE_SHA256,variants=list(VARIANTS),context_scoped_events=True),contexts=contexts,modes=modes,declared_modes=[dict(copy.deepcopy(m),context_id=gid) for gid,r in zip(VARIANTS,children) for m in r['declared_modes']],original_selector_report=copy.deepcopy(original),selector_redirect_evidence='all-lucky-redirect-observed.json',finished_at=now(),note='Four variants retain their actual FUN initializations and native money; no cross-context wallet transfer is asserted.')
if __name__=='__main__':
 from checkpoint_guard import acquire,require_inactive
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause queue first')
 path=ROOT/'live/AllLuckyClover.json';old=json.loads(path.read_text());archive=ROOT/'live/attempts/AllLuckyClover.before-four-variant-report.json'
 if archive.exists():raise ValueError('Selector report already integrated')
 children=[json.loads((ROOT/'live/selector-variants'/(gid+'.json')).read_text(encoding='utf8')) for gid in VARIANTS];report=derive(old,children);save(archive,old);save(path,report)
 state['results']['AllLuckyClover']=dict(status=report['status'],modes_closed=len(report['modes']),report='live/AllLuckyClover.json');state['variant_parents']={**state.get('variant_parents',{}),**dict.fromkeys(VARIANTS,'AllLuckyClover')};state['updated_at']=now();save(ROOT/'run-state.json',state);print('AllLucky selector four variants integrated, native audits passed')
