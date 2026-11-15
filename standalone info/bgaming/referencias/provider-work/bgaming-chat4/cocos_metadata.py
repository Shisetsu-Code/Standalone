"""Read Cocos JSON assets and game-specific RequestBuilder metadata; no wagers."""
import json,re,hashlib
from fractions import Fraction

def decode_uuid(value):
 if re.fullmatch(r'[0-9a-fA-F-]{36}',value):return value
 if len(value)!=22 or not re.fullmatch(r'[0-9a-fA-F]{2}[A-Za-z0-9+/]{20}',value):raise ValueError('Unrecognized Cocos UUID encoding')
 alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
 raw=value[:2]+''.join(format(alphabet.index(value[i])*64+alphabet.index(value[i+1]),'03x') for i in range(2,22,2))
 return raw[:8]+'-'+raw[8:12]+'-'+raw[12:16]+'-'+raw[16:20]+'-'+raw[20:]

def asset_route(manifest,bundle,key):
 matches=[(int(i),v) for i,v in manifest['paths'].items() if v[0]==key]
 if len(matches)!=1:raise ValueError('Cocos config asset mapping not unique')
 index=matches[0][0];uid=decode_uuid(manifest['uuids'][index]);import_base=manifest['importBase']
 if not re.fullmatch('[A-Za-z0-9_-]+',import_base):raise ValueError('Unexpected Cocos importBase')
 if any(index in members for members in manifest.get('packs',{}).values()):raise ValueError('Packed Cocos config requires separate decoding')
 versions=manifest.get('versions',{}).get('import',[]);suffix=''
 for i in range(0,len(versions),2):
  if versions[i]==index:
   version=str(versions[i+1])
   if not re.fullmatch('[A-Za-z0-9_-]+',version):raise ValueError('Invalid Cocos version suffix')
   suffix='.'+version
 return '/assets/'+bundle+'/'+import_base+'/'+uid[:2]+'/'+uid+suffix+'.json'

def extract_config(asset):
 found=[]
 def scan(v):
  if isinstance(v,dict):
   if isinstance(v.get('features'),list) and all(isinstance(x,dict) and 'id' in x and 'priceMultiplier' in x for x in v['features']):found.append(v)
   for x in v.values():scan(x)
  elif isinstance(v,list):
   for x in v:scan(x)
 scan(asset)
 if len(found)!=1:raise ValueError('Cocos base config not uniquely recognized')
 return found[0]

def merge(base,override):
 result=dict(base)
 for k,v in override.items():result[k]=merge(result[k],v) if isinstance(v,dict) and isinstance(result.get(k),dict) else v
 return result

def load_metadata(fetch,source=None):
 if source is None:source=fetch('/assets/main/index.js').decode('utf8')
 if 'RequestBuilder' not in source or 'buildBuyBonusRequest' not in source or 'custom_field:{fid:' not in source:raise ValueError('Cocos RequestBuilder schema not recognized')
 manifest_raw=fetch('/assets/config-base/config.json');manifest=json.loads(manifest_raw);route=asset_route(manifest,'config-base','base.config');base_raw=fetch(route);base=extract_config(json.loads(base_raw));effective=base;proof=[dict(route='/assets/config-base/config.json',sha256=hashlib.sha256(manifest_raw).hexdigest()),dict(route=route,sha256=hashlib.sha256(base_raw).hexdigest())];unresolved=[]
 # Actual production initializer calls loadConfig("prod"); the client merges this over base.
 if '.loadConfig("prod")' in source:
  try:
   prod_manifest_raw=fetch('/assets/config-prod/config.json');prod_manifest=json.loads(prod_manifest_raw);prod_route=asset_route(prod_manifest,'config-prod','prod.config');prod_raw=fetch(prod_route);asset=json.loads(prod_raw)
   # JsonAsset data may be wrapped in a serialized array. Production overrides are identified by its JsonAsset name.
   candidates=[]
   def find(v):
    if isinstance(v,dict):
     if any(k in v for k in ['api','project','features','logger','env']):candidates.append(v)
     for x in v.values():find(x)
    elif isinstance(v,list):
     for x in v:find(x)
   find(asset)
   if candidates:effective=merge(base,candidates[0])
   proof.extend([dict(route='/assets/config-prod/config.json',sha256=hashlib.sha256(prod_manifest_raw).hexdigest()),dict(route=prod_route,sha256=hashlib.sha256(prod_raw).hexdigest())])
  except ValueError as e:unresolved.append('Production config decoding: '+str(e))
 aliases=re.search(r'"BUY_BONUS_PRODUCT_PURCHASED_FEATURES",\{([^}]+)\}',source)
 ids=re.search(r'"BUY_BONUS_PRODUCT_FEATURE_IDS",\{([^}]+)\}',source)
 if not aliases or not ids:raise ValueError('Cocos product mappings not found')
 purchased=dict(re.findall(r'(\w+):"([^\"]+)"',aliases[1]));feature_ids=dict(re.findall(r'(\w+):"([^\"]+)"',ids[1]));chance=re.search(r'"CHANCE_FEATURE_ID","([^\"]+)"',source)
 if chance:feature_ids['chance_x2']=chance[1]
 bids={product:int(bid) for product,bid in re.findall(r'(\w+):\{bid:(\d+),purchasedFeature:',source)}
 chance_bid=re.search(r'\{(\d+):[A-Za-z_$][\w$]*\.chance_x2\}',source)
 if chance_bid:bids['chance_x2']=int(chance_bid[1])
 products=[]
 for feature in effective['features']:
  product=next((p for p,f in feature_ids.items() if f==feature['id']),None)
  if product is None or product not in bids or product not in purchased:unresolved.append('Product mapping: '+feature['id']);continue
  products.append(dict(name=product,feature_id=feature['id'],kind=feature['type'],bid=bids[product],purchased_feature=purchased[product],factor=str(feature['priceMultiplier'])))
 symbols=re.search(r'"BoardSymbol",\{([^}]+)\}',source)
 board={k:int(v) for k,v in re.findall(r'(\w+):(\d+)',symbols[1])} if symbols else {}
 choices={'collect':'no','gamble':'yes'} if 'fid:{a:"collect"===' in source and '?"no":"yes"' in source else {}
 return dict(protocol='jsonrpc-cocos',engine='cocos',products=products,unresolved=unresolved,game_project=effective.get('project'),source_sha256=hashlib.sha256(source.encode()).hexdigest(),config_sources=proof,board_symbols=board,normal_req_fields=['bet','bet_type','bid'],bonus_req_fields=['bet','bet_type','bid','custom_field.fid.x','custom_field.fid.y'],gamble_req_values=choices,init_req={},price_rule='Client Math.round(base bet * priceMultiplier); round.bet.tb is the base bet, not the full feature debit. Validate full price against wallet at round closure.')
