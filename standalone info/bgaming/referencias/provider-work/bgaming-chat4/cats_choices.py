"""Source-proved Cats Soup bonus picks. Never repeat an already opened native index."""
import re,hashlib
from native_variants import balanced,fields
def metadata(source):
 if not re.search(r'var ([A-Za-z_$][\w$]*)=[A-Za-z_$][\w$]*\.parent\.parent\.children\.indexOf\([A-Za-z_$][\w$]*\.parent\)',source) or '{command:"play_bonus",options:{index:i}}' not in source:raise ValueError('Cats bonus index envelope not proved')
 counts=[]
 for match in re.finditer(r'\{c:"MovieClip",p:\{name:"bottles"',source):
  obj=balanced(source,match.start());raw=fields(obj).get('"','')
  if not raw.startswith('\":['):continue
  array=raw[2:];children=[];index=1
  while index<len(array)-1:
   if array[index] in ', ':index+=1;continue
   if array[index]!='{':raise ValueError('Nonliteral bottle children')
   child=balanced(array,index);children.append(child);index+=len(child)
  if children and all(c.startswith('{c:"MovieClip"') for c in children):counts.append(len(children))
 if counts!=[6]:raise ValueError('Six selectable native bottle positions not proved')
 return dict(cats_bottle_count=6,cats_choice_source_sha256=hashlib.sha256(source.encode()).hexdigest(),cats_choice_evidence='Bonus popup has six direct MovieClip bottle children; handler sends its zero-based parent child index in play_bonus.options.index. Policy selects the lowest unopened index; no claim of all random choice sequences.')
def next_choice(response,meta):
 f=response.get('flow',{})
 if f.get('state')!='play_bonus' or set(f.get('available_actions',[]))-{'init'}!={'play_bonus'}:raise ValueError('Cats choice not currently available')
 all_prizes=response['features']['bonus_data']['prizes_data']['all'];used=[p['index'] for p in all_prizes];count=meta['cats_bottle_count']
 if type(count) is not int or count!=6 or any(type(i) is not int or not 0<=i<count for i in used) or len(set(used))!=len(used):raise ValueError('Native opened bottle indices invalid')
 index=next((i for i in range(count) if i not in used),None)
 if index is None:raise ValueError('No unopened bottle remains; do not repeat')
 return {'index':index}
