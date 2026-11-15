"""Numeric row selectors with the official indexed native minimum, not a guessed global minimum."""
import re,hashlib,copy
def metadata(source):
 if 'this.additionalSpinOptions.rows=this.reelSize' not in source:raise ValueError('Numeric rows wire not proved')
 minimum=set(re.findall(r'initialAvailableBets\[this\.reelSize-([A-Za-z_$][\w$]*)\]',source));maximum=set(re.findall(r'this\.reelSize=([A-Za-z_$][\w$]*)[,;]',source));table=re.search(r'changeReelsSize\([^)]*\)\{var [A-Za-z_$][\w$]*=([A-Za-z_$][\w$]*)\[this\.reelSize\]',source)
 if len(minimum)!=1 or len(maximum)!=1 or not table:raise ValueError('Indexed row bounds/table not explicit')
 def constant(name):
  values=set(re.findall(r'(?<![\w$])'+re.escape(name)+r'=(\d+)(?![\w$])',source))
  if len(values)!=1:raise ValueError('Indexed row constant not unique')
  return int(values.pop())
 low=constant(minimum.pop());high=constant(maximum.pop());maps=set(re.findall(r'(?<![\w$])'+re.escape(table[1])+r'=\{((?:\d+:\d+)(?:,\d+:\d+)*)\}',source))
 if len(maps)!=1:raise ValueError('Indexed row table ambiguous')
 values=sorted(int(k) for k,v in re.findall(r'(\d+):(\d+)',maps.pop()))
 if values!=list(range(low,high+1)):raise ValueError('Indexed row bounds disagree with explicit table')
 return dict(indexed_rows=dict(values=values,minimum_index_base=low,wire_type='integer'),indexed_rows_source_sha256=hashlib.sha256(source.encode()).hexdigest(),indexed_rows_evidence='Numeric additionalSpinOptions.rows; explicit row table/bounds; setBetsCustomLimits chooses initialAvailableBets[reelSize-minimum]. Native bet itself is sent, with no display scaling.')
def plan(initial,meta):
 from run_demo_qa import modes_from_init
 spec=meta['indexed_rows'];bets=initial['options']['available_bets'];result=[];plain=dict(meta);plain.pop('indexed_rows')
 for row in spec['values']:
  index=row-spec['minimum_index_base']
  if index<0 or index>=len(bets) or type(bets[index]) is not int or bets[index]<=0:raise ValueError('Native indexed row minimum missing')
  local=copy.deepcopy(initial);local['options']['available_bets']=[bets[index]]
  for mode in modes_from_init(local,plain):
   mode['name']+='@rows:'+str(row);mode['options']['rows']=row;mode['continuation_options']={'rows':row};result.append(mode)
 return result
