"""Cache public source of non-slot protocols. Static GETs only, no gameplay."""
import json,urllib.request,re,hashlib
from run_demo_qa import ROOT,PRIVATE,save,now
from legacy_metadata import load_client
if __name__=='__main__':
 review=json.loads((ROOT/'remaining-review.json').read_text(encoding='utf8'));results=[];op=urllib.request.build_opener()
 classic=PRIVATE/'research/classic/casino.min.js';shared=classic.read_text(encoding='utf8') if classic.exists() else ''
 for entry in review['games']:
  if entry['category'] not in ['native_protocol_without_available_bets','roulette_misclassified_as_baccarat','open_gamble_choice','optional_card_gamble_pending','manual_choice_pending']:continue
  gid=entry['game_id']
  try:info,source=load_client(gid,op);item=dict(game_id=gid,status='cached_client',**info)
  except Exception as error:
   if 'My.games.'+gid+'=' in shared or 'My.games.'+gid+' =' in shared:item=dict(game_id=gid,status='classic_registration_only',source_url='https://cdn.bgaming-network.com/html/casino.min.js',source_sha256=hashlib.sha256(shared.encode()).hexdigest(),fresh_launch_must_confirm=True)
   else:item=dict(game_id=gid,status='source_route_pending',error_type=type(error).__name__)
  results.append(item);print(gid,item['status'],flush=True)
 save(ROOT/'native-client-preparation.json',dict(prepared_at=now(),gameplay_calls=0,new_game_launches=0,results=results))
