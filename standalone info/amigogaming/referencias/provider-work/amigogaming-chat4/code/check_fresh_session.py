"""User-requested single ordinary public launch; no wagering or access bypass."""
import json,re,msvcrt,datetime
from campaign import ROOT,HTTP,Socket,save,client_contract,native
from urllib.parse import urljoin
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);sock=None
 block=ROOT/'private/remote-block.json';archive=ROOT/'private/recovery/403-before-user-requested-fresh-session.json';summary=ROOT/'private/recovery/fresh-session-check.json'
 try:
  assert block.exists() and not archive.exists() and not summary.exists()
  assert not list((ROOT/'private/rounds/107').glob('*.json')),'never_replace_a_financial_session'
  archive.parent.mkdir(exist_ok=True);block.replace(archive)
  save(summary,{'status':'checking_one_normal_public_launch','authorization':'user explicitly requested continuing remaining games and handling403','previous_block':str(archive.relative_to(ROOT)),'no_wagers':True})
  h=HTTP();q=h.request('https://amigogaming.com/es/games',path='private/recovery/fresh-session-portal.json');assert q.status_code==200
  h.s.headers['X-CSRF-TOKEN']=re.search(r'<meta name="csrf-token" content="([^"]+)',q.text).group(1)
  g=next(g for g in json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8')) if g['id']==107);label='game-107-fresh-after-user-request';launch=h.launch(g,label);folder=ROOT/'private/sessions'/label
  q=h.request(launch['resourcesLocation'],path=f'private/sessions/{label}/game-document.json');(folder/'game.html').write_bytes(q.content);lib=re.search(r'var gameLib\s*=\s*"([^"]+)"',q.text);assert lib
  q=h.request(urljoin(launch['resourcesLocation'],lib.group(1)),path=f'private/sessions/{label}/client-fetch.json');source=q.content.decode('utf-8');(folder/'client.js').write_text(source,encoding='utf-8');contract=client_contract(source);save(folder/'client-contract.json',contract)
  sock=Socket(launch,folder);init=sock.send({'@type':'requests.InitRequest'},folder/'init-fresh-check.json')['response'];assert init['round']==0 and init['mainFeature']=='SLOT' and native.terminal(init) and native.D(init['balance']['amount'])>0
  save(summary,{'status':'fresh_public_session_initialized_successfully','previous_block':str(archive.relative_to(ROOT)),'portal_http':200,'websocket_handshake':101,'native_response':init['@type'],'round':0,'balance':init['balance'],'session_folder':str(folder.relative_to(ROOT)),'no_wagers':True,'interpretation':'old_session403_did_not_recur_with_ordinary_new_public_session; exact_old_failure_cause_not_proven'})
  print({'status':'fresh_demo_initialized','round':0,'balance':init['balance'],'no_wagers':True},flush=True)
 except Exception as exc:
  if not block.exists():save(block,{'phase':'user_requested_fresh_session_check','status':'stopped','error':type(exc).__name__,'previous_block':str(archive.relative_to(ROOT))})
  save(summary,{'status':'stopped_no_new_entries','error':str(exc),'no_wagers':True});print({'status':'stopped','error_type':type(exc).__name__},flush=True)
 finally:
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
