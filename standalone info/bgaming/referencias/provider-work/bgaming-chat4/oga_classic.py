"""Source-derived older OGA action/stake request envelopes; no JavaScript execution."""
import re,hashlib,json
from native_variants import balanced,fields
def continuation_contracts(source):
 contracts={}
 expression=r'\.AdditionalData\.request=([A-Za-z_$][\w$]*)\.(FREESPIN_RESPIN|JACKPOT_RESPIN|FREESPIN_JACKPOT|FREESPIN_JACKPOT_RESPIN),[A-Za-z_$][\w$]*\.AdditionalData\.params\.action=\1\.\2'
 for enum,member in re.findall(expression,source):
  aliases={enum}|set(re.findall(r'([A-Za-z_$][\w$]*)='+re.escape(enum)+r'\|\|',source));values=set()
  for alias in aliases:values.update(re.findall(re.escape(alias)+r'\.'+member+r'="([a-z_]+)"',source))
  if len(values)!=1:raise ValueError('Combined OGA continuation enum not unique')
  action=values.pop();contracts[action]={'action':action}
 return contracts
def parse(definitions,source,integration,client):
 if 'params.req.custom_req=' not in client or 'formattedRequest.params.action=' not in client:raise ValueError('Classic OGA envelope source not recognized')
 expression=r'\.Regular\](?:=|:)\{ActionType:[^{}]*AdditionalData:\{[^{}]*params:\{([^}]+)\}'
 map_source=source;matches=list(re.finditer(expression,map_source))
 if not matches:map_source=integration;matches=list(re.finditer(expression,map_source))
 if not matches:raise ValueError('Classic OGA normal request map not found')
 match=matches[-1];block=match[1];params={};native_fields=fields(balanced(map_source,match.start(1)-1))
 # Only observed literal fields and the official consecutive line-number construction are decoded.
 for key,value in re.findall(r'(\w+):(![01]|\[\]|true|false|\d+)(?=,|$)',block):
  params[key]=True if value in ('!0','true') else False if value in ('!1','false') else [] if value=='[]' else int(value)
 for key,value in re.findall(r'(\w+):(\[(?:\d+(?:,\d+)*)?\])',block):params[key]=json.loads(value)
 lines=re.search(r'selectedWinLines:Array\.from\(\{length:(\d+)',block)
 if lines:
  params.pop('length',None) # Array.from's allocation length belongs to the client, not to custom_req.
  params['selectedWinLines']=list(range(int(lines[1])))
 # The regex above ends at the inner Array.from brace; recover the remaining flags from its immediate source span.
 if lines:
  pos=source.find(block);tail=source[pos:pos+400]
  for key,value in re.findall(r'(perLine|isNormalBuy|isSuperBuy):(![01])',tail):params[key]=value=='!0'
 for key,value in native_fields.items():
  if key not in params:
   if value in ('!0','!1'):params[key]=value=='!0';continue
   try:params[key]=json.loads(value)
   except ValueError:raise ValueError('Unrecognized classic OGA request field '+key) from None
 if set(params)-set(native_fields):raise ValueError('Nested client-only field leaked into OGA params')
 if not params:raise ValueError('Classic OGA request map not decoded')
 d=definitions['engine']['definition'];variants=[];unresolved=[]
 mapped=[]
 for key,flag in [('normalBuyCost','isNormalBuy'),('superBuyCost','isSuperBuy'),('featureBuyMulFreespin','isFeatureBuyFreeSpin'),('featureBuyMulRespin','isFeatureBuyRespin')]:
  if key in d:
   assignment=('.params.'+flag+'=!0') in source or bool(re.search(r'\.params\.'+re.escape(flag)+r'="(?:FreeSpin|Respin)"===',source))
   if flag not in params or not assignment:unresolved.append('Buy variant '+key)
   else:
    p=dict(params);p[flag]=True;variants.append(dict(name=key,feature='buy_bonus',factor=str(d[key]),custom_params=p));mapped.append(key)
 # Other price schemes require their own observed flag mappings.
 for key in d:
  if re.search(r'buy|ante|purchase',key,re.I) and not key.lower().endswith('rtp') and key not in mapped and isinstance(d[key],(int,float)) and d[key]>1:unresolved.append('Unmapped price '+key)
 return dict(engine='oga-classic',classic_continuations=continuation_contracts(source),send_custom_stake='formattedRequest.params.stake=' in client,normal_custom_params=params,variants=variants,features={},choices={},unresolved=unresolved,non_monetary_rtp_fields={k:v for k,v in d.items() if k.lower().endswith('rtp')},client_sha256=hashlib.sha256(client.encode()).hexdigest(),integration_sha256=hashlib.sha256(integration.encode()).hexdigest(),source_sha256=hashlib.sha256(source.encode()).hexdigest(),definitions_game_version=d.get('gameVersion'))

def customize(metadata,mode,bet,action,first):
 if action not in ('spin','freespin','respin','jackpot','bonus','cascade','cascadefg','extra_bet_hold') and action not in metadata.get('classic_continuations',{}):raise RuntimeError('Unknown classic OGA action')
 params=dict(mode.get('custom_params',metadata['normal_custom_params'])) if first else dict(metadata.get('classic_continuations',{}).get(action,{}))
 params.update(action=action,exponent=2)
 if action=='spin' and metadata.get('send_custom_stake'):params['stake']=bet
 return params
