"""Resumable first-100 official ELK demo coverage, with durable native traces."""
import argparse,concurrent.futures,hashlib,json,threading,time,uuid
from pathlib import Path
from elk_client import Elk
from elk_protocol import mode_controls,settlement,results,parse_xml,round_id,validate_fresh_demo
from endorphina_run import write_json
from elk_paths import batch_path,catalog_slice,BATCHES

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'elk/batches/1-100'
LOCK=threading.Lock()

def read(path,default):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
def case_name(slug,control):return slug+'--'+control['mode']+('--variant-'+control['variant'] if control.get('variant') else '')
def purchase_checked(client,init,control):
    validate_fresh_demo(init)
    if control not in mode_controls(init):raise ValueError('control_not_published')
    return client.purchase(control)

def main():
    global FOLDER
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=list(BATCHES),default='1-100');parser.add_argument('--workers',type=int,default=4);parser.add_argument('--only');parser.add_argument('--phase',choices=['normal','purchases','all'],default='all');parser.add_argument('--retry-incomplete',action='store_true');args=parser.parse_args()
    FOLDER=batch_path(args.batch);catalog=catalog_slice(args.batch)
    if len({g['slug'] for g in catalog})!=len(catalog):raise ValueError('invalid_scope')
    FOLDER.mkdir(parents=True,exist_ok=True);(FOLDER/'traces').mkdir(exist_ok=True);write_json(FOLDER/'catalog.json',catalog)
    inventory={r['slug']:r for r in read(FOLDER/'inventory.json',[])};rows={r['case']:r for r in read(FOLDER/'rounds.json',[])}
    # Revised native-contract discovery supersedes unsupported attempts, retaining evidence.
    for item in inventory.values():item['controls']=mode_controls(parse_xml(item['init']))
    valid={case_name(item['slug'],c) for item in inventory.values() for c in item['controls']}
    obsolete=[key for key,row in rows.items() if row['slug'] in inventory and key not in valid]
    for key in obsolete:
        archive=FOLDER/'attempts';archive.mkdir(exist_ok=True)
        path=FOLDER/'traces'/(key+'.json')
        if path.exists():write_json(archive/(key+'-'+uuid.uuid4().hex+'.json'),read(path,{}));path.unlink()
        del rows[key]
    def save_rows():
        write_json(FOLDER/'inventory.json',list(inventory.values()));write_json(FOLDER/'rounds.json',list(rows.values()))
    def run(game):
        def case(control=None):
            if control is None and game['slug'] in inventory:control=inventory[game['slug']]['controls'][0]
            name=case_name(game['slug'],control or {'mode':'DEF'});path=FOLDER/'traces'/(name+'.json')
            old=rows.get(name)
            if old and (old.get('status')=='completed' or not args.retry_incomplete):return
            if path.exists():
                archive=FOLDER/'attempts';archive.mkdir(exist_ok=True)
                write_json(archive/(name+'-'+uuid.uuid4().hex+'.json'),read(path,{}))
            primary=inventory.get(game['slug'],{}).get('controls',[None])[0]
            kind='normal' if control is None or control['mode']=='DEF' and (not control.get('variant') or control==primary) else 'variant' if control['mode']=='DEF' else 'purchase'
            row={'case':name,'slug':game['slug'],'id':game['id'],'name':game['name'],'kind':kind,'mode':control['mode'] if control else 'DEF','status':'running','created':time.time()}
            doc={'game':game,'summary':row,'trace':[]}
            def durable(client):
                doc.update(trace=client.trace,launch=getattr(client,'launch',{}))
                with LOCK:write_json(path,doc)
            client=Elk(game,durable)
            with LOCK:rows[name]=row;save_rows();write_json(path,doc)
            try:
                init=client.open();native_controls=mode_controls(init)
                if control is None:control=native_controls[0]
                if control not in native_controls:raise ValueError('inventory_changed_before_entry')
                canonical=case_name(game['slug'],control)
                if canonical!=name:
                    with LOCK:
                        old_path=path;rows.pop(name,None);name=canonical;path=FOLDER/'traces'/(name+'.json');row['case']=name
                        rows[name]=row;write_json(path,doc);old_path.unlink(missing_ok=True)
                row['control']=control;row['variant']=control.get('variant')
                with LOCK:
                    if game['slug'] not in inventory or row['kind']=='normal':
                        inventory[game['slug']]={'slug':game['slug'],'id':game['id'],'status':'discovered','controls':native_controls,'init':doc['trace'][0]['response'],'launch':client.launch}
                    save_rows()
                # The trace is committed before every outgoing purchase. No automatic retry.
                purchase=purchase_checked(client,init,control);check=client.check(purchase)
                financial=settlement(init,purchase,check,control);financial['round_id']=round_id(financial['round_id'])
                row.update(financial,status='completed')
                doc['results']=results(parse_xml(doc['trace'][1]['response']))
            except Exception as error:
                row.update(status='needs_review',error=type(error).__name__+':'+str(error)[:250])
            finally:
                client.session.close()
                with LOCK:write_json(path,doc);save_rows()
                print(json.dumps({'case':name,'status':row['status'],'error':row.get('error'),'results':row.get('native_results')},ensure_ascii=True),flush=True)
        if args.phase in ('normal','all'):case()
        if args.phase in ('purchases','all'):
            for control in inventory.get(game['slug'],{}).get('controls',[]):
                if control!=inventory[game['slug']]['controls'][0]:case(control)
    selected=[g for g in catalog if not args.only or g['slug']==args.only]
    if not selected:raise ValueError('selection_empty')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run,selected))
    print(json.dumps({'games_in_inventory':len(inventory),'completed':sum(r.get('status')=='completed' for r in rows.values()),'review':sum(r.get('status')=='needs_review' for r in rows.values())}),flush=True)

if __name__=='__main__':main()
