"""Run risk coverage as each game's normal/configuration becomes available."""
import json
from pathlib import Path
import subprocess
import sys
import time
from endorphina_paths import batch_path,catalog_slice,unavailable_slugs
from endorphina_risk_contract import options


def read(name):
    path=batch_path()/name
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else []


def main():
    catalog=catalog_slice()
    previous=None
    for _ in range(500):
        normals={r['slug'] for r in read('rounds.json') if r['status']=='completed' and r.get('wallet_check')=='match'}
        config={r['slug']:r for r in read('features.json') if r['status']=='discovered'}
        risk=read('risk.json')
        ready=[]
        for game in catalog:
            slug=game['slug']
            if slug not in normals or slug not in config:continue
            types=[f['featureClassName'] for f in config[slug]['features'] if f['featureID']=='GAMBLE']
            controls=options(config[slug]['features'])
            if any(not any(r['slug']==slug and r.get('kind')=='risk' and r.get('option')==i and r['status']=='completed' for r in risk) for i in range(len(controls))):
                ready.append(slug)
        if ready:
            print(json.dumps({'risk_wave_games':len(ready),'normals_ready':len(normals)}),flush=True)
            result=subprocess.run([sys.executable,'-u','endorphina_risk.py','--workers','6','--symbols',*ready],cwd=Path(__file__).resolve().parent)
            if result.returncode:raise SystemExit(result.returncode)
            after=read('risk.json')
            if any(r['status']!='completed' for r in after):
                print(json.dumps({'risk_needs_review':[(r['case'],r.get('reason')) for r in after if r['status']!='completed']}),flush=True)
                return
        elif len(normals)+len(unavailable_slugs())==len(catalog):
            print(json.dumps({'finished':True,'scope':len(catalog),'verified_risk_options':sum(r.get('kind')=='risk' and r['status']=='completed' for r in risk)}),flush=True)
            return
        else:
            status=(len(normals),len(config))
            if status!=previous:print(json.dumps({'waiting_for_normal_and_config':status}),flush=True);previous=status
            time.sleep(5)
    raise RuntimeError('coverage_wait_limit')


if __name__=='__main__':main()
