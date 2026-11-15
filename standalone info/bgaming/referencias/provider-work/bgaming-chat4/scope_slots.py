"""Offline slot-only execution scope; retain all historical non-slot evidence."""
import json,collections
from run_demo_qa import ROOT,save,now
def build():
 catalog=json.loads((ROOT/'catalog-live.json').read_text(encoding='utf8'))['games'];state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));entries=[]
 for game in catalog:
  gid=game.get('game_id');inside=game.get('game_type')=='Slots';path=ROOT/'live'/(str(gid)+'.json');report=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
  status=('running' if state.get('active_game')==gid else state['results'].get(gid,{}).get('status','queued')) if game.get('demo_url') else 'no_public_demo_link'
  entry=dict(game_id=gid,title=game['title'],game_type=game['game_type'],in_current_scope=inside,execution_status=status,historical_report=str(path.relative_to(ROOT)) if report else None,closed_modes=sum(m.get('status')=='closed' for m in report.get('modes',[])),declared_modes=len(report.get('declared_modes',[])))
  if not inside:entry['scope_reason']='Excluded by latest user instruction: slots only; historical evidence preserved'
  if inside and status not in ('complete_declared_modes','no_public_demo_link'):
   entry['reason']=report.get('reason');entry['conditional_targets_not_reached']=[m['mode']['name'] for m in report.get('modes',[]) if m.get('status')=='needs_trigger']
   entry['native_financial_checks_failed']=sum(check.get('ok') is False for check in report.get('checks',[]))
   entry['observed_closed_with_financial_issue']=bool(entry['native_financial_checks_failed']) and bool(report.get('modes')) and all(m.get('status') in ('closed','closed_financial_anomaly') for m in report['modes']) and len(report['modes'])==len(report.get('declared_modes',[]))
  entry['fresh_revalidation_verified']=report.get('revalidation',{}).get('current_native_checks_verified',False)
  entry['historical_failed_checks_preserved']=report.get('revalidation',{}).get('historical_failed_checks',0)
  closed_statuses={'closed','closed_financial_anomaly'}
  entry['execution_modes_closed']=bool(report.get('modes')) and len(report['modes'])==len(report.get('declared_modes',[])) and all(m.get('status') in closed_statuses for m in report['modes'])
  entry['execution_plan_fulfilled']=entry['execution_modes_closed'] or report.get('status')=='complete_declared_modes'
  entry['public_launch_unavailable']=inside and not report.get('events') and report.get('http_failure',{}).get('status')==404
  entries.append(entry)
 slots=[e for e in entries if e['in_current_scope']]
 result=dict(updated_at=now(),user_scope='Sólo slots; no procesar póker, blackjack u otros juegos de mesa/casuales de rondas indefinidas',included_game_types=['Slots'],products=len(entries),slot_products=len(slots),slot_public_demos=sum(e['execution_status']!='no_public_demo_link' for e in slots),slot_no_public_demo_link=sum(e['execution_status']=='no_public_demo_link' for e in slots),excluded_products=len(entries)-len(slots),slot_status_counts=dict(collections.Counter(e['execution_status'] for e in slots)),active_game=state.get('active_game'),minimum_seconds_between_game_launches=60,pending_slots=[e for e in slots if e['execution_status'] not in ('complete_declared_modes','no_public_demo_link')],games=entries)
 result['slots_with_execution_plan_fulfilled']=sum(e['execution_plan_fulfilled'] for e in slots);result['runtime_pending_slots']=[e['game_id'] for e in slots if e['execution_status']!='no_public_demo_link' and not e['execution_plan_fulfilled'] and not e['public_launch_unavailable']];result['financial_review_slots']=[e['game_id'] for e in slots if e.get('native_financial_checks_failed')];result['public_launch_unavailable_slots']=[e['game_id'] for e in slots if e['public_launch_unavailable']]
 result['historical_financial_findings_preserved']=[e['game_id'] for e in slots if e['historical_failed_checks_preserved']];result['historical_failed_checks_preserved']=sum(e['historical_failed_checks_preserved'] for e in slots)
 save(ROOT/'slot-scope.json',result);return result
if __name__=='__main__':
 result=build();print(json.dumps({k:v for k,v in result.items() if k not in ('games','pending_slots')},ensure_ascii=False))
