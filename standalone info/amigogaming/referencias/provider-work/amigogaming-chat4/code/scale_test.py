"""Scaling test: several stakes per game on public fictional demo. One process, shared campaign.lock, no retries."""
import json,re,time,msvcrt,sys
from decimal import Decimal as D
from urllib.parse import urljoin
from campaign import ROOT,HTTP,Socket,save,client_contract,native
from live_actions import continuation
OUT=ROOT/'private/scale'
PLAN=[ # game id, slug, mode, [(denom,mult)] in execution order
 (100,'blazing-crown-deluxe','NORMAL',[('0.010',1),('0.100',1),('1.000',1),('1.000',10)]),
 (105,'sizzling-coins','NORMAL',[('0.010',1),('0.100',1),('1.000',1),('1.000',2)]),
 (105,'sizzling-coins','BUY_FREE_GAME_2',[('0.100',1),('0.050',1),('0.020',1),('0.010',1)]),
 (110,'clover-hell','NORMAL',[('0.010',1),('0.100',1),('1.000',1),('0.500',5)]),
 (110,'clover-hell','BUY_FREE_GAMES',[('0.100',1),('0.050',1),('0.020',1),('0.010',1)]),
]
def session(h,g,label):
 q=h.request('https://amigogaming.com/es/games',path=f'private/scale/portal-{label}.json');h.s.headers['X-CSRF-TOKEN']=re.search(r'<meta name="csrf-token" content="([^"]+)',q.text).group(1)
 launch=h.launch(g,label);folder=ROOT/'private/sessions'/label
 q=h.request(launch['resourcesLocation'],path=f'private/sessions/{label}/game-document.json');lib=re.search(r'var gameLib\s*=\s*"([^"]+)"',q.text)
 q=h.request(urljoin(launch['resourcesLocation'],lib.group(1)),path=f'private/sessions/{label}/client-fetch.json');src=q.content.decode('utf-8');(folder/'client.js').write_text(src,encoding='utf-8');c=client_contract(src)
 sock=Socket(launch,folder);init=sock.send({'@type':'requests.InitRequest'},folder/'init.json')['response']
 assert init['round']==0 and init['mainFeature']=='SLOT' and native.terminal(init)
 return sock,init,src,c,folder,launch
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);sock=None;last=0
 res=ROOT/'private/scale/rows.json';rows=json.loads(res.read_text(encoding='utf-8')) if res.exists() else []
 try:
  cat={g['id']:g for g in json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8'))}
  for gid,slug,mode,stakes in PLAN:
   if (ROOT/'private/scale'/f'{gid}-{mode}.done').exists():continue
   g=cat[gid];label=f'scale-{gid}-{mode}'+('-r2' if (ROOT/'private/sessions'/f'scale-{gid}-{mode}').exists() else '')
   time.sleep(max(0,10-(time.monotonic()-last)));last=time.monotonic()
   sock,init,src,contract,folder,launch=session(HTTP(),g,label)
   host=re.sub(r'.*//([^/]+)/.*',r'\1',launch['endpoint']+'/') if 'endpoint' in launch else None
   print({'game':slug,'mode':mode,'session':'demo_public','ws_host':host,'balance':init['balance'],'maxBet':init['maxBet']},flush=True)
   if mode!='NORMAL' and not contract['buy_supported']:raise ValueError('buy_not_supported')
   price=D(1) if mode=='NORMAL' else D(str(next(b['price'] for b in init['buyIns'] if b['id']==mode.removeprefix('BUY_'))))
   state=init;lines=init['bets'][0]['value']
   for n,(den,mul) in enumerate(stakes):
    time.sleep(0.8)
    bet={'@type':'BetParams','bet':lines,'multiplier':mul,'denomination':den};base=D(den)*lines*mul;cost=base*price;before=D(state['balance']['amount'])
    row={'game':slug,'game_id':gid,'mode':mode,'denomination':den,'multiplier_level':mul,'lines':lines,'base_stake':str(base),'expected_gross':str(cost),'balance_before':str(before),'price_multiplier':str(price)}
    if cost>before or base>D(init['maxBet']):row.update(status='skipped_preflight',reason='cost>balance or base>maxBet');rows.append(row);continue
    journal=[];bound=dict(state,balance=state['balance']);cur=state;p=ROOT/'private/scale'/f'{gid}-{mode}-{n}.json'
    try:
     for k in range(300):
      if k==0:
       action={'@type':'features.slot.action.SpinAction','betParams':bet}
       if mode!='NORMAL':action['buyInId']=mode.removeprefix('BUY_')
      else:action=continuation(cur,init,src,bet)
      pk=sock.send({'@type':'requests.ActionRequest','action':action},folder/f'S{n}-{k}.json');journal.append(pk);cur=pk['response']
      if native.terminal(cur):break
      time.sleep(0.8)
     else:raise ValueError('continuation_limit')
     a=native.audit(dict(state),journal,price);last_r=journal[-1]['response']
     row.update(status='verified',round=a['round'],gross_bet=a['cost'],total_win=a['payout'],balance_after=a['balance_after'],requests=a['requests'],closed=True,win_credits=last_r['win'],ratio_win_over_base=str(D(a['payout'])/base),ratio_gross_over_base=str(D(a['cost'])/base),ledger_ok=True)
     state=cur
    except Exception as exc:
     row.update(status='hold_do_not_repeat',error=str(exc),requests_sent=len(journal)+1,closed=False);rows.append(row);save(res,rows);raise
    rows.append(row);save(res,rows);print(row,flush=True)
   (ROOT/'private/scale'/f'{gid}-{mode}.done').write_text('ok');sock.w.close();sock=None
 except Exception as exc:print({'stopped':str(exc)},flush=True)
 finally:
  save(res,rows)
  if sock:sock.w.close()
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
