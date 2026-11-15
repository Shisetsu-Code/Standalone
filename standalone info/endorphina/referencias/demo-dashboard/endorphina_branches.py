"""Cover declared internal menu indices in completed demo purchase rounds."""
import argparse
import concurrent.futures
from decimal import Decimal
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path
import threading
from endorphina_client import Endorphina
from endorphina_rounds import close_round
from endorphina_run import write_json
from provider_reports import render

ROOT=Path(__file__).resolve().parent
FOLDER=batch_path()
LOCK=threading.Lock()


def absorb(matrix,row):
    good=row.get('status')=='completed' and row.get('wallet_check')=='match'
    for decision in row.get('choices',[]):
        for option in decision['options']:
            key=decision['node']+':'+str(option)
            goal=matrix.setdefault(key,{'node':decision['node'],'family':decision['family'],'option':option,'verified':False,'evidence':[]})
            if good and option==decision['selected']:
                goal['verified']=True
                if row['case'] not in goal['evidence']:goal['evidence'].append(row['case'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--attempts',type=int,default=15)
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args()
    base=json.loads((FOLDER/'purchases.json').read_text(encoding='utf8'))
    if args.partial:
        base=[r for r in base if r['status']=='completed' and r.get('wallet_check')=='match']
    elif any(r['status']!='completed' or r.get('wallet_check')!='match' for r in base):raise ValueError('purchases_must_be_complete')
    path=FOLDER/'choices.json'
    rows={r['case']:r for r in json.loads(path.read_text(encoding='utf8'))} if path.exists() else {}
    matrices={r['case']:{} for r in base}
    for r in base+list(rows.values()):absorb(matrices[r.get('root_case',r['case'])],r)

    def save():
        write_json(path,list(rows.values()))
        goals=[g for m in matrices.values() for g in m.values()]
        write_json(FOLDER/'choices-matrix.json',{'summary':{'options':len(goals),'verified':sum(g['verified'] for g in goals)},'purchases':matrices})
        render()

    def run(original):
        matrix=matrices[original['case']]
        if all(g['verified'] for g in matrix.values()):return
        client=None
        attempts={}
        prefix=original['case']+'--branch-'
        number=max([int(k[len(prefix):]) for k in rows if k.startswith(prefix)]+[0])
        try:
            client=Endorphina(original['play_url'])
            for _ in range(250):
                pending=[(k,g) for k,g in matrix.items() if not g['verified'] and attempts.get(k,0)<args.attempts]
                if not pending:break
                key,goal=pending[0]
                attempts[key]=attempts.get(key,0)+1
                number+=1
                start=len(client.trace)
                row={k:original[k] for k in ('slug','name','play_url','buy_id','price')}
                row.update(case=prefix+str(number),root_case=original['case'],kind='purchase_choice',status='running',
                    choice_target={'node':goal['node'],'option':goal['option']})
                try:
                    row['balance_before']=client.call('GET_BALANCE')['balance']
                    params=dict(client.parameters,buyInId=original['buy_id'])
                    row['parameters']=params
                    row['cost']=str((Decimal(str(params['bet_per_line']))*params['num_of_lines']+Decimal(str(params['extra_bet'])))*Decimal(params['denom'])*Decimal(str(original['price'])))
                    client.history=client.call('START_GAME',params)['data']
                    close_round(client,row)
                except Exception as e:
                    row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
                write_json(FOLDER/'traces'/(row['case']+'.json'),{'case':row['case'],'slug':row['slug'],'trace':client.trace[start:],'summary':row})
                with LOCK:
                    rows[row['case']]=row
                    absorb(matrix,row)
                    save()
                print(json.dumps({'case':row['case'],'status':row['status'],'wallet':row.get('wallet_check'),'verified':sum(g['verified'] for g in matrix.values()),'options':len(matrix),'reason':row.get('reason')}),flush=True)
                if row['status']!='completed':break
        except Exception as e:print(json.dumps({'root':original['case'],'error':type(e).__name__}),flush=True)
        finally:
            if client:client.close()

    with LOCK:save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,base))
    with LOCK:save()
    print(json.dumps({'finished':True,'options':sum(len(m) for m in matrices.values()),'verified':sum(g['verified'] for m in matrices.values() for g in m.values())}),flush=True)


if __name__=='__main__':main()
