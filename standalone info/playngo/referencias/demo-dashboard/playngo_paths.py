"""Allowlisted disjoint Play'n GO batches, selected before importing runners."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BATCHES={'1-100':(0,100),'101-200':(100,200),'201-300':(200,300),'301-400':(300,400),'401-477':(400,477)}
def batch_path(batch='1-100'):
    if batch not in BATCHES:raise ValueError('unsupported_playngo_batch')
    return ROOT/'playngo/batches'/batch
def catalog_slice(batch='1-100'):
    batch_path(batch);start,end=BATCHES[batch]
    result=json.loads((ROOT/'playngo/catalog.json').read_text(encoding='utf8'))[start:end]
    if len(result)!=end-start:raise ValueError('incomplete_playngo_catalog_scope')
    return result
def selected_batch():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--batch',default=os.environ.get('PLAYNGO_BATCH','1-100'))
    options,_=parser.parse_known_args();batch=options.batch
    batch_path(batch);return batch
