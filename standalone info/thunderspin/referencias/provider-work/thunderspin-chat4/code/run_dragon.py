"""Two native demo cases, serial and journalled; no retries or HAR identities."""
import json,pathlib,hashlib,datetime,time,msvcrt,os
import requests
from native import audit_packets
ROOT=pathlib.Path(__file__).resolve().parent.parent
FP='6f6d83ccbcd2a7e1'
def save(p,x):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2),encoding='utf-8');os.replace(t,p)
def main():
    lock=open(ROOT/'private/campaign.lock','a+b');lock.seek(0)
    if not lock.read(1):lock.write(b'0');lock.flush()
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        folder=ROOT/'private/sessions'/('own-'+FP);cfg=json.loads((folder/'credentials.json').read_text());init=json.loads((folder/'init-journal.json').read_text());enter=init['response']
        if init['http_status']!=200 or enter['Balance']['Demo'] is not True or enter['GameCode']!='dragonhuntmegaways':raise ValueError('native_demo_init_not_verified')
        if min(enter['Balance']['CoinValue'])!=1 or min(enter['Balance']['BetLevel'])!=1 or enter['DefaultBet']!=20:raise ValueError('minimum_changed')
        s=requests.Session();s.trust_env=False;bank=enter['Balance']['ScoreCents'];lines=enter['Balance']['CurrentLinesCount']
        cases=ROOT/'private/rounds/dragonhuntmegaways';cases.mkdir(parents=True,exist_ok=True)
        for mode,action,expected in [('NORMAL','_Roll',20),('BUY_BONUS','_BuyBonus',1200)]:
            p=cases/(mode+'.json')
            if p.exists():
                c=json.loads(p.read_text())
                if c.get('status')!='verified':raise ValueError('existing_uncertain_case_no_retry')
                bank=c['audit']['balance_after_cents'];lines=c['journal'][-1]['response']['LinesCount'];continue
            if mode=='BUY_BONUS':
                price=enter['Features']['BuyBonus']['Costs']['costs']['20']
                if price['allowed'] is not True or price['buyValue']!=expected:raise ValueError('native_buy_price_changed')
                lines=0 # native requestBuyBonus uses data.lines.length, empty for ways
            c={'game':'dragonhuntmegaways','mode':mode,'status':'started','balance_before_cents':bank,'expected_cost_cents':expected,'session_fingerprint':FP,'journal':[],'source_init_reference':str(folder/'init-journal.json')};save(p,c)
            current_init=dict(init);current_init['response']=dict(enter,Balance=dict(enter['Balance'],ScoreCents=bank))
            expected_mode='root'
            for step in range(300):
                q={'denomination':1,'betlevel':1,'lines':lines,'data':0};packet={'endpoint':action,'session_fingerprint':FP,'game':'dragonhuntmegaways','request':dict(q,sid='[REDACTED]'),'http_status':None,'status':'sending','sent_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};c['journal'].append(packet);save(p,c)
                try:r=s.post(cfg['host']+'/service/'+action,data=dict(q,sid=cfg['sid']),timeout=30)
                except Exception:c['status']='hold_do_not_repeat';save(p,c);raise
                packet['http_status']=r.status_code;packet['response_sha256']=hashlib.sha256(r.content).hexdigest();save(p,c)
                if r.status_code in [403,429,503]:save(ROOT/'private/remote-block.json',{'http_status':r.status_code,'case_file':str(p),'step':step})
                if r.status_code!=200:c['status']='hold_do_not_repeat';save(p,c);raise ValueError('unconfirmed_http_'+str(r.status_code))
                x=r.json();x.pop('SessionID',None);packet['response']=x;packet['status']='received';save(p,c)
                if x.get('ErrorCode') or x.get('Error') or x['Mode']!=expected_mode:raise ValueError('native_state_mismatch')
                if step==0 and x['Balance']['TotalBetCents']!=expected:raise ValueError('native_cost_mismatch')
                a=audit_packets([current_init]+c['journal'])
                if a['closed_rounds']:
                    c['audit']=a['closed_rounds'][0];c['status']='verified';save(p,c);bank=c['audit']['balance_after_cents'];lines=x['LinesCount'];print({'mode':mode,'audit':c['audit']},flush=True);break
                expected_mode=x['NextMode']
                if expected_mode not in ['rootCascade','freespins','fsCascade','fsRespin'] or x.get('waitForAcceptWin') is not False:
                    c['status']='hold_do_not_repeat';c['error']='unverified_native_continuation_'+expected_mode;save(p,c);raise ValueError(c['error'])
                action='_Roll';lines=x['LinesCount']
            else:raise ValueError('continuation_bound_reached')
    finally:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
