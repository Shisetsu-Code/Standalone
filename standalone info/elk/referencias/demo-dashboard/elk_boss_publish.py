"""Publish only independently verified Boss cases; archive prior failed attempts."""
import argparse,hashlib,json,time
from pathlib import Path
from elk_boss_audit import audit
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent
def read(path):return json.loads(path.read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def publish(campaign):
    report=audit(campaign)
    if not report['passed']:raise ValueError('campaign_incomplete_or_invalid')
    first=ROOT/'elk/batches/1-100';second=ROOT/'elk/batches/101-159';source=ROOT/'elk/boss-campaigns'/campaign
    proof=read(second/'prior-providers-proof.json')
    if any(sha(ROOT/name)!=value for name,value in proof.items()):raise ValueError('prior_proof_changed_before_publish')
    rows=read(first/'rounds.json');game=next(g for g in read(first/'catalog.json') if g['id']=='10266');initial=read(source/'initialization.json')
    expected={'pirots-5--'+mode+'--variant-boss' for mode in ('DEF','X01','X02','X03','X04','X05')}
    targets=[r for r in rows if r['case'] in expected]
    if len(targets)!=6 or {r['case'] for r in targets}!=expected:raise ValueError('six_existing_targets_required')
    archive=first/'attempts';archive.mkdir(exist_ok=True)
    write_json(archive/('rounds-before-boss-'+campaign+'.json'),rows)
    for entry in report['verified']:
        if entry['kind']!='boss':continue
        case='pirots-5--'+entry['control']['mode']+'--variant-boss';row=next(r for r in targets if r['case']==case);path=first/'traces'/(case+'.json');native=read(source/'rounds'/('%05d.json'%entry['sequence']))
        write_json(archive/(case+'-before-'+campaign+'.json'),read(path))
        row.update({k:v for k,v in entry.items() if k not in ('sequence','kind','control')});row.update(status='completed',control=entry['control'],variant='boss',completed=time.time());row.pop('error',None)
        write_json(path,{'game':game,'summary':row,'launch':initial['launch'],'campaign':campaign,'campaign_sequence':entry['sequence'],'trace':native['trace'],'results':native['results']})
    write_json(first/'rounds.json',rows)
    previous=read(first/'blocked-variants.json');previous.update(status='completed',campaign=campaign,completed_modes=sorted(r['mode'] for r in report['boss_cases']),completed=time.time());write_json(first/'blocked-variants.json',previous)
    updated={name:sha(ROOT/name) for name in proof};changes={name:{'before':proof[name],'after':value} for name,value in updated.items() if value!=proof[name]}
    allowed={'elk/batches/1-100/rounds.json',*{'elk/batches/1-100/traces/'+name+'.json' for name in expected}}
    # Path.relative_to serializes Windows paths using backslashes in existing proofs.
    if {Path(name).as_posix() for name in changes}!=allowed:raise ValueError('unexpected_prior_evidence_mutation')
    write_json(second/('prior-providers-proof-before-boss-'+campaign+'.json'),proof)
    write_json(second/('boss-proof-update-'+campaign+'.json'),{'reason':'User requested completion of the six previously pending Pirots 5 Boss cases. Other prior financial evidence is unchanged.','campaign':campaign,'changes':changes})
    write_json(second/'prior-providers-proof.json',updated)
    print(json.dumps({'published_boss_cases':6,'campaign':campaign,'updated_prior_evidence_files':len(changes)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('campaign');args=parser.parse_args();publish(args.campaign)
