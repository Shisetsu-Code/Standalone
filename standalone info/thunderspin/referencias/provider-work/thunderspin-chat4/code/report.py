"""Reproducible offline audit and coverage inventory, with no network."""
import hashlib,json,pathlib,datetime
from native import audit_packets,number
ROOT=pathlib.Path(__file__).resolve().parent.parent
def build():
 catalogue=json.loads((ROOT/'results/catalogue.json').read_text())
 out={'provider':'ThunderSpin','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'catalogue_count':len(catalogue),'public_demo_count':sum(bool(g.get('demo_url')) for g in catalogue),'without_public_demo':[{'ordinal':g['ordinal'],'title':g['title'],'reason':'no_demo_url_in_official_catalogue'} for g in catalogue if not g.get('demo_url')],'coverage_complete':False,'verified_cases':[],'pending_cases':[],'pending_modes':[],'covered_native_aliases':[],'audit_errors':[],'file_hashes':{}}
 for p in sorted((ROOT/'private/rounds').glob('*/*.json')):
  c=json.loads(p.read_text());rel=str(p.relative_to(ROOT));out['file_hashes'][rel]=hashlib.sha256(p.read_bytes()).hexdigest()
  if c.get('status')!='verified':out['pending_cases'].append({'case_file':rel,'game':c.get('game'),'mode':c.get('mode'),'status':c.get('status'),'error':c.get('error')});continue
  try:
   init_path=pathlib.Path(c.get('source_init_reference') or ROOT/'private/sessions'/('own-'+c['session_fingerprint'])/'init-journal.json');init=json.loads(init_path.read_text());init=dict(init,response=dict(init['response'],Balance=dict(init['response']['Balance'],ScoreCents=c['balance_before_cents'])));result=audit_packets([init]+c['journal'])
   if len(result['closed_rounds'])!=1 or result['unfinished_rounds']:raise ValueError('case_not_one_closed_round')
   out['verified_cases'].append({'case_file':rel,'game':c['game'],'mode':c['mode'],'init_reference':str(init_path.relative_to(ROOT)),'audit':result['closed_rounds'][0]});out['file_hashes'][str(init_path.relative_to(ROOT))]=hashlib.sha256(init_path.read_bytes()).hexdigest()
  except Exception as exc:out['audit_errors'].append({'case_file':rel,'error':str(exc)})
 for p in sorted((ROOT/'private/plans').glob('*.json')):
  plan=json.loads(p.read_text());game=plan['game'];audited={x['case_file'] for x in out['verified_cases']}
  for m in plan.get('pending_modes',[]):
   if m['mode']=='BuyFeatures' and isinstance(m.get('native_definition'),dict):
    for code,definition in m['native_definition'].items():
     target=ROOT/'private/rounds'/game/(('BUY_BONUS' if code=='default' else 'BUY_'+code)+'.json');rel=str(target.relative_to(ROOT));covered=False
     if rel in audited:
      case=json.loads(target.read_text());req=case['journal'][0]['request'];init=json.loads(pathlib.Path(case['source_init_reference'] if 'source_init_reference' in case else ROOT/'private/sessions'/('own-'+case['session_fingerprint'])/'init-journal.json').read_text())['response'];base=number(init.get('DefaultBet',init['Balance']['DefaultBet']))*number(req['denomination'])*number(req['betlevel']);quote=definition.get('costs',{}).get(str(int(base)),{})
      covered=(code=='default' and req.get('buyBonusCode') in (None,'default') or req.get('buyBonusCode')==code) and quote.get('allowed') is True and number(quote['buyValue'])==number(case['audit']['cost_cents'])
     if covered:out['covered_native_aliases'].append({'game':game,'native_code':code,'case_file':rel,'price_and_selector_match':True})
     else:out['pending_modes'].append({'game':game,'mode':'BuyFeatures.'+code,'reason':'distinct_native_code_not_verified','native_multiplier':definition.get('multiplier')})
   elif m['mode']=='gamble' and any(x['game']==game and x['mode']=='GAMBLE' for x in out['verified_cases']):continue
   elif m['mode']=='BUY_BONUS' and str((ROOT/'private/rounds'/game/'BUY_BONUS.json').relative_to(ROOT)) in audited:continue
   else:out['pending_modes'].append({'game':game,**m})
 out['games_with_cases']=len(set(x['game'] for x in out['verified_cases']+out['pending_cases']));out['status']='in_progress_or_partial_pending_catalogue_and_modes'
 (ROOT/'results/provider-report.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
 return out
if __name__=='__main__':
 x=build();print({k:len(x[k]) for k in ['verified_cases','pending_cases','pending_modes','audit_errors']}|{'games_with_cases':x['games_with_cases'],'catalogue':x['catalogue_count'],'coverage_complete':False})
