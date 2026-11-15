"""Recover completed rounds mislabeled when a Windows report write was locked.

No network or gameplay. Requires native evidence of closure and exact balance.
Run after the gameplay writer exits so it cannot overwrite the repaired report.
"""
import argparse
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path
import time
from endorphina_audit import verify
from endorphina_run import write_json

ROOT=batch_path()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    metadata={r['slug']:r for r in json.loads((ROOT/'inventory.json').read_text(encoding='utf8'))}
    path=ROOT/'risk.json'
    rows=json.loads(path.read_text(encoding='utf8'))
    recovered=[]
    for row in rows:
        if row.get('reason')!='PermissionError':continue
        trace_path=ROOT/'traces'/(row['case']+'.json')
        trace=json.loads(trace_path.read_text(encoding='utf8'))
        issues=verify(row,trace['trace'],metadata[row['slug']],require_status=False)
        if issues:continue
        recovered.append(row['case'])
        if args.apply:
            archive=ROOT/'attempts'/row['case']
            archive.mkdir(parents=True,exist_ok=True)
            write_json(archive/(str(time.time_ns())+'.json'),trace)
            row.setdefault('diagnostics',[]).append('Report write was locked; native closure and wallet independently verified.')
            row.update(status='completed',wallet_check='match')
            row.pop('reason',None)
            trace['summary']=row
            write_json(trace_path,trace)
    if args.apply:write_json(path,rows)
    print(json.dumps({'applied':args.apply,'recoverable_closed_rounds':len(recovered),'cases':recovered}))


if __name__=='__main__':main()
