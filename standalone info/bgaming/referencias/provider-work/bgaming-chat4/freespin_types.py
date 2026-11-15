"""Explicit official freespins_type selections, distinct from the paid purchase."""
import re,copy,hashlib
def metadata(source):
 assignments=re.findall(r'additionalSpinOptions\.freespins_type=([^,;]+)',source);types=[]
 if not assignments or 'delete this.additionalSpinOptions.freespins_type' not in source:raise ValueError('Free-spin type lifecycle not proved')
 for expression in assignments:
  ternary=re.fullmatch(r'3===this\.freespinsReelsCount\?([A-Za-z_$][\w$]*):([A-Za-z_$][\w$]*)',expression)
  variables=list(ternary.groups()) if ternary else [expression] if re.fullmatch(r'[A-Za-z_$][\w$]*',expression) else []
  if not variables:raise ValueError('Unknown free-spin type expression')
  for variable in variables:
   values=set(re.findall(r'(?<![\w$])'+re.escape(variable)+r'="([a-z_]+)"',source))
   if len(values)!=1:raise ValueError('Free-spin type literal not unique')
   value=values.pop()
   if value not in types:types.append(value)
 return dict(freespin_types=types,freespin_types_source_sha256=hashlib.sha256(source.encode()).hexdigest(),freespin_types_evidence='Exact additionalSpinOptions.freespins_type assignments and literal enum values, removed on beforeExitFreespins. Each paid free-spin purchase is tested separately for each source type.')
def expand(modes,meta):
 result=[]
 for mode in modes:
  types=meta['freespin_types'] if mode['options'].get('purchased_feature')=='freespin_buy' else meta['freespin_types'][:1]
  for value in types:
   m=copy.deepcopy(mode);m['freespin_options']={'freespins_type':value}
   if mode['options'].get('purchased_feature')=='freespin_buy':m['name']+='/type:'+value
   result.append(m)
 return result
