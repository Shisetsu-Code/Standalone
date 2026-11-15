"""Explicit line-count wire values and separate native price factors from the official client."""
import re,hashlib
from native_variants import balanced
def metadata(source):
 methods=list(re.finditer(r'onLinesCountChanged\([^)]*\)\{',source));tables=set()
 for method in methods:
  body=balanced(source,method.end()-1)
  if 'this.additionalSpinOptions.mode=this.linesCount' in body:tables.update(re.findall(r'setBetsVisibleMultiplier\(([A-Za-z_$][\w$]*)\[[A-Za-z_$][\w$]*\],!0\)',body))
 if len(tables)!=1 or 'delete this.additionalSpinOptions.mode' in source:raise ValueError('Line selector/continuation lifecycle not proved')
 table=tables.pop();maps=set(re.findall(r'(?<![\w$])'+re.escape(table)+r'=\{((?:\d+:\d+)(?:,\d+:\d+)*)\}',source))
 if len(maps)!=1:raise ValueError('Line-count price map ambiguous')
 factors={k:int(v) for k,v in re.findall(r'(\d+):(\d+)',maps.pop())};arrays=re.findall(r'=\[((?:"\d+")(?:,"\d+")+)\]',source)
 candidates=[]
 for array in arrays:
  values=set(re.findall(r'"(\d+)"',array));extra=values-set(factors)
  if not set(factors)<=values:continue
  hidden=True
  for value in extra:
   pattern=r'name:"line-select-item-'+re.escape(value)+r'".{0,500}?\{c:"Button",p:\{([^{}]{0,600})\}'
   controls=re.findall(pattern,source)
   if not controls or any(not all(field in body for field in ['alpha:0','visible:!1','interactive:!1','onClick:"currentScene.selectItem`'+value+'"']) for body in controls):hidden=False;break
  if hidden:candidates.append(sorted(extra,key=int))
 if not factors or any(v<=0 for v in factors.values()) or not candidates:raise ValueError('String wire values do not match the explicit active line selector array')
 return dict(line_count_modes=factors,line_count_disabled_controls=min(candidates,key=len),line_count_source_sha256=hashlib.sha256(source.encode()).hexdigest(),line_count_evidence='onLinesCountChanged assigns the line-count string to additionalSpinOptions.mode and separately sets the visible/native bet factor from its explicit table. Source never deletes mode for continuations. Extra selector entries are excluded only when their matching UI buttons explicitly have alpha=0, visible=false and interactive=false.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];bet=min(o['available_bets'])
 if c.get('code')!='FUN' or c.get('subunits')!=100 or type(bet) is not int or bet<=0 or o.get('feature_options',{}).get('feature_multipliers'):raise ValueError('Unverified line-count currency/minimum or newly advertised purchase schema')
 return [dict(name='lines:'+value,command='spin',options={'bet':bet,'mode':value},cost_native=bet*factor,continuation_options={'mode':value},native_line_count_factor=factor) for value,factor in sorted(meta['line_count_modes'].items(),key=lambda x:int(x[0]))]
