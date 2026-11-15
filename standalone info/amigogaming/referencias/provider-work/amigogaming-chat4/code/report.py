"""Offline coverage and original native ledger audit; no network."""
import json,pathlib,hashlib,collections,datetime
from discover import ROOT,save
from native import audit,minimum_bet,D
def build():
 catalogue=json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8'));out={'provider':'Amigo Gaming','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'catalogue_entries':len(catalogue),'coming_soon':[g for g in catalogue if g['is_coming_soon']],'eligible_games':sum(not g['is_coming_soon'] for g in catalogue),'verified':[],'pending':[],'audit_errors':[],'unvisited':[],'plans':[],'source_hashes':{},'captured_ws_packets_available':False,'scope':'native minimum normal and every buyIns mode; observed continuations; not every random outcome, line or stake'}
 audited=set();rejected=[]
 for p in sorted((ROOT/'private/rounds').glob('*/*.json')):
  c=json.loads(p.read_text(encoding='utf-8'));rel=str(p.relative_to(ROOT));out['source_hashes'][rel]=hashlib.sha256(p.read_bytes()).hexdigest()
  if c['status']=='rejected_no_funds':rejected.append({'case':rel,'game_id':c['game_id'],'slug':c['slug'],'mode':c['mode'],'status':c['status'],'error':c.get('error')});continue
  if c['status']!='verified':out['pending'].append({'case':rel,'game_id':c['game_id'],'slug':c['slug'],'mode':c['mode'],'status':c['status'],'error':c.get('error')});continue
  try:
   ip=ROOT/c['init_reference'];init=json.loads(ip.read_text(encoding='utf-8'))['response'];out['source_hashes'][c['init_reference']]=hashlib.sha256(ip.read_bytes()).hexdigest();init['balance']['amount']=c['balance_before']
   if c['journal'][0]['request']['action']['betParams']!=minimum_bet(init):raise ValueError('not_native_minimum')
   request=c['journal'][0]['request']['action']
   if c['mode']=='NORMAL':
    if 'buyInId' in request or D(c['price_multiplier'])!=1:raise ValueError('normal_mode_price_or_selector')
   else:
    code=c['mode'].removeprefix('BUY_');quote=next((b for b in init.get('buyIns',[]) if b['id']==code),None)
    if quote is None or request.get('buyInId')!=code or D(str(quote['price']))!=D(c['price_multiplier']):raise ValueError('native_buy_quote_not_matched')
   for packet in c['journal']:
    if packet.get('recovery_snapshot'):
     ref=ROOT/packet['recovery_reference'];assert json.loads(ref.read_text(encoding='utf-8'))['response']==packet['recovery_snapshot'];out['source_hashes'][str(ref.relative_to(ROOT))]=hashlib.sha256(ref.read_bytes()).hexdigest()
   a=audit(init,c['journal'],c['price_multiplier']);out['verified'].append({'case':rel,'game_id':c['game_id'],'slug':c['slug'],'mode':c['mode'],'init_reference':c['init_reference'],'audit':a});audited.add((c['game_id'],c['mode']))
  except Exception as exc:out['audit_errors'].append({'case':rel,'error':str(exc)})
 out['rejected_requests']=rejected
 excluded=[]
 for g in catalogue:
  if g['is_coming_soon']:continue
  p=ROOT/'private/plans'/(str(g['id'])+'.json')
  if not p.exists():out['unvisited'].append({'id':g['id'],'slug':g['slug']});continue
  plan=json.loads(p.read_text(encoding='utf-8'));out['plans'].append(plan)
  if plan.get('excluded_non_slot'):excluded.append(plan);continue
  for mode in plan['modes']:
   if (g['id'],mode) not in audited and not any(c['game_id']==g['id'] and c['mode']==mode for c in out['pending']):out['pending'].append({'game_id':g['id'],'slug':g['slug'],'mode':mode,'status':'not_verified'})
 out['excluded_non_slots']=excluded;out['eligible_games']-=len(excluded)
 discovered=[]
 for item in out['verified']:
  c=json.loads((ROOT/item['case']).read_text(encoding='utf-8'));initial=json.loads((ROOT/c['init_reference']).read_text(encoding='utf-8'))['response'];known={b['id'] for b in initial.get('buyIns',[]) or []}
  for packet in c['journal']:
   for b in (packet.get('response') or packet.get('recovery_snapshot') or {}).get('buyIns',[]) or []:
    if b['id'] not in known:
     found={'game_id':c['game_id'],'slug':c['slug'],'mode':'BUY_'+b['id'],'native_offer':b}
     if found not in discovered:discovered.append(found)
 out['additional_response_buy_offers']=discovered
 for found in discovered:
  if (found['game_id'],found['mode']) not in audited:out['pending'].append(dict(found,status='additional_native_offer_not_verified'))
 out['verified_normals']=len({x['game_id'] for x in out['verified'] if x['mode']=='NORMAL'});out['verified_buys']=len({(x['game_id'],x['mode']) for x in out['verified'] if x['mode'].startswith('BUY_')});out['verified_closed_cases']=len(out['verified']);out['coverage_complete']=not(out['pending'] or out['unvisited'] or out['audit_errors']) and out['verified_normals']==out['eligible_games'];out['status']='finished' if out['coverage_complete'] else 'in_progress_or_partial'
 if (ROOT/'private/remote-block.json').exists():out.update(status='stopped_on_http_403_partial',remote_block=json.loads((ROOT/'private/remote-block.json').read_text(encoding='utf-8')),coverage_complete=False)
 recovery=ROOT/'private/recovery/fresh-session-check.json'
 if recovery.exists():out['historical_403_recovery']=json.loads(recovery.read_text(encoding='utf-8'))
 save(ROOT/'results/provider-report.json',out);return out
if __name__=='__main__':
 x=build();print({k:x[k] for k in ['eligible_games','verified_normals','verified_buys','coverage_complete']}|{k:len(x[k]) for k in ['pending','unvisited','audit_errors']})
