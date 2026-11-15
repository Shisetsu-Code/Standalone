"""Allowlisted, disjoint ELK catalog batches."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BATCHES={'1-100':(0,100),'101-159':(100,159)}
def batch_path(batch='1-100'):
    if batch not in BATCHES:raise ValueError('unsupported_elk_batch')
    return ROOT/'elk/batches'/batch
def catalog_slice(batch='1-100'):
    batch_path(batch);start,end=BATCHES[batch]
    catalog=json.loads((ROOT/'elk/catalog.json').read_text(encoding='utf8'))
    selected=catalog[start:end]
    if len(selected)!=end-start:raise ValueError('catalog_scope_incomplete')
    return selected
