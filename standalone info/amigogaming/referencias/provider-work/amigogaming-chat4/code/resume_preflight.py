"""Resume an initialized own demo only before any financial case exists."""
import json,sys,msvcrt
from campaign import ROOT,Socket,run_case,client_contract,save,checkpoint,native
def main(game_id):
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);sock=None
 try:
  assert not list((ROOT/'private/rounds'/str(game_id)).glob('*.json')),'financial_case_exists_no_preflight_resume'
  g=next(g for g in json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8')) if g['id']==game_id);folder=ROOT/'private/sessions'/('game-'+str(game_id)+'-1');source=(folder/'client.js').read_text(encoding='utf-8');contract=client_contract(source);save(folder/'client-contract.json',contract);sock=Socket(json.loads((folder/'launch.private.json').read_text(encoding='utf-8')),folder);ref=folder/'preflight-resume-init.json';init=sock.send({'@type':'requests.InitRequest'},ref)['response'];assert init['@type']=='responses.InitResponse' and init['round']==0 and native.terminal(init)
  modes={'NORMAL':1}
  for b in init.get('buyIns') or []:modes['BUY_'+b['id']]=b['price']
  save(ROOT/'private/plans'/(str(game_id)+'.json'),{'game_id':game_id,'slug':g['slug'],'modes':list(modes),'buyIns':init.get('buyIns',[]),'feature_types':{k:v.get('@type') for k,v in init['features'].items()},'init_reference':str(ref.relative_to(ROOT)),'client':contract});current=init
  for mode,price in modes.items():current=run_case(sock,g,init,source,mode,price,folder,current,case_init_reference=ref)
  checkpoint(status='preflight_resumed_game_verified',game_id=game_id)
 except Exception as exc:checkpoint(status='stopped_for_review',error=str(exc));print({'error':str(exc)},flush=True)
 finally:
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main(int(sys.argv[1]))
