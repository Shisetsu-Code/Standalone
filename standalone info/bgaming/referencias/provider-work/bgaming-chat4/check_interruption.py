"""Offline checkpoint/code integrity audit; does not contact or replay any demo."""
import ast,json,collections
from run_demo_qa import ROOT,PRIVATE,save,now
if __name__=='__main__':
 syntax=[]
 for f in ROOT.glob('*.py'):
  try:ast.parse(f.read_text(encoding='utf8'));syntax.append(dict(file=f.name,ok=True))
  except SyntaxError as e:syntax.append(dict(file=f.name,ok=False,line=e.lineno))
 counts=collections.Counter();pending=[];resolved=[]
 for f in list(PRIVATE.glob('*.session.json'))+list((PRIVATE/'hyperhive').glob('*.session.json'))+list((PRIVATE/'fresh-financial-revalidation').glob('*/session.json')):
  d=json.loads(f.read_text(encoding='utf8'));op=d.get('operation');op=op.get('status',op.get('state','unknown')) if isinstance(op,dict) else op
  status=d.get('status',op or 'unknown');counts[status]+=1
  if status in ('sending','uncertain'):
   gid=d.get('game_id',f.stem);readback=PRIVATE/'readback'/(gid+'.json');entry=dict(game_id=gid,status=status,private_checkpoint=str(f.relative_to(PRIVATE)),action='No POST replay; read-only state reconciliation required')
   if readback.exists():
    rb=json.loads(readback.read_text(encoding='utf8'));r=rb.get('response',{});balance=r.get('balance');prior=d.get('last_response',{}).get('balance')
    if rb.get('status')==200 and rb.get('time','')>d.get('updated_at','') and r.get('flow',{}).get('state')=='ready' and prior is not None and balance==prior:
     entry.update(action='Resolved by later init: same native balance and ready state, no POST replay',native_balance=balance,evidence='reconciliation-live/'+gid+'.json');resolved.append(entry);continue
   pending.append(entry)
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));missing=[]
 for gid,result in state['results'].items():
  f=ROOT/result['report']
  if not f.exists():missing.append(gid)
  else:json.loads(f.read_text(encoding='utf8'))
 historical=[]
 for f in (PRIVATE/'attempts').glob('*.session.json'):
  d=json.loads(f.read_text(encoding='utf8'));op=d.get('operation',{});status=d.get('status',op.get('status') if isinstance(op,dict) else op)
  if status in ('sending','uncertain'):historical.append(dict(game_id=d.get('game_id'),private_checkpoint=str(f.relative_to(PRIVATE)),original_post_outcome='unknown',note='Later init observed no open round; FUN balance may refresh on init, so it does not independently prove the original debit/credit. Original POST was not replayed.'))
 result=dict(checked_at=now(),syntax=syntax,temporary_files=[f.name for f in ROOT.glob('*.tmp')],missing_reports=missing,completed_game_checkpoints=len(state['results']),active_game=state.get('active_game'),private_status_counts=dict(counts),uncertain_post_checkpoints=pending,resolved_uncertain_posts=resolved,historical_uncertain_attempts=historical)
 save(ROOT/'interruption-audit.json',result);print(json.dumps({k:v for k,v in result.items() if k!='syntax'},ensure_ascii=False));print('syntax_valid',sum(x['ok'] for x in syntax),'of',len(syntax))
