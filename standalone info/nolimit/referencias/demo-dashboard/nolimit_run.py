"""Bounded native QA of fresh official Nolimit City demo sessions."""
import argparse
from collections import Counter
from copy import deepcopy
import concurrent.futures
from decimal import Decimal,ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from endorphina_run import write_json
from nolimit_client import Nolimit
from nolimit_protocol import controls,choice_point,continuation,native_win,check_wallet,redact

ROOT=Path(__file__).resolve().parent/'nolimit'
LOCK=threading.Lock()


def read(path,default):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default


def scope(batch):
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*',batch):raise ValueError('invalid_batch')
    start,end=map(int,batch.split('-'))
    if end<start or end-start>=100:raise ValueError('invalid_batch_range')
    games=read(ROOT/'catalog.json',[])[start-1:end]
    if len(games)!=end-start+1:raise ValueError('missing_catalog_scope')
    return ROOT/'batches'/batch,games


def cost_for(bet,control):
    if control is None:return Decimal(bet)
    side=Decimal(control.get('side_multiplier','0'));base=Decimal(control['multiplier'])-side
    return (Decimal(bet)*base).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)+(Decimal(bet)*side).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def finish(client,spec,checkpoint,target=None):
    control=None
    if spec.get('control_id'):
        control=next((c for c in controls(client.init) if c['control_id']==spec['control_id']),None)
        if control is None:raise ValueError('published_control_removed')
    bet=client.minimum_bet(control);cost=cost_for(bet,control)
    row=dict(spec,status='running',balance_before=client.balance,bet=bet,currency='EUR',version=client.version,cost=str(cost),choices=[],extra_spin_costs='0')
    if control:row['published_control']=control
    if cost>Decimal(client.balance):raise ValueError('insufficient_demo_funds_for_published_control')
    checkpoint(row);row['stake_sent']=True;checkpoint(row)
    content={'type':'normalBet','bet':bet}
    interaction={}
    if isinstance(client.init.get('allowedFeatureBets'),dict):interaction['gameMode']=client.init['game']['playedCapMode']
    if control and control.get('game_mode'):interaction['gameMode']=control['game_mode']
    if control and control.get('feature_name'):
        content.update(type='featureBet',featureName=control['feature_name']);interaction['featureName']=control['feature_name']
    if control and control.get('side_name'):interaction['sideBet']=control['side_name']
    if client.code=='TsarWars' and content['type']=='normalBet':
        native=client.init['game'].get('nextGameSelect',-1)
        interaction['gameSelect']=native if native in (1,2,3) else 1
    if interaction:content['playerInteraction']=interaction
    responses=[];target_used=False
    try:
        client.on_checkpoint=lambda:checkpoint(row)
        response=client.call('normal',content);responses.append(response);client.on_checkpoint=None
        for _ in range(1000):
            game=response.get('game')
            if not isinstance(game,dict):raise ValueError('game_response_missing')
            if game.get('nextMode')=='NORMAL':break
            point=choice_point(game,client.code);selected=None
            if point:
                selected=point.get('default','NO')
                if target and not target_used and target['node']==point['node'] and target['option'] in point['options']:
                    selected=target['option'];target_used=True
                row['choices'].append(dict(point,selected=selected,accumulated_before=str(game.get('accumulatedRoundWin',0))))
                if selected!='NO':row['extra_spin_costs']=str(Decimal(row['extra_spin_costs'])+Decimal(str(point['published_costs'][selected])))
                client.on_checkpoint=lambda:checkpoint(row)
            content=continuation(game,client.code,selected)
            response=client.call('normal',content);responses.append(response);client.on_checkpoint=None
        else:raise ValueError('round_step_limit')
        final=client.call('balance',{'type':'balance','bet':bet})
        if 'currency' in final and final['currency'].get('code')!=client.init['currency']['code']:
            raise ValueError('native_final_currency_changed')
        row.update(check_wallet(row['balance_before'],cost,native_win(responses,client.code),final['balance']),status='completed')
        row['closed_next_mode']=responses[-1]['game']['nextMode'];row['native_game_responses']=len(responses)
    except Exception as e:
        row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
    finally:client.on_checkpoint=None
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',default='1-100');p.add_argument('--phase',choices=['inventory','purchases','choices'],default='inventory')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--symbols',nargs='*');p.add_argument('--fresh-incomplete',action='store_true');p.add_argument('--attempts',type=int,default=20)
    args=p.parse_args();folder,games=scope(args.batch);folder.mkdir(parents=True,exist_ok=True);(folder/'traces').mkdir(exist_ok=True)
    write_json(folder/'catalog.json',games)
    proof=folder/'prior-providers-proof.json'
    if not proof.exists():
        paths=[ROOT.parent/'catalog-complete.json',*(ROOT.parent/'endorphina/batches').glob('*/audit.json'),*(ROOT.parent/'hacksaw/batches').glob('*/audit.json')]
        write_json(proof,{str(f.relative_to(ROOT.parent)):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths if f.exists()})
    if (folder/'audit.json').exists():
        (folder/'attempts').mkdir(exist_ok=True);(folder/'audit.json').replace(folder/'attempts'/('audit-'+str(time.time_ns())+'.json'))
    def report():
        from nolimit_reports import render
        render(args.batch)
    if args.phase=='choices':explore(folder,args,report);return
    inv_path=folder/'inventory.json';normal_path=folder/'rounds.json';buy_path=folder/'purchases.json'
    inventory={r['code']:r for r in read(inv_path,[])};normals={r['case']:r for r in read(normal_path,[])};buys={r['case']:r for r in read(buy_path,[])}
    specs=[]
    for game in games:
        if args.symbols and game['code'] not in args.symbols and game['id'] not in args.symbols:continue
        if args.phase=='inventory':specs.append(dict(game,kind='normal',case=game['code']+'--normal'));continue
        meta=inventory.get(game['code'],{})
        if meta.get('status')!='discovered':raise ValueError('inventory_incomplete:'+game['code'])
        specs.extend(dict(game,kind='purchase',case=game['code']+'--buy-'+str(i),control_id=c['control_id']) for i,c in enumerate(meta['controls']))
    def archive(case):
        path=folder/'traces'/(case+'.json')
        if path.exists():
            dest=folder/'attempts'/case;dest.mkdir(parents=True,exist_ok=True);write_json(dest/(str(time.time_ns())+'.json'),read(path,{}))
    def save(rows,path,key,row):
        rows[key]=deepcopy(row);write_json(path,list(rows.values()))
    def run(spec):
        normal=args.phase=='inventory';rows=normals if normal else buys;index=normal_path if normal else buy_path
        case=spec['case'];old=rows.get(case,{})
        same_control=old.get('control_id')==spec.get('control_id') and old.get('code')==spec['code']
        if same_control and old.get('status')=='completed' and old.get('wallet_check')=='match' and (not normal or inventory.get(spec['code'],{}).get('status')=='discovered'):return
        if old.get('stake_sent') and old.get('status')!='completed' and not args.fresh_incomplete:
            print(json.dumps({'case':case,'skipped':'uncertain_previous_entry_requires_fresh_attempt'}),flush=True);return
        if old:archive(case)
        client=None;row=dict(spec,status='running');meta=dict(spec,status='running')
        def checkpoint(current):
            with LOCK:
                write_json(folder/'traces'/(case+'.json'),{'summary':deepcopy(current),'trace':client.trace})
                save(rows,index,case,current)
                if normal:save(inventory,inv_path,spec['code'],meta)
        try:
            client=Nolimit(spec['code'])
            if normal:
                meta={k:v for k,v in spec.items() if k not in ('case','kind')}
                meta.update(status='discovered',version=client.version,minimum_bet=client.minimum_bet(),controls=controls(client.init),init=redact(client.init))
                write_json(folder/'traces'/(spec['code']+'-initialization.json'),client.trace[:1])
            if same_control and old.get('status')=='completed' and old.get('wallet_check')=='match':row=old
            else:row=finish(client,spec,checkpoint)
        except Exception as e:
            row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
            if normal:meta.update(status='needs_review',reason=row['reason'])
            response=getattr(e,'response',None)
            if response is not None:row['http_status']=response.status_code;meta['http_status']=response.status_code
        finally:
            if client:
                if row is not old:write_json(folder/'traces'/(case+'.json'),{'summary':row,'trace':client.trace})
                client.close()
            with LOCK:
                save(rows,index,case,row)
                if normal:save(inventory,inv_path,spec['code'],meta)
                report()
            print(json.dumps({'case':case,'status':row['status'],'wallet':row.get('wallet_check'),'reason':row.get('reason')}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,specs))
    print(json.dumps({'finished':True,'phase':args.phase,'states':dict(Counter(r['status'] for r in (normals if args.phase=='inventory' else buys).values()))}),flush=True)


