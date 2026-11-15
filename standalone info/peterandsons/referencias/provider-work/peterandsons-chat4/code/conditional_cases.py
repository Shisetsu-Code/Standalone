"""One new, labelled conditional case per Bloody Mary extra type; never replay."""
import json
import os
import time
from analyze_hars import ROOT,clean
from campaign import Client,atomic,API
from protocol import minimum_modes,extra_spin_request,take_round_request,audit_round

def run_case(action):
    if action not in ('extra_spin_fs','extra_spin_sfs'):raise ValueError('unreviewed_conditional_case')
    target=ROOT/'private/conditional-cases'/(action+'.json')
    if target.exists():
        if json.loads(target.read_text(encoding='utf8')).get('status')=='verified':return
        raise ValueError('prior_conditional_operation_needs_review_never_replay')
    if (ROOT/'private/holds/bloody-mary.json').exists():raise ValueError('game_held')
    game=next(g for g in json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf8')) if g['game_id']=='bloody-mary')
    while True:
        cadence=ROOT/'private/cadence.json'
        last=json.loads(cadence.read_text()).get('last_started_at',0) if cadence.exists() else 0
        wait=40-(time.time()-last)
        if wait<=0:break
        time.sleep(min(wait,5))
    atomic('private/cadence.json',{'last_started_at':time.time(),'game':'bloody-mary','case':action,'minimum_interval_seconds':40})
    client=Client(game)
    record={'game':'bloody-mary','conditional_action':action,'status':'initializing','session':client.folder.name,
            'source_har_sha256':'2cd70fa019c66b32b3168ddcb362108bbfff5eda07486f04c6c1a878d94dac9a',
            'purpose':'New parent entry solely prepares a distinct conditional case; never new coverage of its already verified parent mode.'}
    atomic(target.relative_to(ROOT),record)
    try:
        cfg=client.call('/cfg',{'server':API,'wallet':game['wallet'],'operator':'demo','gameCode':'bloody-mary','key':client.key,'language':'en'},'configuration')
        if cfg.get('adapter')!='standard' or cfg.get('loadGame') is not True:raise ValueError('unsupported_native_adapter')
        auth=client.call('/authenticate',{'wallet':game['wallet'],'operator':'demo','key':client.key,'provider':'peterandsons','game':'bloody-mary'},'authentication')
        if not auth.get('token') or auth.get('currencyDecimals')!=2:raise ValueError('authentication_or_currency_unreviewed')
        client.session.headers['Authorization']='Bearer '+auth['token']
        atomic((client.folder/'credentials.json').relative_to(ROOT),{'wallet':game['wallet'],'game':'bloody-mary','key':client.key,'token':auth['token'],'source':'new_anonymous_launch_never_HAR'})
        common={'game':'bloody-mary','provider':'peterandsons'}
        recovery=client.call('/game/recover',dict(common,complete=False),'recovery')
        if recovery.get('rounds')!=[]:raise ValueError('fresh_demo_has_pending_round')
        info=client.call('/game/info',common,'information')
        parent='buy_FS_3SC' if action=='extra_spin_fs' else 'buy_SFS_3SC'
        profile=next(m for m in minimum_modes(info) if m['id']==parent)
        record.update(status='preparation_started',balance_before=auth['balance'],preparation_mode=profile)
        atomic(target.relative_to(ROOT),record)
        request=dict(common,action=parent,complete=False,asyncWin=False,bet=profile['bet'])
        response=client.call('/game/play',request,'preparation-play')
        record.update(play_request=request,play_response=clean(response),continuations=[])
        atomic(target.relative_to(ROOT),record)
        if action not in response.get('wager',{}).get('next',[]):raise ValueError('conditional_offer_not_reached_preserve_preparation')
        buy=extra_spin_request('bloody-mary',response,info,action)
        continued=client.call('/game/play',buy,'conditional-buy')
        record['continuations'].append({'request':buy,'response':clean(continued),'source_binding':'56 captured native extras: pending_actions.cost /100 equals bet; same roundId; configuration and counter match.'})
        atomic(target.relative_to(ROOT),record);response=continued
        if 'take_round' in response.get('wager',{}).get('next',[]):
            take=take_round_request('bloody-mary',response)
            continued=client.call('/game/play',take,'take-round')
            record['continuations'].append({'request':take,'response':clean(continued)})
            atomic(target.relative_to(ROOT),record);response=continued
        if response.get('wager',{}).get('next') or response['wager']['data'][-1].get('closes_game_round') is not True:raise ValueError('unknown_pending_choice_no_settlement')
        complete_request=dict(common,roundId=response['roundId'],asyncWin=False)
        complete=client.call('/game/complete',complete_request,'complete')
        record.update(complete_request=complete_request,complete_response=clean(complete))
        atomic(target.relative_to(ROOT),record)
        audit=audit_round(auth['balance'],info,request,record['play_response'],complete_request,complete,record['continuations'])
        record.update(status='verified',audit=audit,conditional_cost=buy['bet'],preparation_cost=profile['bet'])
        atomic(target.relative_to(ROOT),record)
        print(json.dumps({'case':action,'status':'verified','conditional_cost':buy['bet'],'total_cost':audit['cost'],'payout':audit['payout'],'balance_after':audit['balance_after']}),flush=True)
    except Exception as error:
        record.update(status='needs_review',error=str(error));atomic(target.relative_to(ROOT),record);raise
    finally:client.session.close()

def main():
    lock=ROOT/'private/campaign.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,json.dumps({'pid':os.getpid(),'task':'two_conditional_cases','started_at':time.time()}).encode());os.close(fd)
    try:
        for action in ('extra_spin_fs','extra_spin_sfs'):run_case(action)
    finally:lock.unlink()

if __name__=='__main__':main()
