"""Promote only independently verified fresh contexts; retain immutable failed history."""
import copy,hashlib,json
from run_demo_qa import ROOT,save,now
from revalidate_financial_slots import TARGETS
from checkpoint_guard import acquire,require_inactive
from audit_live import audit
def validate_fresh(report,old):
 gid=report['game']['game_id']
 if gid not in TARGETS or report['status']!='complete_declared_modes':raise ValueError('Only a fully closed authorized fresh context may be published')
 if report.get('bootstrap',{}).get('currency')!='FUN' or report['bootstrap'].get('server_id')!='demo':raise ValueError('Fresh native FUN identity missing')
 if not report.get('modes') or len(report['modes'])!=len(report['declared_modes']) or any(m['status']!='closed' for m in report['modes']):raise ValueError('Fresh mode plan incomplete')
 if {m['name'] for m in report['declared_modes']}!={m['name'] for m in old['declared_modes']}:raise ValueError('Fresh revalidation omitted a previous declared mode')
 if gid=='DigDigDigger' and set(report.get('finite_choices_verified',[]))!={'s','c','d','h','black','red'}:raise ValueError('Fresh finite slot choices not all verified')
 checked=audit(report)
 if checked.get('failed') or checked.get('audit_error') or any(c.get('ok') is False for c in report.get('checks',[])):raise ValueError('Fresh independent/native checks failed')
 return checked
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text());require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause queue before publication')
 prepared=[]
 for gid in TARGETS:
  path=ROOT/'live/fresh-financial-revalidation'/(gid+'.json');report=json.loads(path.read_text());archive=ROOT/report['historical_report_archive'];raw=archive.read_bytes();old=json.loads(raw)
  if hashlib.sha256(raw).hexdigest()!=report['historical_report_sha256'] or (ROOT/'live'/(gid+'.json')).read_bytes()!=raw:raise ValueError('Historical evidence changed; no overwrite')
  current=validate_fresh(report,old);historical=audit(old)
  report['revalidation']=dict(context_id='fresh-financial-revalidation/'+gid,verified_at=now(),current_native_checks_verified=True,current_independent_checks=current['passed'],historical_report_archive=report['historical_report_archive'],historical_report_sha256=report['historical_report_sha256'],historical_failed_checks=historical.get('failed',0),historical_status=old['status'],private_checkpoint='fresh-financial-revalidation/'+gid+'/session.json',policy='Current status describes a new independently verified FUN session. Archived native failures remain failures; their cause is not retroactively repaired.')
  prepared.append((gid,report))
 for gid,report in prepared:
  save(ROOT/'live'/(gid+'.json'),report);state['results'][gid]=dict(status=report['status'],modes_closed=len(report['modes']),report='live/'+gid+'.json',revalidated_at=now(),historical_failed_checks=report['revalidation']['historical_failed_checks'])
 state['updated_at']=now();save(ROOT/'run-state.json',state);print('Published four fresh fully verified contexts; all historical receipts/checks preserved')
