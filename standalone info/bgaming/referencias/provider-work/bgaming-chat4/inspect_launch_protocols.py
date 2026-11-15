"""Read static clients of initial HTTP-rejection cases; never calls init or gameplay."""
import json,re,urllib.request,urllib.error
from run_demo_qa import ROOT,PRIVATE,save,now
from legacy_metadata import load_client
GAMES=['BInvestLive','DragonsCrash','GiftX','SpaceXY','TopEagle','CatsLoveYummy','ChickenFire','MysticReels','RedHotChilliChickens','TripleNipple','AllLuckyClover']
if __name__=='__main__':
 results=[]
 for gid in GAMES:
  try:
   info,source=load_client(gid,urllib.request.build_opener());markers={k:len(list(re.finditer(re.escape(k),source))) for k in ['WebSocket','wss:','socket.io','command:"init"','command:"connect"','action:"init"','api_version']};info.update(game_id=gid,source_only=True,markers=markers);results.append(info);print(gid,markers,flush=True)
  except Exception as error:
   item=dict(game_id=gid,status='source_fetch_pending',error_type=type(error).__name__)
   if isinstance(error,urllib.error.HTTPError):item['http_status']=error.code
   results.append(item);print(gid,item,flush=True)
 save(ROOT/'initial-rejection-source-review.json',dict(reviewed_at=now(),new_launches=0,init_calls=0,gameplay_calls=0,results=results))
