"""Read-only recovery gate; preserve the rejected out-of-sequence control."""
import json,hashlib,msvcrt
from campaign import ROOT,Campaign,save,clean
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 try:
  p=ROOT/'private/rounds/zeusriches/BUY_BONUS.json';c=json.loads(p.read_text());last=c['journal'][-1]
  if last['endpoint']!='_SkipInteractive' or last.get('response',{}).get('status',{}).get('code')!=409:raise ValueError('unexpected_case_state')
  jpath=ROOT/'private/recovery/zeus-read-only.json'
  if jpath.exists():raise ValueError('existing_recovery_read_no_retry')
  cfg=json.loads((ROOT/'private/sessions'/('own-'+c['session_fingerprint'])/'credentials.json').read_text());r,j=Campaign().request(cfg['host']+'/service/_Initialise',data={'sid':cfg['sid'],'slotcode':cfg['slotcode']},journal=jpath);x=clean(r.json());j['response']=x;save(jpath,j)
  previous=c['journal'][-2]['response'];restored=x.get('LastResult');print({'demo':x.get('Balance',{}).get('Demo'),'balance':x.get('Balance',{}).get('ScoreCents'),'last_result_present':isinstance(restored,dict),'last_mode':restored.get('Mode') if isinstance(restored,dict) else None,'last_next_mode':restored.get('NextMode') if isinstance(restored,dict) else None})
  if not isinstance(restored,dict) or x['Balance'].get('Demo') is not True or x['Balance']['ScoreCents']!=previous['Balance']['ScoreCents'] or any(restored.get(k)!=previous.get(k) for k in ['Mode','NextMode','roundWin']):raise ValueError('old_round_not_confirmed_no_financial_action')
  save(ROOT/'private/recovery/zeus-case-before-recovery.json',c)
  c.setdefault('rejected_native_controls',[]).append(c['journal'].pop());c.update(status='hold_do_not_repeat',error='unknown_continuation_freespins_alternative',recovery_read_reference=str(jpath),recovery_note='Rejected 409 control excluded from financial ledger only after own native read confirms same original balance and state; never resend it.');save(p,c);print('Existing round confirmed; first Roll may now be resumed without repeating purchase or rejected control')
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
