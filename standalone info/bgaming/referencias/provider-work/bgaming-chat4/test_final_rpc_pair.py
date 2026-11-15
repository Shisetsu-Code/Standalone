import copy,importlib.util,json,unittest
from pathlib import Path
from types import SimpleNamespace
if importlib.util.find_spec('final_rpc_pair'):
 import final_rpc_pair as pair
else:pair=None
ROOT=Path(__file__).resolve().parent;PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def source(gid):return next(f for f in (PRIVATE/'research/frontends'/gid).glob('*.js') if 'main.' in f.name or 'bundle' in f.name).read_text(encoding='utf8')
def init(gid):
 candidates=sorted((ROOT/'live/attempts').glob(gid+'*.json'))+[ROOT/'live'/(gid+'.json')]
 for candidate in candidates:
  data=json.loads(candidate.read_text(encoding='utf8'));events=data.get('events',[])
  if events and events[0].get('status')==200 and events[0].get('response',{}).get('result',{}).get('currency')=='FUN':return events[0]['response']
 raise AssertionError('Accepted original RPC init fixture missing: '+gid)
def meta(gid):return pair.metadata(gid,source(gid),init(gid)['result']['config']['purchased_features'])
def yommi(cost,win,total,end,balance,step=1,feature=None):
 return {'balance':balance,'state_lock':'synthetic-lock','final':end,'round':'own-round','step':step,'req':{'purchased_feature':feature},'resp':{'bet':20,'cost':cost,'winnings':win,'round':{'winnings':total},'outcome':{'roundEnd':end},'payload':{'bet':20},'state':{'freeSpins':0 if end else 2,'boughtFeature':'BONUS' if feature=='buy_bonus' else None}}}
def joker(win,total,next_free,balance,is_free=False,is_buy=False):
 return {'balance':balance,'state_lock':'synthetic-lock','final':not next_free,'resp':{'super_spin':{'finished':not next_free,'round':{'stages':[{'win':win,'totalWin':total,'isNextFree':next_free,'isFreespin':is_free,'isBuyBonus':is_buy,'freespinCount':1 if next_free else 0}]}}}}
class Transport:
 def __init__(self,gid,responses):
  self.metadata=meta(gid);self.initial=init(gid);self.last=copy.deepcopy(self.initial['result']);self.cfg={};self.responses=list(responses);self.calls=[];self.parent=SimpleNamespace(game={'game_id':gid},events=[{'request':{'method':'init'},'response':self.initial,'status':200}],money_checks=[])
 def request(self,method,req=None):
  assert method=='play';self.calls.append(copy.deepcopy(req));r=copy.deepcopy(self.responses.pop(0));self.last=r;outer={'jsonrpc':'2.0','result':r};self.parent.events.append({'request':{'method':'play','params':{'req':copy.deepcopy(req)}},'response':outer,'status':200});return outer
