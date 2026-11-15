"""Read published per-game feature declarations without gameplay requests."""
import concurrent.futures
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path
import re
import threading
import requests
from endorphina_choices import features_from_config
from endorphina_run import write_json

ROOT=batch_path()


def main():
    inv=json.loads((ROOT/'inventory.json').read_text(encoding='utf8'))
    path=ROOT/'features.json'
    records=json.loads(path.read_text(encoding='utf8')) if path.exists() else []
    rows={r['slug']:r for r in records}
    lock=threading.Lock()
    def run(meta):
        if rows.get(meta['slug'],{}).get('status')=='discovered' or meta['status']!='discovered':return
        row={'slug':meta['slug']}
        try:
            if not re.fullmatch('endorphina2_[A-Za-z0-9_]+',meta['game']):raise ValueError('unrecognized_game_path')
            url='https://demo.endorphina.network/games-wgl/endorphina2/'+meta['game'].split('_',1)[1]+'/configs/config.desktop.json'
            r=requests.get(url,timeout=25);r.raise_for_status();data=r.json()
            row.update(status='discovered',features=features_from_config(data),source=url)
        except Exception as e:row.update(status='needs_review',reason=type(e).__name__)
        with lock:
            rows[row['slug']]=row
            write_json(path,list(rows.values()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run,inv))
    print({'feature_configs':len(rows),'games_with_risk':sum(any(f['featureID']=='GAMBLE' for f in r.get('features',[])) for r in rows.values())})


if __name__=='__main__':main()
