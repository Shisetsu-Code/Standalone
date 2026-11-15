"""Explicit batch selection shared by the Endorphina workers and reports."""
import os
from pathlib import Path
import re
import json

ROOT=Path(__file__).resolve().parent/'endorphina'


def batch_id():
    value=os.environ.get('ENDORPHINA_BATCH','1-100')
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*',value):raise ValueError('invalid_endorphina_batch')
    start,end=map(int,value.split('-'))
    if end<start or end-start>=100:raise ValueError('invalid_endorphina_batch_range')
    return value


def batch_path():
    return ROOT/'batches'/batch_id()


def catalog_slice():
    start,end=map(int,batch_id().split('-'))
    full=json.loads((ROOT/'catalog.json').read_text(encoding='utf8'))
    rows=full[start-1:end]
    if len(rows)!=end-start+1 or len({r['id'] for r in rows})!=len(rows):raise ValueError('batch_catalog_incomplete_or_duplicate')
    return rows


def private_path():
    root=ROOT.parent.parent/'endorphina-private'/'rounds'
    return root if batch_id()=='1-100' else root/batch_id()


def unavailable_slugs():
    folder=batch_path()
    path=folder/'unavailable-evidence.json'
    if not path.exists():return set()
    result=set()
    for slug,proof in json.loads(path.read_text(encoding='utf8')).items():
        files=proof.get('source_files',[])
        if len(files)!=2 or len(set(files))!=2:continue
        outage=proof.get('reason')=='official_demo_temporarily_unavailable' and proof.get('http_status')==502
        if outage:
            checks=proof.get('checks',[])
            expected={'https://endorphina.com/'+lang+'/'+slug+'/play' for lang in ('es/juegos','games')}
            if len(checks)!=2 or {c.get('play_url') for c in checks}!=expected:continue
            if {c.get('source_file') for c in checks}!=set(files):continue
            if any(c.get('launcher_status')!=200 or c.get('demo_status')!=502 or c.get('demo_host')!='edemo.endorphina.com' for c in checks):continue
        elif proof.get('http_status')!=200:continue
        valid=True
        for name in files:
            target=(folder/name).resolve()
            if target.parent!=folder.resolve() or not target.is_file():valid=False;break
            source=target.read_text(encoding='utf8')
            if outage:
                if source.strip()!='The game is temporarily unavailable. Please try again later.':valid=False;break
            else:
                match=re.search(r"window.location.href\s*=\s*'([^']*)'",source)
                if not match or match[1]:valid=False;break
        if valid:result.add(slug)
    return result
