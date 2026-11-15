"""Close and independently reconcile native demo rounds, retaining every step."""
import argparse
from collections import Counter
import concurrent.futures
from decimal import Decimal
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path,unavailable_slugs
import threading
import time
from endorphina_client import Endorphina
from endorphina_choices import point
from endorphina_run import write_json
from provider_reports import render

ROOT=Path(__file__).resolve().parent
FOLDER=batch_path()
PRIVATE=private_path()
LOCK=threading.Lock()


def next_step(history,slug=None):
    if history['status']=='FINISHED':
        return None
    features=history['features']
    active=[f for f in features if f['status']=='IN_PROGRESS']
    if active:
        feature=active[-1]
        state=feature['current_state']
        if state.get('is_final') is True or state.get('isFinal') is True:
            return 'END_FEATURE',None
        if feature['feature_id'] in ('PICKME','WHEEL_WIN') and state.get('tries')==0:
            return 'END_FEATURE',None
        choice=point(feature,slug)
        if choice:
            return 'STEP_FEATURE',{'@type':choice['action_type'],choice['field']:choice['options'][0]}
        if feature['feature_id']=='SLOT':
            return 'STEP_FEATURE',{'@type':'logic.api.gamelogic.slot.'+('Drop_Action' if state.get('curr_reaction') else 'Slot_Action')}
        if feature['feature_id']=='FREE_GAME':
            if state.get('not_played_free_games')==0 and not state.get('is_drop'):
                return 'END_FEATURE',None
            return 'STEP_FEATURE',{'@type':'logic.api.gamelogic.freegames.'+('Free_Games_Drop_Action' if state.get('is_drop') else 'Free_Games_Action')}
        if feature['feature_id']=='RABBITS_WIN':
            if 'tries' in state and state['tries']<=0:
                return 'END_FEATURE',None
            return 'STEP_FEATURE',{'@type':'logic.api.gamelogic.rabbits.Rabbits_Action'}
        if feature['feature_id']=='WHEEL_WIN':
            return 'STEP_FEATURE',{'@type':'logic.api.gamelogic.wheel.Wheel_Action'}
        if feature['feature_id']=='COCKTAIL_WIN':
            if state['tries']<=0:return 'END_FEATURE',None
            return 'STEP_FEATURE',{'@type':'logic.api.gamelogic.cocktail_wins.Cocktail_Action'}
        raise ValueError('unhandled_active_feature:'+feature['feature_id']+':'+str(state.get('@type')))
    waiting=[f for f in features if f['status']=='NOT_STARTED' and f['feature_id']!='GAMBLE']
    if waiting:
        return 'START_FEATURE',waiting[0]['feature_id']
    # Native collect action closes a round rather than entering optional risk.
    return 'END_GAME',None


