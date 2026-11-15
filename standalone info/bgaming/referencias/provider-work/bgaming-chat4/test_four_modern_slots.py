import copy,json,unittest
from pathlib import Path
from types import SimpleNamespace
from fractions import Fraction
import four_modern_slots as x
ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parents[1]/'bgaming-private-chat4'
ALLOWED=['buy_bonus','bonus_buy','freespin_buy','high_freespin_buy','buy_chance','bonus_chance','freespin_chance','buy_bonus_and_chance','freespin_and_bonus_chance']

class FourModern(unittest.TestCase):
 def sources(self,gid):
  manifest=json.loads((ROOT/'protocols'/(gid+'.fresh-frontend-resources.json')).read_text(encoding='utf8'));items={i['path']:i for i in manifest['resources']}
  return {path:(PRIVATE/'research/frontends'/gid/items[path]['cache_file']).read_bytes() for path in x.PINS[gid]}
 def initial(self,gid):
  bet={'CatsLoveYummy':30,'RedHotChilliChickens':20,'MysticReels':100,'ChickenFire':100}[gid]
  return {'result':dict(currency='FUN',currency_attributes={'code':'FUN','subunits':100,'exponent':2},config={'bet_limits':[bet,bet*2],'purchased_features':ALLOWED},balance=100000,state=None,freebets=None)}
 def meta(self,gid):return x.metadata(gid,self.sources(gid),ALLOWED)
 def harness(self,gid,responses):
  initial=self.initial(gid);meta=self.meta(gid);h=SimpleNamespace(initial=initial,metadata=meta,last=copy.deepcopy(initial['result']),parent=SimpleNamespace(events=[],money_checks=[]));calls=[];responses=iter(responses)
  def request(method,req):
   calls.append(copy.deepcopy(req));result=copy.deepcopy(next(responses))
   if gid!='ChickenFire':result.setdefault('round','own-round')
   envelope={'result':result};h.parent.events.append(dict(status=200,request={'method':method,'params':{'req':copy.deepcopy(req)}},response=envelope));h.last=result;return envelope
  h.request=request;return h,calls,x.plan(initial,meta)
 def test_all_fresh_entry_pins_and_visible_source_catalogs(self):
  expected={'CatsLoveYummy':[30,3000],'RedHotChilliChickens':[20,2000,4000],'MysticReels':[100,150,10000],'ChickenFire':[100,150,6000,9000,12000]}
  for gid in x.PINS:
   with self.subTest(gid=gid):
    html=(PRIVATE/'research/frontends'/gid/'index.html').read_text(encoding='utf8');sources=self.sources(gid);fetched=[]
    def fetch(path):fetched.append(path);return sources[path]
    meta=x.load_metadata(gid,html,fetch,ALLOWED);self.assertEqual(set(fetched),set(x.PINS[gid]));self.assertEqual([m['cost_native'] for m in x.plan(self.initial(gid),meta)],expected[gid]);self.assertFalse(meta['unresolved'])
    empty=x.metadata(gid,sources,[]);self.assertEqual(len(x.plan(self.initial(gid),empty)),1)
 def test_hash_entry_and_unknown_currency_changes_fail_before_gameplay(self):
  gid='CatsLoveYummy';sources=self.sources(gid);bad=copy.deepcopy(sources);bad[next(iter(bad))]+=b' '
  with self.assertRaises(ValueError):x.metadata(gid,bad,ALLOWED)
  with self.assertRaises(ValueError):x.load_metadata(gid,'<html></html>',lambda path:self.fail('No fetch for unselected source'),ALLOWED)
  initial=self.initial(gid);initial['result']['currency']='USD'
  with self.assertRaises(ValueError):x.plan(initial,self.meta(gid))
 def test_cats_purchase_id_native_price_free_continuation_and_incremental_win(self):
  h,calls,modes=self.harness('CatsLoveYummy',[dict(final=False,balance=97010,resp={'win':10,'body':{'nextBonus':'{"bonusName":"freeBuy","currentSpin":0,"totalSpins":1}'}}),dict(final=True,balance=97015,resp={'win':5,'body':{}})])
  result=x.run(h,modes[1]);self.assertEqual(result['status'],'closed');self.assertEqual(calls,[{'bet':30,'bet_type':'bet','purchased_feature':'buy_bonus','buy_feature_id':1},{'bet':30,'bet_type':'bet'}]);self.assertEqual(result['win_ratio'],[15,1]);checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(all(c['ok'] for c in checks));self.assertTrue(rounds[0]['closed'])
 def test_cats_unknown_pending_bonus_does_not_send_another_paid_spin(self):
  h,calls,modes=self.harness('CatsLoveYummy',[dict(final=False,balance=99970,resp={'win':0,'body':{'nextBonus':{'bonusName':'pick_unknown'}}})])
  with self.assertRaises(ValueError):x.run(h,modes[0])
  self.assertEqual(len(calls),1);checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertFalse(checks[-1]['ok']);self.assertFalse(rounds[0]['closed'])
 def test_mystic_native_base_bet_first_feature_only_and_cashwin_sum(self):
  h,calls,modes=self.harness('MysticReels',[dict(final=False,balance=90001,resp={'CashWin':1,'GameCycleWinningsSoFar':1}),dict(final=True,balance=90003,resp={'CashWin':2,'GameCycleWinningsSoFar':3})]);result=x.run(h,modes[2])
  self.assertEqual(calls,[{'bet':100,'bet_type':'bet','purchased_feature':'buy_bonus'},{'bet':100,'bet_type':'bet'}]);self.assertEqual(result['win_ratio'],[3,1]);checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(checks[-1]['ok'])
 def test_truncated_valid_nonfinal_round_is_explicit_audit_failure(self):
  for gid,resp in [('MysticReels',{'CashWin':1}),('CatsLoveYummy',{'win':1,'body':{'nextBonus':{'bonusName':'free','currentSpin':0,'totalSpins':1}}})]:
   with self.subTest(gid=gid):
    initial=self.initial(gid);meta=self.meta(gid);mode=x.plan(initial,meta)[0]
    event=dict(status=200,request={'method':'play','params':{'req':mode['req']}},response={'result':{'final':False,'round':'own-round','balance':100000-mode['cost_native']+1,'resp':resp}})
    checks,rounds=x.audit(initial,[event],meta)
    self.assertEqual(checks[-1]['kind'],'four_modern_open_round');self.assertFalse(checks[-1]['ok']);self.assertFalse(rounds[-1]['closed']);self.assertEqual(checks[-1]['start_event'],0)
 def test_redhot_bonus_completion_uses_whole_round_win_not_step_sum(self):
  h,calls,modes=self.harness('RedHotChilliChickens',[dict(final=False,balance=98000,resp={'nextAction':'BONUS','game':{'spin':{'totalWin':10}}}),dict(final=True,balance=98250,resp={'nextAction':'SPIN','game':{'totalWin':250}})]);result=x.run(h,modes[1])
  self.assertEqual(calls[0],{'bet':20,'bet_type':'betting','purchased_feature':'bonus_buy','isSuperBonus':False});self.assertEqual(calls[1],{'bet':20,'bet_type':'betting','action':'bonus'});self.assertEqual(result['win_ratio'],[250,1]);checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(checks[-1]['ok'])
 def test_redhot_never_repeats_rejected_nonfinal_bonus_completion(self):
  h,calls,modes=self.harness('RedHotChilliChickens',[dict(final=False,balance=98000,resp={'nextAction':'BONUS','game':{'spin':{'totalWin':0}}}),dict(final=False,balance=98000,resp={'nextAction':'BONUS','game':{'totalWin':0}})])
  with self.assertRaises(ValueError):x.run(h,modes[1])
  self.assertEqual(len(calls),2)
 def test_chicken_three_distinct_ids_and_one_complete_response(self):
  h,calls,modes=self.harness('ChickenFire',[dict(final=True,balance=88345,resp={'data':[{}],'totalWin':345})]);result=x.run(h,modes[4]);self.assertEqual(calls,[{'bet':100,'bet_type':'bet','purchased_feature':'buy_bonus','feature_id':'buy_ultra_bonus'}]);self.assertEqual(result['win_ratio'],[345,1]);self.assertTrue(h.parent.money_checks[-1]['ok']);checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(checks[-1]['ok'])
 def test_chicken_actual_received_bonus_uses_plain_stage_requests_initial_total_once(self):
  fixture=json.loads((ROOT/'protocols/ChickenFire.received-native-bonus-fixture.json').read_text());opening=fixture['received_result'];final_balance=fixture['before_balance_native']-6000+opening['resp']['totalWin']
  # Follow-up synthetic receipt deliberately has no resp: the source consumes
  # only its final/balance/state_lock and retains the opening gameResponse.
  follow=[dict(final=i==len(opening['resp']['data'])-1,balance=final_balance if i==len(opening['resp']['data'])-1 else opening['balance'],round=opening.get('round')) for i in range(len(opening['resp']['data']))]
  h,calls,modes=self.harness('ChickenFire',[opening]+follow);h.last['balance']=fixture['before_balance_native'];h.initial['result']['balance']=fixture['before_balance_native']
  result=x.run(h,modes[2]);self.assertEqual(result['win_ratio'],[14700,1]);self.assertEqual(len(calls),1+len(opening['resp']['data']));self.assertEqual(calls[0],fixture['request']);self.assertTrue(all(req=={'bet':100,'bet_type':'bet'} for req in calls[1:]));self.assertEqual(result['final_balance'],108450)
  checks,rounds=x.audit(h.initial,h.parent.events,h.metadata);self.assertTrue(all(c['ok'] for c in checks));self.assertTrue(rounds[-1]['closed']);self.assertEqual(rounds[-1]['win_ratio'],[14700,1])
 def test_chicken_nonfinal_and_failed_money_never_continue(self):
  h,calls,modes=self.harness('ChickenFire',[dict(final=False,balance=99900,resp={'data':[{}],'totalWin':0})])
  with self.assertRaises(ValueError):x.run(h,modes[0])
  self.assertEqual(len(calls),1)
  h,calls,modes=self.harness('ChickenFire',[dict(final=True,balance=99901,resp={'data':[{}],'totalWin':0})])
  with self.assertRaises(ValueError):x.run(h,modes[0])
  self.assertFalse(h.parent.money_checks[-1]['ok']);self.assertEqual(len(calls),1)
 def test_native_bets_are_never_scaled_to_make_fractional_prices_work(self):
  initial=self.initial('MysticReels');initial['result']['config']['bet_limits']=[101]
  with self.assertRaises(ValueError):x.plan(initial,self.meta('MysticReels'))
  h,calls,modes=self.harness('ChickenFire',[]);mode=copy.deepcopy(modes[0]);mode['req']['bet']=10
  with self.assertRaises(ValueError):x.run(h,mode)
  self.assertFalse(calls)
