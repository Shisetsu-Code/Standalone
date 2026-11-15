"""Verify fresh loader versions/original hashes before static RPC source derivation."""
import re,json,hashlib
from urllib.parse import urlsplit
from run_demo_qa import ROOT
from hyperhive_adapter import native_script_entries
def valid_route(route):
 if not isinstance(route,str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:js|json)',route) or '..' in route.split('/') or '//' in route:raise ValueError('Invalid pinned static route')
 return route
def strings(value):
 if isinstance(value,str):yield value
 elif isinstance(value,list):
  for entry in value:yield from strings(entry)
 elif isinstance(value,dict):
  for entry in value.values():yield from strings(entry)
def load_pinned_sources(frontend,fetch,proof):
 if re.search(r'<base\b',frontend,re.I):raise ValueError('Fresh frontend changes script base resolution')
 guard=proof['fresh_version_guard'];entries={urlsplit(s).path.lstrip('./') for s in native_script_entries(frontend)}
 expected=guard.get('html_scripts',[guard['html_script']] if 'html_script' in guard else [])
 if not expected or any(s.lstrip('./') not in entries for s in expected):raise ValueError('Fresh frontend version differs from prepared source')
 pins=proof['fresh_source_pins']
 if not pins or len({p['route'] for p in pins})!=len(pins):raise ValueError('Pinned static routes missing/duplicated')
 for pin in pins:
  valid_route(pin['route'])
  if not re.fullmatch('[a-f0-9]{64}',pin['original_sha256']):raise ValueError('Invalid original source digest')
 selected=proof.get('metadata_source_routes',[p['route'] for p in pins])
 if not selected or len(set(selected))!=len(selected) or not set(selected)<=set(p['route'] for p in pins):raise ValueError('Invalid metadata source selection')
 # This loader executes no JS: accept only the pinned literal defaults and
 # reject any HTML override capable of selecting a different asset version.
 if guard.get('loader_default_resource_version'):
  if re.search(r'\bSKIN_DIRS\b|(?:\.|\[\s*[\"\x27])(?:resources_path|game_bundle_source)[\"\x27]?\]?\s*=',frontend):raise ValueError('Dynamic HTML resource override unsupported')
  for key,expected_value in [('resources_path',guard['html_resources_path']),('game_bundle_source',guard['html_game_bundle_source'])]:
   matches=re.findall(r'\b'+key+r'\s*:\s*([\"\x27])([^\"\x27]*)\1',frontend)
   if len(matches)!=1 or matches[0][1]!=expected_value:raise ValueError('Fresh loader literal resource selection changed')
  if guard['html_resources_path']!='.' or guard['html_game_bundle_source']!='bundle.js':raise ValueError('Unsupported prepared loader base')
  resolved='/'+guard['loader_default_resource_version']+'/bundle.js'
  if valid_route(resolved)!=guard['resolved_bundle_route'] or resolved not in selected:raise ValueError('Prepared dynamic bundle route mismatch')
 checks=[]
 manifests=[]
 if guard.get('manifest_routes'):
  routes=guard['manifest_routes'];targets=[guard['project_jsList'],guard['load_list_script']]
  if len(routes)!=2:raise ValueError('Unsupported prepared manifest set')
  manifests.extend((route,target,key) for route,target,key in zip(routes,targets,['jsList','scripts']))
 if guard.get('project_manifest'):manifests.append((guard['project_manifest'],guard['project_jsList'],'jsList'))
 if guard.get('library_manifest'):manifests.append((guard['library_manifest'],guard['library_script'],'scripts'))
 if guard.get('slot_parameters_manifest'):manifests.append((guard['slot_parameters_manifest'],guard['bets_data'],'bg_gaming.bets_data'))
 for route,_,_ in manifests:valid_route(route)
 for route,target,key in manifests:
  raw=fetch(valid_route(route));data=json.loads(raw)
  value=data.get('bg_gaming',{}).get('bets_data') if key=='bg_gaming.bets_data' else data.get(key)
  if (value!=target if key=='bg_gaming.bets_data' else not isinstance(value,list) or target not in value):raise ValueError('Fresh static manifest no longer selects prepared source')
  checks.append(dict(route=route,original_sha256=hashlib.sha256(raw).hexdigest(),manifest_selection=target))
 sources={}
 for index,pin in enumerate(pins):
  raw=fetch(pin['route']);digest=hashlib.sha256(raw).hexdigest()
  if digest!=pin['original_sha256']:raise ValueError('Fresh official source hash changed; no wager allowed')
  source=raw.decode('utf8')
  if index==0 and guard.get('entry_source_literal') and guard['entry_source_literal'] not in source:raise ValueError('Entry dependency reference changed')
  if pin['route']=='/loader.js' and guard.get('loader_default_resource_version'):
   if 'res:n="'+guard['loader_default_resource_version']+'"' not in source or 'e.game_bundle_source=e.resources_path+"/bundle.js"' not in source:raise ValueError('Pinned loader no longer uses prepared default bundle resolution')
  item=dict(route=pin['route'],original_sha256=digest)
  if pin.get('derive'):
   if pin['derive']!='rpc_extra.decode_static_strings(original_utf8)':raise ValueError('Unrecognized static derivation')
   from rpc_extra import decode_static_strings
   source=decode_static_strings(source);derived=hashlib.sha256(source.encode()).hexdigest()
   if derived!=pin['derived_sha256']:raise ValueError('Static decoder output differs from prepared proof')
   item['derived_sha256']=derived
  checks.append(item);sources[pin['route']]=source
 return '\n'.join(sources[route] for route in selected),checks
def load_metadata(gid,frontend,fetch,allowed):
 if gid not in ['Robospin','KeepersOfTheSecret7rst','GrandPatron7rst','BigBucksSaloon','ClashofGodsAnubisvsHades','AztecsClawWildDice']:raise ValueError('Unverified pinned-source game')
 proof=json.loads((ROOT/'protocols'/(gid+'.rpc-extra-prepared.json')).read_text(encoding='utf8'))
 if proof['game_id']!=gid:raise ValueError('Prepared source game identity mismatch')
 source,checks=load_pinned_sources(frontend,fetch,proof)
 from rpc_extra import metadata
 meta=metadata(source,allowed)
 if meta['source_sha256']!=proof['metadata']['source_sha256'] or meta['family']!=proof['metadata']['family']:raise ValueError('Fresh metadata source differs from prepared proof')
 meta['fresh_source_verification']=checks;return meta
