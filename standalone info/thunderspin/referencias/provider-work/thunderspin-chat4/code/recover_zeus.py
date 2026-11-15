"""One certified interactive continuation of an existing own round. No retry."""
import json,pathlib,hashlib,msvcrt
from campaign import ROOT,save,Campaign,clean
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 try:
  p=ROOT/'private/rounds/zeusriches/BUY_BONUS.json';c=json.loads(p.read_text());last=c['journal'][-1]
  if c['status']!='hold_do_not_repeat' or c.get('wheel_recovery_started') or any(x.get('http_status')!=200 for x in c['journal']) or last['response']['NextMode']!='freespins_alternative':raise ValueError('not_safe_to_continue')
  cfg=json.loads((ROOT/'private/sessions'/('own-'+c['session_fingerprint'])/'credentials.json').read_text());client=pathlib.Path(cfg['source_client']).read_text(encoding='utf-8')
  exact='wheelRoll(){this.send({name:"SkipInteractive",body:{sid:this.sid}})}'
  if exact not in client:raise ValueError('native_wheel_contract_missing')
  save(ROOT/'private/references/zeus-riches-megaways/wheel-contract.json',{'client_sha256':hashlib.sha256(client.encode()).hexdigest(),'source':cfg['source_client'],'exact_contract':exact,'original_case':str(p)})
  c['wheel_recovery_started']=True;packet={'endpoint':'_SkipInteractive','game':'zeusriches','session_fingerprint':c['session_fingerprint'],'request':{'sid':'[REDACTED]'},'status':'sending','http_status':None};c['journal'].append(packet);save(p,c)
  http=Campaign();r,_=http.request(cfg['host']+'/service/_SkipInteractive',data={'sid':cfg['sid']},journal=ROOT/'private/journals/zeusriches/wheel-first.json');x=clean(r.json());packet.update(http_status=200,status='received',response=x);c['status']='hold_do_not_repeat';c['error']='interactive_response_requires_audit';save(p,c)
  print({'http_status':200,'response_keys':list(x),'Mode':x.get('Mode'),'NextMode':x.get('NextMode')})
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
