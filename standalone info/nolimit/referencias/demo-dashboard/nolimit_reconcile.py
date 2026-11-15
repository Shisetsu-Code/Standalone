"""Enrich already closed native evidence offline; never sends a game request."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
from endorphina_run import write_json
from nolimit_protocol import choice_point,continuation,check_wallet,native_win
from nolimit_audit import audit_case

def reconcile(folder):
    updated=0;rejected=[]
    for name in ('rounds.json','purchases.json','choices.json'):
        index=folder/name
        if not index.exists():continue
        rows=json.loads(index.read_text(encoding='utf8'))
        for i,old in enumerate(rows):
            path=folder/'traces'/(old['case']+'.json')
            if not path.exists():continue
            document=json.loads(path.read_text(encoding='utf8'));trace=document['trace']
            if not trace or trace[-1]['request']['type']!='balance':continue
            try:
                responses=[next(r for r in step['responses'] if r.get('id')==step['request']['id']) for step in trace]
                if any(r.get('error') for r in responses):continue
                if responses[-2].get('game',{}).get('nextMode')!='NORMAL':continue
                row=deepcopy(old);row['choices']=[];internal=Decimal(0)
                for step_num,response in enumerate(responses[1:-2],start=2):
                    game=response['game'];point=choice_point(game,row['code'])
                    if point:
                        actual=trace[step_num]['request']['content']
                        selected=[o for o in point['options'] if continuation(game,row['code'],o)==actual]
                        if len(selected)!=1:raise ValueError('native_selection_not_uniquely_verified')
                        selected=selected[0]
                        row['choices'].append(dict(point,selected=selected,accumulated_before=str(game.get('accumulatedRoundWin',0))))
                        if selected!='NO':internal+=Decimal(str(point['published_costs'][selected]))
                row.update(check_wallet(responses[0]['balance'],row['cost'],native_win(responses[1:-1],row['code']),responses[-1]['balance']))
                row.update(status='completed',extra_spin_costs=str(internal),closed_next_mode='NORMAL',native_game_responses=len(responses)-2)
                row.pop('reason',None);proposed={'summary':row,'trace':trace}
                with tempfile.TemporaryDirectory() as temp:
                    test=Path(temp);(test/'traces').mkdir();(test/'traces'/path.name).write_text(json.dumps(proposed),encoding='utf8');audit_case(test,row)
                if row==old:continue
                archive=folder/'attempts'/old['case'];archive.mkdir(parents=True,exist_ok=True)
                write_json(archive/('reconcile-'+str(time.time_ns())+'.json'),document)
                rows[i]=row;write_json(path,proposed);updated+=1
            except Exception as error:rejected.append({'case':old['case'],'error':str(error)})
        write_json(index,rows)
    print(json.dumps({'offline_updated':updated,'rejected':rejected}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',default='1-100');args=parser.parse_args()
    from nolimit_run import scope
    reconcile(scope(args.batch)[0])