def close_round(client,row,stop_at_collect=False):
    for _ in range(1000):
        command=next_step(client.history,row.get('slug'))
        if command is None:
            break
        method,payload=command
        if stop_at_collect and method=='END_GAME' and sum(Decimal(str(f['current_win'])) for f in client.history['features'])>0:
            return False
        if method=='STEP_FEATURE':
            active=[f for f in client.history['features'] if f['status']=='IN_PROGRESS']
            decision=point(active[-1],row.get('slug')) if active else None
            if decision:
                target=row.get('choice_target',{})
                selected=target.get('option') if target.get('node')==decision['node'] and target.get('option') in decision['options'] else decision['options'][0]
                payload[decision['field']]=selected
                row.setdefault('choices',[]).append(dict(decision,selected=selected))
        response=client.call(method,payload)
        if method=='START_FEATURE':
            client.history=client.call('GET_LAST_GAME')
        elif method=='STEP_FEATURE':
            client.history=response['historyItem']
        elif method=='END_FEATURE':
            client.history=response
        elif method=='END_GAME':
            client.history=response['data']
    else:
        raise ValueError('continuation_limit')
    after=client.call('GET_BALANCE')
    parameters=client.history['betting_param']
    win=sum(Decimal(str(f['current_win'])) for f in client.history['features'])*Decimal(parameters['denom'])
    expected=Decimal(row['balance_before'])-Decimal(row['cost'])+win
    row.update(status='completed',final_win=str(win),balance_after=after['balance'],
        wallet_check='match' if expected==Decimal(after['balance']) else 'mismatch',
        expected_balance=str(expected),last_history=client.history)
    if row['wallet_check']!='match':
        row['status']='needs_review'
        row['reason']='wallet_mismatch'
    else:
        row.pop('reason',None)
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--symbols',nargs='*')
    parser.add_argument('--phase',choices=['normal','purchases'],default='normal')
    parser.add_argument('--fresh-incomplete',action='store_true',help='Archive incomplete attempts and start a new fictional-money demo case')
    args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    (FOLDER/'traces').mkdir(exist_ok=True)
    PRIVATE.mkdir(parents=True,exist_ok=True)
    catalog=catalog_slice()
    specs=[]
    if args.phase=='normal':
        specs=[dict(g,kind='normal',case=g['slug']+'--normal') for g in catalog]
    else:
        inventory=json.loads((FOLDER/'inventory.json').read_text(encoding='utf8'))
        for g in catalog:
            if g['slug'] in unavailable_slugs():continue
            meta=next(r for r in inventory if r['slug']==g['slug'])
            if meta['status']!='discovered':raise ValueError('inventory_incomplete')
            specs.extend(dict(g,kind='purchase',case=g['slug']+'--buy-'+str(i),buy_id=b['id'],price=b['price']) for i,b in enumerate(meta.get('buy_ins') or []))
            if meta.get('extra_bet'):
                raise ValueError('extra_bet_schema_requires_review')
    specs=[g for g in specs if not args.symbols or g['slug'] in args.symbols][:args.limit]
    path=FOLDER/('rounds.json' if args.phase=='normal' else 'purchases.json')
    rows={r['case']:r for r in json.loads(path.read_text(encoding='utf8'))} if path.exists() else {}

    def run(spec):
        existing=rows.get(spec['case'],{})
        if existing.get('status')=='completed' and existing.get('wallet_check')=='match':return
        client=None
        row=dict(spec,status='running')
        trace_path=FOLDER/'traces'/(spec['case']+'.json')
        resume_path=PRIVATE/(spec['case']+'.json')
        previous=[]
        try:
            if existing and args.fresh_incomplete:
                archive=FOLDER/'attempts'/spec['case']
                archive.mkdir(parents=True,exist_ok=True)
                if trace_path.exists():
                    write_json(archive/(str(time.time_ns())+'.json'),json.loads(trace_path.read_text(encoding='utf8')))
                existing={}
            if existing and resume_path.exists() and existing.get('stake_sent'):
                row=dict(existing,status='running')
                if row.get('reason'):
                    row.setdefault('diagnostics',[]).append(row.pop('reason'))
                previous=json.loads(trace_path.read_text(encoding='utf8'))['trace']
                client=Endorphina.resume(json.loads(resume_path.read_text(encoding='utf8')))
            else:
                client=Endorphina(spec['play_url'])
                row.update(game=client.game,currency=client.currency,balance_before=client.balance['balance'])
                parameters=dict(client.parameters)
                if spec['kind']=='purchase':
                    published=next(b for b in client.paytable.get('buyIns',[]) if b['id']==spec['buy_id'])
                    if published['price']!=spec['price']:raise ValueError('buy_price_changed')
                    parameters['buyInId']=spec['buy_id']
                cost=(Decimal(str(parameters['bet_per_line']))*parameters['num_of_lines']+Decimal(str(parameters['extra_bet'])))*Decimal(parameters['denom'])*Decimal(str(spec.get('price',1)))
                row.update(parameters=parameters,cost=str(cost))
                if Decimal(row['balance_before'])<cost:
                    raise ValueError('public_demo_balance_insufficient')
                write_json(resume_path,client.connection)
                row['stake_sent']=True
                write_json(trace_path,{'case':spec['case'],'slug':spec['slug'],'trace':client.trace,'summary':row})
                with LOCK:
                    rows[spec['case']]=dict(row)
                    write_json(path,list(rows.values()))
                response=client.call('START_GAME',parameters)
                client.history=response['data']
                row['first_history']=client.history
            close_round(client,row)
        except Exception as e:
            row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
        finally:
            trace=previous+(client.trace if client else [])
            if client:
                row['last_history']=client.history
                client.close()
            write_json(trace_path,{'case':spec['case'],'slug':spec['slug'],'trace':trace,'summary':row})
            with LOCK:
                rows[spec['case']]=row
                write_json(path,list(rows.values()))
                render()
                print(json.dumps({'case':spec['case'],'status':row['status'],'wallet':row.get('wallet_check'),'reason':row.get('reason'),'records':len(rows)}),flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run,specs))
    print(json.dumps({'finished':True,'phase':args.phase,'states':dict(Counter(r['status'] for r in rows.values()))}),flush=True)


if __name__=='__main__':
    main()
