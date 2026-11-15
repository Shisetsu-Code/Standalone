"""Alice Wonder Luck source-backed collect/gamble and automatic/manual card choices."""
import re,hashlib,copy
from native_variants import balanced
def metadata(source):
 required=['{command:"gamble_bonus",options:{}}','this.requestCardsPick({mode:"select_pick_cards"})','this.requestCardsPick({mode:"auto"})','this.requestCardsPick({mode:"any",index:','get index(){return this.parent.parent.children.indexOf(this.parent)}']
 if not all(x in source for x in required):raise ValueError('Alice choice request contract not recognized')
 starts=[m.start() for m in re.finditer(r'\{c:"MovieClip",p:\{name:"cards-list"',source)]
 if len(starts)!=1:raise ValueError('Card container not unique')
 obj=balanced(source,starts[0]);references=obj.count('prefabName:"slot-animations/popup/pick-feature-card"');images=re.findall(r'image:"popups/features-to-pick/card-(?:green|red)-\d+\.png"',obj)
 if references!=len(images) or not 1<references<=64:raise ValueError('Card positions not proved')
 return dict(alice_choices_verified=True,card_count=references,card_index_min=0,card_index_max=references-1,source_sha256=hashlib.sha256(source.encode()).hexdigest(),choice_requests=dict(collect={'command':'pick_cards','options':{'mode':'select_pick_cards'}},gamble={'command':'gamble_bonus','options':{}},auto={'command':'pick_cards','options':{'mode':'auto'}},manual={'command':'pick_cards','options_fields':['mode=any','index']}),scope='Collect and one gamble; auto picks and deterministic manual low/high boundary strategies. Not every permutation or repeated-gamble sequence.')
def expand(modes,meta):
 result=[]
 for base in modes:
  if base['options'].get('purchased_feature')!='freespin_buy':result.append(base);continue
  for gamble,card in [('collect','auto'),('collect','manual_low'),('collect','manual_high'),('gamble_once','auto'),('gamble_once','manual_low')]:
   mode=copy.deepcopy(base);mode.update(name=base['name']+'/'+gamble+'/'+card,alice_gamble_policy=gamble,alice_card_policy=card);result.append(mode)
 return result
def next_action(response,mode,progress,meta):
 state=response['flow']['state'];allowed=response['flow']['available_actions']
 if state=='gamble_bonus':
  if mode.get('alice_gamble_policy')=='gamble_once' and not progress.get('gambled'):
   q={'command':'gamble_bonus','options':{}};progress['gambled']=True
  else:q={'command':'pick_cards','options':{'mode':'select_pick_cards'}}
 elif state=='pick_cards':
  policy=mode.get('alice_card_policy','auto')
  if policy=='auto':q={'command':'pick_cards','options':{'mode':'auto'}}
  elif policy in ('manual_low','manual_high'):
   used=progress.setdefault('used_indices',[]);candidates=[i for i in range(meta['card_count']) if i not in used]
   if not candidates:raise RuntimeError('No unused source-verified card remains')
   index=candidates[-1] if policy=='manual_high' else candidates[0];used.append(index);q={'command':'pick_cards','options':{'mode':'any','index':index}}
  else:raise RuntimeError('Unknown card policy')
 else:raise RuntimeError('Unknown Alice choice state')
 if q['command'] not in allowed:raise RuntimeError('Alice command not currently allowed')
 return q
