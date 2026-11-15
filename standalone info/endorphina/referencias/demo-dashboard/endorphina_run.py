"""Resumeable, provider-isolated coverage for the official Endorphina demo."""
import argparse
from collections import Counter
import concurrent.futures
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import threading
import uuid
from atomic_report import replace_report
from endorphina_client import Endorphina
from endorphina_paths import batch_path,catalog_slice

ROOT = Path(__file__).resolve().parent / 'endorphina'
LOCK = threading.Lock()


def write_json(path, value):
    temp = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf8')
    replace_report(temp,path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['inventory'], default='inventory')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--with-normal',action='store_true')
    args=parser.parse_args()
    folder=batch_path()
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'traces').mkdir(exist_ok=True)
    catalog=catalog_slice()
    if not catalog or len({g['id'] for g in catalog})!=len(catalog):
        raise ValueError('first_100_catalog_invalid')
    write_json(folder/'catalog.json',catalog)
    path=folder/'inventory.json'
    previous=json.loads(path.read_text(encoding='utf8')) if path.exists() else []
    rows={r['slug']:r for r in previous}
    normal_path=folder/'rounds.json'
    normal_rows={r['case']:r for r in json.loads(normal_path.read_text(encoding='utf8'))} if normal_path.exists() else {}
    feature_path=folder/'features.json'
    feature_rows={r['slug']:r for r in json.loads(feature_path.read_text(encoding='utf8'))} if feature_path.exists() else {}

    def run(game):
        case=game['slug']+'--normal'
        if rows.get(game['slug'],{}).get('status')=='discovered' and (not args.with_normal or normal_rows.get(case,{}).get('status')=='completed'):
            return
        client=None
        row={**game,'status':'running','checked_utc':datetime.now(timezone.utc).isoformat()}
        try:
            client=Endorphina(game['play_url'])
            row.update(status='discovered',game=client.game,currency=client.currency,
                buy_ins=client.paytable.get('buyIns'),extra_bet=client.paytable.get('extra_bet'),
                default_parameters=client.parameters,balance=client.balance,history_status=client.history['status'],
                paytable={k:v for k,v in client.paytable.items() if k not in ('virtual_strips','virtual_fg_strips','bonus_strips')})
            config_url=client.asset_base+'/configs/config.desktop.json'
            config=client.http.get(config_url,timeout=25)
            config.raise_for_status()
            from endorphina_choices import CONFIG,features_from_config
            features=features_from_config(config.json())
            CONFIG[game['slug']]=features
            with LOCK:
                feature_rows[game['slug']]={'slug':game['slug'],'status':'discovered','features':features,'source':config_url}
                write_json(feature_path,list(feature_rows.values()))
            if args.with_normal:
                from decimal import Decimal
                from endorphina_rounds import close_round
                from endorphina_paths import private_path
                normal={**game,'case':case,'kind':'normal','status':'running','game':client.game,'currency':client.currency,
                    'parameters':client.parameters,'balance_before':client.balance['balance']}
                params=client.parameters
                normal['cost']=str((Decimal(str(params['bet_per_line']))*params['num_of_lines']+Decimal(str(params['extra_bet'])))*Decimal(params['denom']))
                private_path().mkdir(parents=True,exist_ok=True)
                write_json(private_path()/(case+'.json'),client.connection)
                try:
                    normal['stake_sent']=True
                    client.history=client.call('START_GAME',params)['data']
                    normal['first_history']=client.history
                    close_round(client,normal)
                except Exception as e:
                    normal.update(status='needs_review',reason=str(e) if isinstance(e,ValueError) else type(e).__name__,last_history=client.history)
                write_json(folder/'traces'/(case+'.json'),{'case':case,'slug':game['slug'],'trace':client.trace,'summary':normal})
                with LOCK:
                    normal_rows[case]=normal
                    write_json(normal_path,list(normal_rows.values()))
        except Exception as e:
            row.update(status='needs_review',reason=type(e).__name__)
            if isinstance(e,ValueError):row['reason']=str(e).split('https:')[0]
        finally:
            if client:
                write_json(folder/'traces'/(game['slug']+'-initialization.json'),client.trace)
                client.close()
            with LOCK:
                rows[game['slug']]=row
                ordered=[rows[g['slug']] for g in catalog if g['slug'] in rows]
                write_json(path,ordered)
                summary={'provider':'endorphina','scope_games':len(catalog),'phase':'inventory','states':dict(Counter(r['status'] for r in ordered)),
                    'games_with_buy_ins':sum(bool(r.get('buy_ins')) for r in ordered),'games_with_extra_bet':sum(bool(r.get('extra_bet')) for r in ordered)}
                write_json(folder/'progress.json',summary)
                print(json.dumps({'game':game['slug'],'state':row['status'],'processed':len(ordered),'scope':len(catalog),'reason':row.get('reason')}),flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run,catalog))
    print(json.dumps({'finished':True,'phase':args.phase,'states':dict(Counter(r['status'] for r in rows.values()))}),flush=True)


if __name__=='__main__':
    main()
