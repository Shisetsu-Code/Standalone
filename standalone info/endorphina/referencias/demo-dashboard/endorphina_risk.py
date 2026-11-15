"""Exercise all four published Beat The Dealer choices using fictional funds.

Native source: Ic.NUM_OF_PLAYER_CARDS=4; BTD getFeatureAction sets player_choice
and bet=creditsWon. Every qualifying/warmup paid round has its own trace.
"""
import argparse
from collections import Counter
import concurrent.futures
from decimal import Decimal
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path
import threading
import time
from endorphina_client import Endorphina
from endorphina_rounds import close_round
from endorphina_run import write_json
from provider_reports import render
from endorphina_risk_contract import options as risk_options

ROOT=Path(__file__).resolve().parent
FOLDER=batch_path()
LOCK=threading.Lock()


def compact(row):
    # Full histories remain in the per-round trace, not in the growing index.
    return {k:v for k,v in row.items() if k not in ('first_history','last_history','risk_initial')}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--symbols',nargs='*')
    parser.add_argument('--qualifying-spins',type=int,default=60)
    args=parser.parse_args()
    config=json.loads((FOLDER/'features.json').read_text(encoding='utf8'))
    catalog=json.loads((FOLDER/'catalog.json').read_text(encoding='utf8'))
    path=FOLDER/'risk.json'
    rows={r['case']:compact(r) for r in json.loads(path.read_text(encoding='utf8'))} if path.exists() else {}
    contracts={r['slug']:risk_options(r.get('features',[])) for r in config}
    eligible=[g for g in catalog if contracts.get(g['slug'])]
    if args.symbols:eligible=[g for g in eligible if g['slug'] in args.symbols]

    def save(row,client,start):
        write_json(FOLDER/'traces'/(row['case']+'.json'),{'case':row['case'],'slug':row['slug'],'trace':client.trace[start:],'summary':row})
        with LOCK:
            rows[row['case']]=compact(row)
            write_json(path,list(rows.values()))
            render()
        print(json.dumps({'case':row['case'],'status':row['status'],'wallet':row.get('wallet_check'),'reason':row.get('reason')}),flush=True)

    def run(game):
        needed=[i for i in range(len(contracts[game['slug']])) if rows.get(game['slug']+'--risk-'+str(i),{}).get('status')!='completed']
        if not needed:return
        client=None
        try:
            cached=private_path()/(game['slug']+'--normal.json')
            if cached.exists():
                try:
                    client=Endorphina.resume(json.loads(cached.read_text(encoding='utf8')))
                    if client.history['status']!='FINISHED':
                        client.close()
                        client=None
                except Exception:
                    client=None
            if client is None:
                client=Endorphina(game['play_url'])
            number=max([int(r['case'].rsplit('-',1)[1]) for r in rows.values() if r['slug']==game['slug'] and r.get('kind')=='risk_warmup']+[0])
            for option in needed:
                case=game['slug']+'--risk-'+str(option)
                previous=rows.get(case)
                if previous and previous.get('status')!='completed':
                    original=FOLDER/'traces'/(case+'.json')
                    if original.exists():
                        archive=FOLDER/'attempts'/case
                        archive.mkdir(parents=True,exist_ok=True)
                        write_json(archive/(str(time.time_ns())+'.json'),json.loads(original.read_text(encoding='utf8')))
                for attempt in range(args.qualifying_spins):
                    start=len(client.trace)
                    before=client.call('GET_BALANCE')['balance']
                    params=client.parameters
                    cost=(Decimal(str(params['bet_per_line']))*params['num_of_lines']+Decimal(str(params['extra_bet'])))*Decimal(params['denom'])
                    row={**game,'kind':'risk','option':option,'case':game['slug']+'--risk-'+str(option),
                        'balance_before':before,'cost':str(cost),'parameters':dict(params),'status':'running','risk_control':contracts[game['slug']][option]}
                    response=client.call('START_GAME',params)
                    client.history=response['data']
                    row['first_history']=client.history
                    done=close_round(client,row,stop_at_collect=True)
                    if done:
                        number+=1
                        row.update(kind='risk_warmup',case=game['slug']+'--risk-warmup-'+str(number))
                        save(row,client,start)
                        continue
                    feature=client.call('START_FEATURE','GAMBLE')
                    row['risk_initial']=feature
                    state=feature['current_state']
                    if feature['feature_id']!='GAMBLE' or 'curr_win' not in state:
                        raise ValueError('unrecognized_risk_contract')
                    for _ in range(20):
                        control=contracts[game['slug']][option]
                        action={'@type':'logic.api.gamelogic.gamble.'+control['type'],control['field']:control['value'],'bet':state['curr_win']}
                        result=client.call('STEP_FEATURE',action)
                        client.history=result['historyItem']
                        state=result['state']['current_state']
                        if not state.get('must_play'):break
                    else:raise ValueError('risk_continuation_limit')
                    client.history=client.call('END_FEATURE')
                    close_round(client,row)
                    save(row,client,start)
                    if row['status']!='completed':return
                    break
                else:
                    row={'slug':game['slug'],'case':game['slug']+'--risk-'+str(option),'kind':'risk','option':option,
                        'status':'needs_review','reason':'no_qualifying_win_in_'+str(args.qualifying_spins)+'_closed_rounds'}
                    save(row,client,len(client.trace))
                    return
        except Exception as e:
            if client:
                row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__,last_history=client.history)
                save(row,client,start)
        finally:
            if client:client.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,eligible))
    print(json.dumps({'finished':True,'games':len(eligible),'risk_cases':sum(r.get('kind')=='risk' for r in rows.values()),'states':dict(Counter(r['status'] for r in rows.values()))}),flush=True)


if __name__=='__main__':main()
