"""Second pass for distinct native BuyFeatures codes. No normal repeats."""
import json,msvcrt,pathlib,re,os
from campaign import ROOT,Campaign,save,number
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);runner=Campaign();runner.state['pass']='named_features'
 try:
  catalogue=json.loads((ROOT/'results/catalogue.json').read_text())
  for g in catalogue:
   p=ROOT/'private/plans'/(g['slug']+'.json')
   if not p.exists() or (ROOT/'private/holds'/(g['slug']+'.json')).exists():continue
   prior=json.loads(p.read_text());defs={};canonical=any(m['mode']=='BUY_BONUS' for m in prior.get('pending_modes',[]))
   for item in prior.get('pending_modes',[]):
    if item['mode']=='BuyFeatures':defs.update(item['native_definition'])
   defs={k:v for k,v in defs.items() if k!='default' and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',k)}
   if not defs and not canonical:continue
   client=ROOT/'private/references'/g['slug']/'client.js'
   from contracts import identify
   identified=identify(client.read_text(encoding='utf-8'))
   if not (defs and identified.get('named_buy_contract') or canonical and identified.get('buy_bonus_contract')):continue
   paths=[ROOT/'private/rounds'/prior['game']/('BUY_'+k+'.json') for k in defs]
   if canonical:paths.append(ROOT/'private/rounds'/prior['game']/'BUY_BONUS.json')
   if any(q.exists() and json.loads(q.read_text()).get('status')!='verified' for q in paths):raise ValueError('existing_uncertain_named_feature_no_retry')
   if all(q.exists() for q in paths):continue
   runner.state['current']={'slug':g['slug'],'stage':'fresh_named_feature_demo'};runner.checkpoint();cfg,fp,init,init_path=runner.prepare(g);x=init['response'];b=x['Balance'];denom=min(b['CoinValue']);level=min(b['BetLevel']);base=number(x.get('DefaultBet',b['DefaultBet']))*number(denom)*number(level);lines=b.get('CurrentLinesCount',0);native=x.get('BuyFeatures') or {}
   canonical_path=ROOT/'private/rounds'/cfg['slotcode']/'BUY_BONUS.json'
   if canonical and not canonical_path.exists():
    price=x.get('Features',{}).get('BuyBonus',{}).get('Costs',{}).get('costs',{}).get(str(int(base)),{})
    if cfg['contract']['buy_bonus_contract'] and price.get('allowed') is True:
     runner.state['current']={'game':cfg['slotcode'],'mode':'BUY_BONUS','stage':'native_canonical_buy'};runner.checkpoint();init,lines=runner.run_case(cfg,fp,init,init_path,'BUY_BONUS',price['buyValue'],denom,level,lines)
    else:runner.state['pending'].append({'game':cfg['slotcode'],'mode':'BUY_BONUS','reason':'native_price_or_contract_not_available'})
   for code in defs:
    target=ROOT/'private/rounds'/cfg['slotcode']/('BUY_'+code+'.json')
    if target.exists():continue
    feature=native.get(code,{});price=feature.get('costs',{}).get(str(int(base)),{})
    if feature.get('code')!=code or price.get('allowed') is not True:
     runner.state['pending'].append({'game':cfg['slotcode'],'mode':code,'reason':'not_native_available_at_minimum'});continue
    runner.state['current']={'game':cfg['slotcode'],'mode':'BUY_'+code,'stage':'native_named_buy'};runner.checkpoint();init,lines=runner.run_case(cfg,fp,init,init_path,'BUY_'+code,price['buyValue'],denom,level,lines,buy_code=code)
   runner.state['completed_games'].append({'game':cfg['slotcode'],'named_codes':list(defs)});runner.checkpoint()
  runner.state['status']='named_features_pass_finished_pending_audit';runner.checkpoint()
 except Exception as exc:
  runner.state.update(status='stopped_for_review',error=str(exc));runner.checkpoint();print(json.dumps({k:runner.state.get(k) for k in ['pid','status','current','error']}),flush=True)
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
