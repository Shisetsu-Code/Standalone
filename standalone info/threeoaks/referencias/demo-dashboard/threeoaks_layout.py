"""Explicit, disjoint batches of the captured official 3 Oaks catalog."""
import json,os
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BATCHES={'1-100':(1,100),'101-103':(101,103)}

def batch_name(name=None):
    name=os.environ.get('THREEOAKS_BATCH','1-100') if name is None else name
    if name not in BATCHES:raise ValueError('unknown_threeoaks_batch')
    return name

def batch_folder(name=None):return ROOT/'threeoaks/batches'/batch_name(name)

def batch_games(name=None):
    first,last=BATCHES[batch_name(name)]
    catalog=json.loads((ROOT/'threeoaks/catalog.json').read_text(encoding='utf8'))
    games=[g for g in catalog if first<=g['ordinal']<=last]
    if [g['ordinal'] for g in games]!=list(range(first,last+1)):raise ValueError('incomplete_batch_catalog')
    return games

def catalog_matches(games,name=None):return games==batch_games(name)
