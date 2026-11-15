import unittest,hashlib,json
from pathlib import Path
from rpc_source_pins import load_pinned_sources,load_metadata
class SourcePins(unittest.TestCase):
 def proof(self):
  raw=b'const a="./classes-hash.js";';return raw,{'fresh_version_guard':{'html_script':'/assets/index-hash.js','entry_source_literal':'./classes-hash.js'},'fresh_source_pins':[{'route':'/assets/index-hash.js','original_sha256':hashlib.sha256(raw).hexdigest()}]}
 def test_only_pinned_fresh_sources_are_accepted(self):
  raw,p=self.proof();source,refs=load_pinned_sources('<script src="/assets/index-hash.js"></script>',lambda route:raw,p);self.assertEqual(source,raw.decode());self.assertEqual(refs[0]['route'],'/assets/index-hash.js')
  with self.assertRaises(ValueError):load_pinned_sources('<script src="/assets/index-hash.js"></script>',lambda route:b'changed',p)
  with self.assertRaises(ValueError):load_pinned_sources('<script src="/assets/other.js"></script>',lambda route:raw,p)
 def test_untrusted_pin_cannot_fetch_external_or_traversal(self):
  raw,p=self.proof();p['fresh_source_pins'][0]['route']='https://other.example/main.js'
  with self.assertRaises(ValueError):load_pinned_sources('<script src="/assets/index-hash.js"></script>',lambda route:self.fail('Must not fetch'),p)
 def test_all_six_prepared_games_reproduce_from_cached_original_bytes(self):
  root=Path(__file__).resolve().parent;private=root.parents[1]/'bgaming-private-chat4/research/frontends'
  for gid in ['Robospin','KeepersOfTheSecret7rst','GrandPatron7rst','BigBucksSaloon','ClashofGodsAnubisvsHades','AztecsClawWildDice']:
   with self.subTest(gid=gid):
    proof=json.loads((root/'protocols'/f'{gid}.rpc-extra-prepared.json').read_text(encoding='utf8'));directory=private/gid
    raw_by_route={pin['route']:(directory/pin['original_cache_file']).read_bytes() for pin in proof['fresh_source_pins']}
    for route in proof['fresh_version_guard'].get('manifest_routes',[]):
     raw_by_route[route]=next(directory.glob('rpc-extra-*-'+route.rsplit('/',1)[-1])).read_bytes()
    for field in ('project_manifest','library_manifest','slot_parameters_manifest'):
     route=proof['fresh_version_guard'].get(field)
     if route:raw_by_route[route]=next(directory.glob('rpc-extra-*-'+route.rsplit('/',1)[-1])).read_bytes()
    calls=[]
    def fetch(route):calls.append(route);return raw_by_route[route]
    initial=json.loads((root/'live'/f'{gid}.json').read_text(encoding='utf8'))['events'][0]['response']
    meta=load_metadata(gid,(directory/'index.html').read_text(encoding='utf8'),fetch,initial['result']['config']['purchased_features'])
    self.assertEqual(meta['family'],proof['metadata']['family'])
    self.assertEqual(meta['products'],proof['metadata']['products'])
    self.assertEqual(meta['source_sha256'],proof['metadata']['source_sha256'])
    self.assertTrue(meta['fresh_source_verification'])
    self.assertEqual(set(calls),set(raw_by_route))
 def test_big_bucks_overrides_are_rejected_before_fetch(self):
  root=Path(__file__).resolve().parent;private=root.parents[1]/'bgaming-private-chat4/research/frontends/BigBucksSaloon'
  proof=json.loads((root/'protocols/BigBucksSaloon.rpc-extra-prepared.json').read_text(encoding='utf8'));html=(private/'index.html').read_text(encoding='utf8')
  for changed in [html.replace("resources_path: '.'","resources_path: '/changed'"),html+'<script>window.SKIN_DIRS={basic:{res:"other"}};</script>',html+'<base href="https://other.example/">']:
   with self.assertRaises(ValueError):load_pinned_sources(changed,lambda route:self.fail('Must reject changed loader selection before fetch'),proof)
 def test_metadata_source_order_is_explicit(self):
  raw,p=self.proof();other=b'second';p['fresh_source_pins'].append({'route':'/other.js','original_sha256':hashlib.sha256(other).hexdigest()});p['metadata_source_routes']=['/other.js','/assets/index-hash.js']
  source,_=load_pinned_sources('<script src="/assets/index-hash.js"></script>',lambda route:raw if route.startswith('/assets/') else other,p)
  self.assertEqual(source,'second\n'+raw.decode())
