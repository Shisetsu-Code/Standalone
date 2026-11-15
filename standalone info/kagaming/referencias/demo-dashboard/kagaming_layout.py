"""Explicit isolated KA campaign folders; catalogue ordinals never change."""
import json,os
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BATCHES=('1-100','101-200')

def batch_name(name=None):
    name=os.environ.get('KAGAMING_BATCH','1-100') if name is None else name
    if name not in BATCHES:raise ValueError('unauthorized_kagaming_batch')
    return name

def batch_folder(name=None,root=ROOT):
    return Path(root)/'kagaming/batches'/batch_name(name)

def scope_policy(folder=None):
    folder=batch_folder() if folder is None else Path(folder)
    path=folder/'scope.json'
    if not path.exists():path=ROOT/'kagaming/scope.json'
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}

def is_excluded(game,policy):
    included=policy.get('included_game_types')
    return (included is not None and game.get('gameType') not in included) or game.get('gameType') in policy.get('excluded_game_types',[])

def batch_games(name=None):
    start,end=map(int,batch_name(name).split('-'))
    catalog=json.loads((ROOT/'kagaming/catalog.json').read_text(encoding='utf8'))
    games=catalog[start-1:end]
    if len(games)!=end-start+1 or [g['ordinal'] for g in games]!=list(range(start,end+1)):raise ValueError('kagaming_catalog_slice_mismatch')
    return games
