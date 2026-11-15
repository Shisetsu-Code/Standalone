"""Resumeable coverage of advertised controls in public Hacksaw demos."""
import argparse
from collections import Counter
import concurrent.futures
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from hacksaw_client import Hacksaw
from hacksaw_protocol import check_round,choice_point,continuation
from hacksaw_contracts import mode_cases
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent/'hacksaw'
LOCK=threading.Lock()


def read(path,default):
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else default


def scope(batch):
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*',batch):raise ValueError('invalid_batch')
    first,last=map(int,batch.split('-'))
    if last<first or last-first>=100:raise ValueError('invalid_batch_range')
    games=read(ROOT/'catalog.json',[])[first-1:last]
    if len(games)!=last-first+1:raise ValueError('catalog_scope_incomplete')
    return ROOT/'batches'/batch,games


def finish(client,spec,checkpoint=None,target=None):
    row=dict(spec,status='running',balance_before=client.balance,bet=client.bet,currency='EUR',version=client.version,choices=[])
    bonus=spec.get('bonus_id')
    control=next((b for b in client.auth.get('bonusGames') or [] if b['bonusGameId']==bonus),None) if bonus else None
    if bonus and control is None:raise ValueError('published_control_removed')
    multiplier=str(control['betCostMultiplier']) if control else '1'
    row['multiplier']=multiplier
    if control:row['published_control']=control
    if Decimal(client.bet)*Decimal(multiplier)>Decimal(client.balance):raise ValueError('insufficient_demo_funding_for_control')
    if checkpoint:checkpoint(row)
    row['stake_sent']=True
    if checkpoint:checkpoint(row)
    try:
        response=client.wager(bonus,base_mode=spec.get('base_mode'));responses=[response]
        for _ in range(200):
            current=response['round']
            if current['status']=='completed':break
            point=choice_point(current);selected=None
            if point:
                if target and target['node']==point['node'] and target['option'] in point['options']:selected=target['option']
                action=continuation(current,selected)
                row['choices'].append(dict(point,selected=action))
            else:action=continuation(current)
            response=client.step(current['roundId'],action);responses.append(response)
        else:raise ValueError('round_step_limit')
        row.update(check_round(client.balance,client.bet,multiplier,responses),status='completed')
    except Exception as e:
        row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',default='1-100');p.add_argument('--workers',type=int,default=4)
    p.add_argument('--phase',choices=['inventory','purchases','choices'],default='inventory')
    p.add_argument('--symbols',nargs='*');p.add_argument('--fresh-incomplete',action='store_true');p.add_argument('--attempts',type=int,default=20)
    args=p.parse_args();folder,games=scope(args.batch);folder.mkdir(parents=True,exist_ok=True);(folder/'traces').mkdir(exist_ok=True)
    write_json(folder/'catalog.json',games)
    # Preserve earlier provider audits as immutable evidence of isolation.
    proof=folder/'prior-providers-proof.json'
    if not proof.exists():
        paths=[ROOT.parent/'catalog-complete.json',*(ROOT.parent/'endorphina/batches').glob('*/audit.json')]
        write_json(proof,{str(path.relative_to(ROOT.parent)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.exists()})
    if (folder/'audit.json').exists():
        (folder/'attempts').mkdir(exist_ok=True)
        (folder/'audit.json').replace(folder/'attempts'/('audit-'+str(time.time_ns())+'.json'))

    def report():
        from hacksaw_reports import render
        render(args.batch)

    if args.phase=='choices':
        explore(folder,games,args,report);return
    path=folder/('inventory.json' if args.phase=='inventory' else 'purchases.json')
    rows={r['id'] if args.phase=='inventory' else r['case']:r for r in read(path,[])}
    normals={r['case']:r for r in read(folder/'rounds.json',[])}
    inventory={r['id']:r for r in read(folder/'inventory.json',[])}
    specs=[]
    for g in games:
        if args.symbols and g['id'] not in args.symbols and g['slug'] not in args.symbols:continue
        if args.phase=='inventory':specs.append(g);continue
        meta=inventory.get(g['id'],{})
        if meta.get('status')!='discovered':raise ValueError('inventory_incomplete:'+g['id'])
        specs.extend(dict(g,kind='purchase',case=g['id']+'--buy-'+str(i),bonus_id=b['bonusGameId'],control_type='activator' if b['bonusGameId'].startswith('mod_') else 'bonus') for i,b in enumerate(meta.get('bonus_games') or []))
        specs.extend(mode_cases(g))

    def save_row(key,row,client):
        with LOCK:
            rows[key]=deepcopy(row);write_json(path,list(rows.values()));report()

    def run(spec):
        key=spec['id'] if args.phase=='inventory' else spec['case'];old=rows.get(key,{})
        normal_case=spec['id']+'--normal';old_normal=normals.get(normal_case,{})
        if args.phase=='inventory' and old.get('status')=='discovered' and normals.get(spec['id']+'--normal',{}).get('status')=='completed':return
        if args.phase=='inventory' and old_normal.get('stake_sent') and old_normal.get('status')!='completed' and not args.fresh_incomplete:
            print(json.dumps({'case':normal_case,'skipped':'uncertain_previous_stake_requires_explicit_fresh_attempt'}),flush=True);return
        if args.phase=='purchases' and old.get('status')=='completed' and old.get('wallet_check')=='match':return
        if old.get('stake_sent') and not args.fresh_incomplete:
            print(json.dumps({'case':key,'skipped':'uncertain_previous_stake_requires_explicit_fresh_attempt'}),flush=True);return
        client=None;row=dict(spec,status='running');trace_path=folder/'traces'/(key+'.json')
        if args.fresh_incomplete and trace_path.exists():
            dest=folder/'attempts'/key;dest.mkdir(parents=True,exist_ok=True)
            write_json(dest/(str(time.time_ns())+'.json'),read(trace_path,{}))
        try:
            client=Hacksaw(spec['id'])
            if args.phase=='inventory':
                row.update(status='discovered',version=client.version,balance=client.balance,minimum_bet=client.bet,
                    bonus_games=client.auth.get('bonusGames') or [],auth=client.trace[-1]['response'],partner_settings=client.settings)
                case=spec['id']+'--normal'
                normal_trace=folder/'traces'/(case+'.json')
                if old_normal.get('status')=='completed' and old_normal.get('wallet_check')=='match':
                    normal=old_normal
                else:
                    if normal_trace.exists():
                        dest=folder/'attempts'/case;dest.mkdir(parents=True,exist_ok=True)
                        write_json(dest/(str(time.time_ns())+'.json'),read(normal_trace,{}))
                    def normal_checkpoint(current):
                        write_json(normal_trace,{'summary':deepcopy(current),'trace':client.trace})
                        with LOCK:
                            normals[case]=deepcopy(current);rows[key]=deepcopy(row)
                            write_json(folder/'rounds.json',list(normals.values()));write_json(path,list(rows.values()));report()
                    normal=finish(client,dict(spec,kind='normal',case=case),normal_checkpoint)
                    write_json(normal_trace,{'summary':normal,'trace':client.trace})
                    with LOCK:normals[case]=normal;write_json(folder/'rounds.json',list(normals.values()))
                write_json(folder/'traces'/(key+'-initialization.json'),client.trace[:2])
            else:
                def checkpoint(current):
                    write_json(trace_path,{'summary':current,'trace':client.trace});save_row(key,current,client)
                row=finish(client,spec,checkpoint)
        except Exception as e:
            row.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
            response=getattr(e,'response',None)
            if response is not None:row['http_status']=response.status_code
        finally:
            if client:
                if args.phase=='purchases':write_json(trace_path,{'summary':row,'trace':client.trace})
                client.close()
            save_row(key,row,client)
            print(json.dumps({'case':key,'status':row['status'],'wallet':row.get('wallet_check'),'reason':row.get('reason'),'records':len(rows)}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,specs))
    print(json.dumps({'finished':True,'phase':args.phase,'states':dict(Counter(r['status'] for r in rows.values()))}),flush=True)


def explore(folder,games,args,report):
    bases=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])
    if any(r['status']!='completed' or r.get('wallet_check')!='match' for r in bases):raise ValueError('base_rounds_must_be_reconciled')
    path=folder/'choices.json';rows={r['case']:r for r in read(path,[])};matrices={r['case']:{} for r in bases}
    incomplete=[r for r in rows.values() if r['status']!='completed' or r.get('wallet_check')!='match']
    if any(r.get('stake_sent') for r in incomplete) and not args.fresh_incomplete:raise ValueError('uncertain_choice_attempt_requires_fresh')
    for old in incomplete:
        dest=folder/'attempts'/old['case'];dest.mkdir(parents=True,exist_ok=True)
        source=folder/'traces'/(old['case']+'.json')
        write_json(dest/(str(time.time_ns())+'.json'),read(source,{'summary':old,'trace':[]}))
        rows.pop(old['case'])
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
    def save():
        write_json(path,list(rows.values()));goals=[g for m in matrices.values() for g in m.values()]
        write_json(folder/'choices-matrix.json',{'summary':{'options':len(goals),'verified':sum(g['verified'] for g in goals)},'roots':matrices});report()
    def run(base):
        matrix=matrices[base['case']];attempts={}
        if not any(not g['verified'] for g in matrix.values()):return
        prefix=base['case']+'--choice-'
        historical=list(rows)+[p.name for p in (folder/'attempts').glob(prefix+'*')]
        number=max([int(k[len(prefix):]) for k in historical if k.startswith(prefix)]+[0])
        for _ in range(200):
            pending=[(k,g) for k,g in matrix.items() if not g['verified'] and attempts.get(k,0)<args.attempts]
            if not pending:break
            key,goal=pending[0];attempts[key]=attempts.get(key,0)+1;number+=1;client=None
            spec={k:base[k] for k in ('id','name','slug','details_url','bonus_id','control_type','base_mode','label') if k in base}
            spec.update(case=prefix+str(number),root_case=base['case'],kind='choice',choice_target={'node':goal['node'],'option':goal['option']})
            try:
                client=Hacksaw(base['id'])
                def choice_checkpoint(current):
                    with LOCK:
                        rows[spec['case']]=deepcopy(current)
                        write_json(folder/'traces'/(spec['case']+'.json'),{'summary':deepcopy(current),'trace':client.trace});save()
                row=finish(client,spec,choice_checkpoint,target=spec['choice_target'])
            except Exception as e:row=dict(spec,status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__)
            finally:
                if client:
                    write_json(folder/'traces'/(spec['case']+'.json'),{'summary':row,'trace':client.trace});client.close()
            with LOCK:rows[row['case']]=row;absorb(row);save()
            print(json.dumps({'case':row['case'],'status':row['status'],'reason':row.get('reason')}),flush=True)
            if row['status']!='completed':break
    with LOCK:save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,bases))
    with LOCK:save()
    print(json.dumps({'finished':True,**read(folder/'choices-matrix.json',{})['summary']}),flush=True)


if __name__=='__main__':main()