class FinalPair(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(pair,'Source-pinned final RPC pair adapter required')
 def test_source_features_intersect_global_whitelist_instead_of_inventing_aliases(self):
  ym=meta('YommiRush');jm=meta('JokerVsJoker');self.assertEqual(ym['features'],{'buy_chance':3,'buy_bonus':100,'buy_bonus_and_chance':250});self.assertEqual(jm['features'],{'buy_bonus':60,'buy_chance':10});self.assertIn('freespin_buy',jm['global_only_aliases']);self.assertEqual([m['cost_native'] for m in pair.plan(init('YommiRush'),ym)],[20,60,2000,5000]);self.assertEqual([m['cost_native'] for m in pair.plan(init('JokerVsJoker'),jm)],[10,600,100])
 def test_wrong_source_or_nonfun_context_blocks_before_transport(self):
  with self.assertRaises(ValueError):pair.metadata('YommiRush','other source',[])
  initial=init('YommiRush');initial['result']['currency']='EUR'
  with self.assertRaises(ValueError):pair.plan(initial,meta('YommiRush'))
 def test_yommi_native_request_and_single_final_round(self):
  h=Transport('YommiRush',[yommi(20,0,0,True,99980)]);mode=pair.plan(h.initial,h.metadata)[0];result=pair.run(h,mode);self.assertEqual(h.calls,[{'bet':'20','bet_type':'bet','modelRev':0,'minExponent':2}]);self.assertEqual(result['status'],'closed');self.assertEqual(result['win_native'],0)
 def test_yommi_bonus_continuation_never_rebuys_and_final_ledger_allows_deferred_credit(self):
  h=Transport('YommiRush',[yommi(2000,10,10,False,98000,feature='buy_bonus'),yommi(0,20,30,True,98030,step=2)]);mode=next(m for m in pair.plan(h.initial,h.metadata) if m['feature']=='buy_bonus');result=pair.run(h,mode);self.assertEqual(h.calls[0]['purchased_feature'],'buy_bonus');self.assertNotIn('purchased_feature',h.calls[1]);self.assertEqual(result['win_native'],30);self.assertEqual(result['network_calls'],2);self.assertTrue(h.parent.money_checks[-1]['ok'])
 def test_yommi_paid_continuation_is_failed_without_retry(self):
  h=Transport('YommiRush',[yommi(2000,0,0,False,98000,feature='buy_bonus'),yommi(20,0,0,True,97980,step=2)]);mode=next(m for m in pair.plan(h.initial,h.metadata) if m['feature']=='buy_bonus')
  with self.assertRaises(ValueError):pair.run(h,mode)
  self.assertEqual(len(h.calls),2)
 def test_joker_exact_default_envelope_and_source_normalized_win_units(self):
  h=Transport('JokerVsJoker',[joker(20,20,False,100010)]);result=pair.run(h,pair.plan(h.initial,h.metadata)[0]);self.assertEqual(h.calls,[{'bet':10,'bet_type':'default','fe_exponent':2,'purchased_feature':None,'balance':100000,'buyBonusModeMultiplier':1}]);self.assertEqual(result['win_native'],20)
 def test_joker_bonus_uses_sixty_then_free_continuation_multiplier_one(self):
  h=Transport('JokerVsJoker',[joker(5,5,True,99400,is_buy=True),joker(15,20,False,99420,is_free=True)]);mode=next(m for m in pair.plan(h.initial,h.metadata) if m['feature']=='buy_bonus');result=pair.run(h,mode);self.assertEqual(h.calls[0]['buyBonusModeMultiplier'],60);self.assertEqual(h.calls[1]['buyBonusModeMultiplier'],1);self.assertIsNone(h.calls[1]['purchased_feature']);self.assertEqual(h.calls[1]['balance'],99400);self.assertEqual(result['status'],'closed')
 def test_joker_chance_is_retained_semantically_on_free_continuation(self):
  h=Transport('JokerVsJoker',[joker(10,10,True,99900),joker(20,30,False,99930,is_free=True)]);mode=next(m for m in pair.plan(h.initial,h.metadata) if m['feature']=='buy_chance');pair.run(h,mode);self.assertEqual([q['purchased_feature'] for q in h.calls],['buy_chance','buy_chance'])
 def test_monetary_mismatch_records_failure_and_does_not_fix_native_balance(self):
  h=Transport('JokerVsJoker',[joker(20,20,False,100011)]);mode=pair.plan(h.initial,h.metadata)[0]
  with self.assertRaises(ValueError):pair.run(h,mode)
  self.assertEqual(h.last['balance'],100011);self.assertFalse(h.parent.money_checks[-1]['ok']);self.assertEqual(len(h.calls),1)
 def test_open_round_prevents_another_paid_trigger(self):
  h=Transport('YommiRush',[]);h.last=yommi(20,0,0,False,99980)
  with self.assertRaises(ValueError):pair.run(h,pair.plan(h.initial,h.metadata)[0])
  self.assertFalse(h.calls)
 def test_audit_replays_request_costs_and_full_bonus_round_independently(self):
  h=Transport('YommiRush',[yommi(2000,10,10,False,98000,feature='buy_bonus'),yommi(0,20,30,True,98030,step=2)]);mode=next(m for m in pair.plan(h.initial,h.metadata) if m['feature']=='buy_bonus');pair.run(h,mode);checks,rounds=pair.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(all(c['ok'] for c in checks));self.assertEqual(len(rounds),1);events=copy.deepcopy(h.parent.events);events[2]['request']['params']['req']['purchased_feature']='buy_bonus'
  with self.assertRaises(ValueError):pair.audit(h.initial,events,h.metadata)
 def test_unknown_global_purchase_or_multistage_joker_stops(self):
  h=Transport('JokerVsJoker',[]);mode=copy.deepcopy(pair.plan(h.initial,h.metadata)[0]);mode['feature']='freespin_buy'
  with self.assertRaises(ValueError):pair.run(h,mode)
  self.assertFalse(h.calls)
  out=joker(0,0,False,99990);out['resp']['super_spin']['round']['stages'].append(copy.deepcopy(out['resp']['super_spin']['round']['stages'][0]));h=Transport('JokerVsJoker',[out])
  with self.assertRaises(ValueError):pair.run(h,pair.plan(h.initial,h.metadata)[0])
if __name__=='__main__':unittest.main()
