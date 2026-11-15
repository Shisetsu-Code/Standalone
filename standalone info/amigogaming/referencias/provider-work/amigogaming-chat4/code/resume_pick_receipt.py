"""One reconnect with own credentials; continue only a proven choice receipt."""
import json,msvcrt
from campaign import ROOT,Socket,save,checkpoint,native
from live_actions import continuation
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);sock=None
 folder=ROOT/'private/sessions/game-199-1';p=ROOT/'private/rounds/199/BUY_PICKME.json';c=json.loads(p.read_text());init=json.loads((folder/'init.json').read_text())['response'];source=(folder/'client.js').read_text(encoding='utf-8')
 try:
  assert c['status']=='hold_do_not_repeat' and c['journal'][-1]['status']=='sending'
  pending=c['journal'][-1];q=pending['request']['action'];assert q['@type']=='features.pickme.action.PickMeAction' and q['choice']==0
  sock=Socket(json.loads((folder/'launch.private.json').read_text()),folder);wp=folder/'buy-recovery-init-once.json';read=sock.send({'@type':'requests.InitRequest'},wp)['response'];prev=c['journal'][-2]['response'];cur=native.resolved(prev)
  assert read['round']==prev['round'] and read['balance']==prev['balance'] and read['states'][cur]['choices'][0]!=-1
  pending.update(recovery_snapshot=read,recovery_reference=str(wp.relative_to(ROOT)));save(p,c);state=read;bet=native.minimum_bet(init)
  for n in range(300):
   if native.terminal(state):break
   action=continuation(state,init,source,bet);path=folder/('BUY_PICKME-recovered-'+str(n)+'.json');c['journal'].append({'status':'sending','request':{'@type':'requests.ActionRequest','id':sock.id,'action':action},'packet_reference':str(path.relative_to(ROOT))});save(p,c);packet=sock.send({'@type':'requests.ActionRequest','action':action},path);c['journal'][-1]=dict(packet,packet_reference=str(path.relative_to(ROOT)));save(p,c);state=packet['response']
  bound=dict(init,balance=dict(init['balance'],amount=c['balance_before']));c.update(audit=native.audit(bound,c['journal'],c['price_multiplier']),status='verified',resolved_adapter_history=c.pop('error',None));save(p,c);checkpoint(status='spooky_all_cases_verified');print(c['audit'],flush=True)
 except Exception as exc:checkpoint(status='stopped_for_review',error=str(exc));print({'error':str(exc)},flush=True)
 finally:
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
