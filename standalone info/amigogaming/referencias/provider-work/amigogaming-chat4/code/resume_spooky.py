"""Resume only the receipt-proven acknowledged Match3, never its original spin/pick."""
import json,msvcrt
from campaign import ROOT,Socket,run_case,checkpoint,save,native
from live_actions import continuation
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 folder=ROOT/'private/sessions/game-199-1';p=ROOT/'private/rounds/199/NORMAL.json';c=json.loads(p.read_text());original=json.loads((folder/'init.json').read_text())['response'];launch=json.loads((folder/'launch.private.json').read_text());source=(folder/'client.js').read_text(encoding='utf-8');sock=None
 try:
  assert c['status']=='hold_do_not_repeat' and c['journal'][-1]['status']=='sending' and len(c['journal'])==2
  witness=json.loads((folder/'recovery-init-once.json').read_text())['response'];assert witness['round']==c['journal'][0]['response']['round'] and witness['states']['MATCH3']['choices'][0]!=-1
  c['journal'][-1].update(recovery_snapshot=witness,recovery_reference=str((folder/'recovery-init-once.json').relative_to(ROOT)));save(p,c)
  sock=Socket(launch,folder);read=sock.send({'@type':'requests.InitRequest'},folder/'resume-init.json')['response'];assert read['round']==witness['round'] and read['balance']==witness['balance'] and read['states']['MATCH3']['choices']==witness['states']['MATCH3']['choices'];state=read;bet=native.minimum_bet(original)
  for n in range(30):
   action=continuation(state,original,source,bet);path=folder/('NORMAL-resume-'+str(n)+'.json');c['journal'].append({'status':'sending','request':{'@type':'requests.ActionRequest','id':sock.id,'action':action},'packet_reference':str(path.relative_to(ROOT))});save(p,c);packet=sock.send({'@type':'requests.ActionRequest','action':action},path);c['journal'][-1]=dict(packet,packet_reference=str(path.relative_to(ROOT)));save(p,c);state=packet['response']
   if native.terminal(state):
    c.update(status='verified',audit=native.audit(original,c['journal'],'1'),resolved_adapter_history=c.pop('error',None));save(p,c);print({'normal':'verified','audit':c['audit']},flush=True);break
  assert c['status']=='verified'
  g=next(x for x in json.loads((ROOT/'results/catalogue.json').read_text()) if x['id']==199);quote=next(b['price'] for b in original['buyIns'] if b['id']=='PICKME');run_case(sock,g,original,source,'BUY_PICKME',quote,folder,state);checkpoint(status='spooky_recovered_and_buy_verified')
 except Exception as exc:checkpoint(status='stopped_for_review',error=str(exc));print({'error':str(exc)},flush=True)
 finally:
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
