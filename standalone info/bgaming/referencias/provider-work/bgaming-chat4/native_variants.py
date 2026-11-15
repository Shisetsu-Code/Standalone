"""Static extraction of explicit client-side slot variant settings. Never evals JavaScript."""
import re,json
from fractions import Fraction

def balanced(text,start,opening='{',closing='}'):
 depth=0;quote=None;escape=False
 for i in range(start,len(text)):
  c=text[i]
  if quote:
   if escape:escape=False
   elif c=='\\':escape=True
   elif c==quote:quote=None
   continue
  if c in ('"',"'",'`'):quote=c;continue
  if c==opening:depth+=1
  elif c==closing:
   depth-=1
   if depth==0:return text[start:i+1]
 raise ValueError('Unclosed static config')

def fields(obj):
 parts=[];depth=0;quote=None;escape=False;start=1
 for i,c in enumerate(obj[1:-1],1):
  if quote:
   if escape:escape=False
   elif c=='\\':escape=True
   elif c==quote:quote=None
  elif c in ('"',"'",'`'):quote=c
  elif c in '[{(':depth+=1
  elif c in ']})':depth-=1
  elif c==',' and depth==0:parts.append(obj[start:i]);start=i+1
 parts.append(obj[start:-1]);return dict(part.split(':',1) for part in parts if ':' in part)

def parse(source):
 assignment=re.search(r'\b([A-Za-z_$][\w$]*)\.mode=([A-Za-z_$][\w$]*)\.currentVariantId\.toString\(\)',source)
 if not assignment:raise ValueError('Native mode selector not recognized')
 model=re.escape(assignment[2]);conversion=r'\b[A-Za-z_$][\w$]*\.bet=[A-Za-z_$][\w$]*\.data\.bet/'+model+r'\.currentConfig\.base_bet\*[A-Za-z_$][\w$]*\[0\]\.base_bet'
 if not re.search(conversion,source):raise ValueError('Native variant request conversion not recognized')
 arrays=re.findall(r'"allOptions",([A-Za-z_$][\w$]*)\)',source)
 if len(set(arrays))!=1:raise ValueError('Variant array not unique')
 array=arrays[0];m=re.search(r'(?<![\w$])'+re.escape(array)+r'=\[([A-Za-z0-9_$,]+)\]',source)
 if not m:raise ValueError('Explicit variant array not recognized')
 identifiers=m[1].split(',');memo={}
 def config(name,trail=()):
  if name in memo:return dict(memo[name])
  if name in trail or len(trail)>20:raise ValueError('Config inheritance cycle/depth')
  pattern=r'(?<![\w$])'+re.escape(name)+r'=(?:([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*),)?\{'
  found=re.search(pattern,source)
  if not found:return {}
  obj=balanced(source,found.end()-1);f=fields(obj);result=config(found[2],trail+(name,)) if found[2] else {}
  for key in ('name','base_bet','bet_adding'):
   if key in f:
    try:result[key]=json.loads(f[key])
    except ValueError:raise ValueError('Nonliteral native variant '+key) from None
  if 'requestOptions' in f:
   ro=fields(f['requestOptions']);result['request_options']={}
   for key,value in ro.items():
    if key not in ('purchased_feature','purchased_feature_level','mode'):raise ValueError('Unmapped variant request field')
    result['request_options'][key]=json.loads(value)
  if 'buy_features' in f:
   value=f['buy_features'];result['buys']=[dict(name=n,price=p) for n,p in re.findall(r'name:"([A-Za-z0-9_]+)",price:(\d+(?:\.\d+)?)',value)]
   if 'features:[' in value and not result['buys']:raise ValueError('Unmapped native buy prices')
  memo[name]=dict(result);return result
 variants=[]
 for i,name in enumerate(identifiers):
  conf=config(name)
  if not isinstance(conf.get('base_bet'),(int,float)) or conf['base_bet']<=0 or 'name' not in conf:raise ValueError('Incomplete native variant '+name)
  conf['index']=i;conf['identifier']=name;variants.append(conf)
 return variants

def plan(initial,metadata):
 o=initial['options'];rawbet=min(o['available_bets']);variants=metadata['native_variants'];base=Fraction(str(variants[0]['base_bet']));disabled=o.get('feature_options',{}).get('disabled_features',[]);modes=[]
 for variant in variants:
  args=dict(variant.get('request_options',{}));feature=args.get('purchased_feature')
  if feature in disabled:continue
  args.setdefault('mode',str(variant['index']));args['bet']=rawbet;cost=Fraction(rawbet)*Fraction(str(variant['base_bet']))/base
  if cost.denominator!=1:raise ValueError('Fractional native mode stake')
  modes.append(dict(name=variant['name'],command='spin',options=args,cost_native=int(cost),native_variant=variant['index']))
  if feature:continue # Chance requestOptions replace a simultaneous buy; do not invent that combination.
  for buy in variant.get('buys',[]):
   if buy['name'] in disabled:continue
   price=cost*Fraction(buy['price'])
   if price.denominator!=1:raise ValueError('Fractional native purchase cost')
   options=dict(args,purchased_feature=buy['name']);modes.append(dict(name=variant['name']+'/'+buy['name'],command='spin',options=options,cost_native=int(price),native_variant=variant['index']))
 return modes
