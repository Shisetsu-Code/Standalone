"""Offline validation of retained native replies. This module never sends requests."""
import argparse,json
from pathlib import Path
from elk_protocol import parse_xml,settlement,results,round_id
from elk_run import FOLDER,read
from endorphina_run import write_json
from elk_paths import batch_path,BATCHES

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=list(BATCHES),default='1-100');args=parser.parse_args();FOLDER=batch_path(args.batch)
    rows=read(FOLDER/'rounds.json',[]);updated=0;remaining=[]
    for row in rows:
        path=FOLDER/'traces'/(row['case']+'.json');doc=read(path,{})
        try:
            if doc.get('campaign'):
                from elk_boss_audit import verify_target
                candidate=dict(row,status='completed');candidate.pop('error',None)
                verify_target(dict(doc,summary=candidate));row.update(status='completed');row.pop('error',None);updated+=1
            else:
                trace=doc['trace']
                if len(trace)!=3 or any(s.get('http_status')!=200 for s in trace):raise ValueError('native_transport_incomplete')
                native=[parse_xml(s['response']) for s in trace];financial=settlement(*native,row['control']);financial['round_id']=round_id(financial['round_id'])
                row.update(financial,status='completed');row.pop('error',None);doc['results']=results(native[1]);updated+=1
        except Exception as error:
            row['status']='needs_review'
            if str(error)!='native_transport_incomplete' or not row.get('error'):row['error']=type(error).__name__+':'+str(error)[:250]
            remaining.append(row['case'])
        doc['summary']=row;write_json(path,doc)
    write_json(FOLDER/'rounds.json',rows)
    print(json.dumps({'revalidated_offline':updated,'pending':remaining},ensure_ascii=True))

if __name__=='__main__':main()