def explore(folder,args,report):
    bases=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])
    expected={g['code']+'--normal':None for g in read(folder/'catalog.json',[])}
    for meta in read(folder/'inventory.json',[]):
        for i,control in enumerate(meta.get('controls',[])):expected[meta['code']+'--buy-'+str(i)]=control['control_id']
    if len(bases)!=len(expected) or {r['case']:r.get('control_id') for r in bases}!=expected:raise ValueError('complete_expected_base_inventory_required')
    if any(r['status']!='completed' or r.get('wallet_check')!='match' for r in bases):raise ValueError('base_cases_must_be_reconciled')
    path=folder/'choices.json';rows={r['case']:r for r in read(path,[])};matrices={r['case']:{} for r in bases}
    incomplete=[r for r in rows.values() if r['status']!='completed']
    if any(r.get('stake_sent') for r in incomplete) and not args.fresh_incomplete:raise ValueError('uncertain_choice_requires_fresh_attempt')
    for row in incomplete:
        dest=folder/'attempts'/row['case'];dest.mkdir(parents=True,exist_ok=True)
        write_json(dest/(str(time.time_ns())+'.json'),read(folder/'traces'/(row['case']+'.json'),{'summary':row,'trace':[]}));rows.pop(row['case'])
    def absorb(row):
        matrix=matrices[row.get('root_case',row['case'])]
        for choice in row.get('choices',[]):
            for option in choice['options']:
                key=choice['node']+':'+option
                goal=matrix.setdefault(key,{'node':choice['node'],'family':choice['family'],'option':option,'verified':False,'evidence':[]})
                if row['status']=='completed' and row.get('wallet_check')=='match' and choice['selected']==option:
                    goal['verified']=True
                    if row['case'] not in goal['evidence']:goal['evidence'].append(row['case'])
    for row in bases+list(rows.values()):absorb(row)
    from nolimit_history import history_points
    for item in history_points(folder,bases):
        point=item['point'];matrix=matrices[item['root']]
        for option in point['options']:
            key=point['node']+':'+option
            goal=matrix.setdefault(key,{'node':point['node'],'family':point['family'],'option':option,'verified':False,'evidence':[]})
            goal['default']=point.get('default','NO')
            sources=goal.setdefault('observed_in_archives',[])
            if item['source'] not in sources:sources.append(item['source'])
    def save():
        write_json(path,list(rows.values()));goals=[g for m in matrices.values() for g in m.values()]
        write_json(folder/'choices-matrix.json',{'summary':{'options':len(goals),'verified':sum(g['verified'] for g in goals)},'roots':matrices});report()
    def run(base):
        matrix=matrices[base['case']];attempts={};prefix=base['case']+'--choice-'
        historical=list(rows)+[p.name for p in (folder/'attempts').glob(prefix+'*')]
        number=max([int(k[len(prefix):]) for k in historical if k.startswith(prefix)]+[0])
        for _ in range(200):
            pending=[(key,g) for key,g in matrix.items() if not g['verified'] and attempts.get(key,0)<args.attempts]
            pending.sort(key=lambda pair:pair[1]['option']==pair[1].get('default','NO'))
            if not pending:break
            key,goal=pending[0];attempts[key]=attempts.get(key,0)+1;number+=1;client=None
            spec={k:base[k] for k in ('id','code','name','slug','details_url','release_date','control_id') if k in base}
            spec.update(case=prefix+str(number),root_case=base['case'],kind='choice',choice_target={'node':goal['node'],'option':goal['option']})
            def checkpoint(current):
                with LOCK:
                    rows[spec['case']]=deepcopy(current);write_json(path,list(rows.values()))
                    write_json(folder/'traces'/(spec['case']+'.json'),{'summary':deepcopy(current),'trace':client.trace})
            try:
                client=Nolimit(base['code']);row=finish(client,spec,checkpoint,spec['choice_target'])
            except Exception as e:row=dict(spec,status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
            finally:
                if client:write_json(folder/'traces'/(spec['case']+'.json'),{'summary':row,'trace':client.trace});client.close()
            with LOCK:rows[row['case']]=row;absorb(row);save()
            print(json.dumps({'case':row['case'],'status':row['status'],'reason':row.get('reason')}),flush=True)
            if row['status']!='completed':break
    with LOCK:save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,bases))
    with LOCK:save()
    print(json.dumps({'finished':True,**read(folder/'choices-matrix.json',{})['summary']}),flush=True)


if __name__=='__main__':main()
