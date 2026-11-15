"""Read cached official source and sanitized captures, without launching or wagering."""
import json,re,urllib.request,sys
from pathlib import Path
from legacy_metadata import load_client
if __name__=='__main__':
 for gid in sys.argv[1:]:
  r=json.loads((Path(__file__).parent/'live'/(gid+'.json')).read_text(encoding='utf8'))
  initial=r['events'][0]['response'];o=initial.get('options',{})
  print('GAME',gid,'INIT',json.dumps({**{k:v for k,v in initial.items() if k not in ['options','bet_to_recipe_batch_state','bet_to_multiplier_batch_state']},'options':{k:v for k,v in o.items() if k not in ['reels','screen','paytable','paytables','lines','special_symbols']}},ensure_ascii=False))
  info,source=load_client(gid,urllib.request.build_opener());print('SOURCE',info)
  for term in ['onLinesCountChanged','setSpinOptions','additionalPlayData','playCommand','purchased_feature_level=','setBoughtBonusParameter(','beforePlay','freespin_buy_miltipliers','spinOptions','bonus_buy_0','bet_to_multiplier_batch_state']:
   hits=list(re.finditer(re.escape(term),source));print('TERM',term,'HITS',len(hits))
   for m in hits[-5:]:print(source[max(0,m.start()-100):m.end()+300])
