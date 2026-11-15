import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import rpc_extra as x

ROOT = Path(__file__).resolve().parents[2]

class ExtraRPC(unittest.TestCase):
 def meta(self, gid):
  directory=ROOT/'bgaming-private-chat4/research/frontends'/gid
  source = '\n'.join(p.read_text(encoding='utf8') for p in list(directory.glob('review*'))+list(directory.glob('rpc-extra-*.js')))
  if gid=='GrandPatron7rst':source+='\n'+next(directory.glob('rpc-extra-*bets_data-*.json')).read_text(encoding='utf8')
  initial = json.loads((Path(__file__).parent/'live'/f'{gid}.json').read_text())['events'][0]['response']
  return initial, x.metadata(source, initial['result']['config']['purchased_features'])
 def test_source_registry_is_specific_not_global_allowlist(self):
  for gid, names in [('RecycleRiches', ['normal','chance','buy_random','buy_max']), ('BlackbeardsBounty',['normal','buy_chance','freeSpin','freeSpinRandom']), ('BlazingFirepots',['normal','buy_chance','buy_bonus'])]:
   initial, meta = self.meta(gid)
   modes=x.plan(initial,meta)
   self.assertEqual([m['name'] for m in modes],names)
   self.assertEqual(modes[0]['bet_native'],min(initial['result']['config']['bet_limits']))
  with self.assertRaises(ValueError):x.metadata('purchased_features:["buy_bonus"]', ['buy_bonus'])
 def test_recycle_purchase_then_plain_native_continuation(self):
  initial,meta=self.meta('RecycleRiches');mode=x.plan(initial,meta)[2]
  replies=[{'final':False,'balance':98000,'resp':{'roundData':{'roundWin':10}}},{'final':True,'balance':98030,'resp':{'roundData':{'roundWin':30}}}]
  calls,h=self.harness(replies)
  self.assertEqual(x.run(h,mode)['win_native'],30)
  self.assertEqual(calls,[{'bet':20,'custom_field':'buy_random','purchased_feature':'buy_bonus'},{'bet':20}])
  checks,rounds=x.audit(initial,h.parent.events,meta)
  self.assertTrue(checks[0]['ok']);self.assertTrue(rounds[0]['closed'])
 def test_firepots_action_continuations(self):
  initial,meta=self.meta('BlazingFirepots');mode=x.plan(initial,meta)[0]
  calls,h=self.harness([{'final':False,'balance':99980,'resp':{'nextAction':'WHEEL'}},{'final':False,'balance':99980,'resp':{'nextAction':'BONUS'}},{'final':True,'balance':100000,'resp':{'nextAction':'SPIN','game':{'totalWin':20}}}])
  x.run(h,mode)
  self.assertEqual([r['action'] for r in calls],['spin','wheel','bonus'])
  self.assertEqual({r['bet_type'] for r in calls},{'betting'})
 def test_blackbeard_uses_cumulative_data_once(self):
  initial,meta=self.meta('BlackbeardsBounty');mode=x.plan(initial,meta)[3]
  resp={'commonGame':{'totalWin':5},'roundStep':2,'freespinsGame':{'data':[{'type':'INITIAL_FREE_SPIN','winResult':{'multipliedTotalWin':10}},{'type':'CASCADE','winResult':{'multipliedTotalWin':5}},{'type':'INITIAL_FREE_SPIN','winResult':{'multipliedTotalWin':20}}]}}
  calls,h=self.harness([{'final':True,'balance':96040,'resp':resp}])
  self.assertEqual(x.run(h,mode)['win_native'],40)
  self.assertEqual(calls[0],{'bet':20,'purchased_feature':'buy_bonus','bonus_multiplier_type':'freeSpinRandom'})
 def test_unknown_firepots_action_stops_before_next_request(self):
  initial,meta=self.meta('BlazingFirepots');mode=x.plan(initial,meta)[0]
  calls,h=self.harness([{'final':False,'balance':99980,'resp':{'nextAction':'PICK'}}])
  with self.assertRaises(RuntimeError):x.run(h,mode)
  self.assertEqual(len(calls),1)
 def test_balance_mismatch_is_rejected(self):
  initial,meta=self.meta('RecycleRiches');mode=x.plan(initial,meta)[0]
  calls,h=self.harness([{'final':True,'balance':99999,'resp':{'roundData':{'roundWin':0}}}])
  with self.assertRaises(RuntimeError):x.run(h,mode)
 def test_jungle_native_purchase_and_incremental_free_spin_wins(self):
  initial,meta=self.meta('JungleQueen');mode=x.plan(initial,meta)[1];bet=mode['bet_native'];cost=mode['cost_native']
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'state':{'status':'FREESPINS_TRIGGER'},'results':{'win':{'total':'5'}}}},{'final':True,'balance':100000-cost+15,'resp':{'state':{'status':'NORMAL'},'results':{'win':{'total':'10'}}}}])
  self.assertEqual(x.run(h,mode)['win_native'],15)
  self.assertEqual(calls,[{'bet':bet,'action':'buybonus','id':'buybonus','purchased_feature':'buy_bonus'},{'bet':bet,'action':'freespin','bet_type':'bet'}])
  checks,rounds=x.audit(initial,h.parent.events,meta);self.assertTrue(checks[0]['ok'])
  self.assertEqual(h.parent.events[0]['response']['result']['resp']['results']['win']['total'],'5')
 def test_jungle_string_payout_is_exact_fraction_only_for_jungle(self):
  from fractions import Fraction
  self.assertEqual(x._win({'resp':{'results':{'win':{'total':'0.1'}}}},'jungle-queen'),Fraction(1,10))
  with self.assertRaises(ValueError):x._money('0.1')
  with self.assertRaises(ValueError):x._win({'resp':{'results':{'win':{'total':'NaN'}}}},'jungle-queen')
 def test_sugar_mix_native_bet_null_normal_feature_and_fifty_factor(self):
  initial,meta=self.meta('SugarMix');modes=x.plan(initial,meta);mode=modes[1]
  self.assertEqual(mode['cost_native'],mode['bet_native']*50)
  cost=mode['cost_native'];bet=mode['bet_native']
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'resultState':{'totalWin':5}}},{'final':True,'balance':100000-cost+12,'resp':{'resultState':{'totalWin':7}}}])
  self.assertEqual(x.run(h,mode)['win_native'],12)
  self.assertEqual(calls,[{'bet':bet,'bet_type':'default','purchased_feature':'buy_bonus'},{'bet':bet,'bet_type':'default','purchased_feature':None}])
 def test_treasure_native_total_bet_and_machine_six(self):
  initial,meta=self.meta('TreasureExplorer');modes=x.plan(initial,meta)
  self.assertEqual([m['cost_native']//m['bet_native'] if m['cost_native']%m['bet_native']==0 else m['cost_native']/m['bet_native'] for m in modes],[1,1.4,100,250])
  mode=modes[3];bet=mode['bet_native'];cost=mode['cost_native']
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'totalWin':5}},{'final':True,'balance':100000-cost+12,'resp':{'totalWin':7}}])
  self.assertEqual(x.run(h,mode)['win_native'],12)
  self.assertEqual(calls,[{'bet':bet,'machineId':6,'purchased_feature':'buy_bonus_and_chance'},{'bet':bet,'machineId':6}])
 def test_zeus_normalized_payout_does_not_scale_native_bet(self):
  initial,meta=self.meta('ZeusGoesWild');mode=x.plan(initial,meta)[0]
  self.assertEqual(len(x.plan(initial,meta)),1)
  # Client stages use a fixed ten-unit paytable, while request and wallet
  # remain native currency values. Use a larger legal native bet to catch
  # accidental direct payout use.
  mode['bet_native']=20;mode['cost_native']=20
  calls,h=self.harness([{'final':True,'balance':100020,'resp':{'super_spin':{'bet':20,'round':{'stages':[{'totalWin':20}]}}}}])
  self.assertEqual(x.run(h,mode)['win_native'],40)
  self.assertEqual(calls,[{'bet':20,'bet_type':'default','custom_field':'custom_value','fe_exponent':2}])
 def test_robospin_explicit_traits_registry_without_buy_features(self):
  initial,meta=self.meta('Robospin');modes=x.plan(initial,meta)
  self.assertEqual(len(modes),20)
  self.assertEqual(modes[0]['request'],{'traits_to_win':1,'selected_traits':{'hat':'left'}})
  self.assertEqual(modes[-1]['request'],{'traits_to_win':6,'selected_traits':dict.fromkeys(['hat','ears','arms','head','body','bg'],'left')})
  mode=modes[0];bet=mode['bet_native'];calls,h=self.harness([{'final':True,'balance':100000-bet+19,'resp':{'win':19}}])
  self.assertEqual(x.run(h,mode)['win_native'],19)
  self.assertEqual(calls,[{'bet':bet,**mode['request']}])
 def test_keepers_native_string_bet_buy_120_and_incremental_steps(self):
  initial,meta=self.meta('KeepersOfTheSecret7rst');modes=x.plan(initial,meta);mode=modes[1];bet=mode['bet_native'];cost=mode['cost_native']
  self.assertEqual(cost,bet*120)
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'step':{'win':'5'}}},{'final':True,'balance':100000-cost+12,'resp':{'step':{'win':'7'}}}])
  self.assertEqual(x.run(h,mode)['win_native'],12)
  self.assertEqual(calls,[{'bet':str(bet),'purchased_feature':'buy_bonus'},{'bet':str(bet)}])
  checks,rounds=x.audit(initial,h.parent.events,meta);self.assertTrue(checks[0]['ok'])
 def test_static_decoder_reproduces_pinned_private_keepers_derivations(self):
  directory=ROOT/'bgaming-private-chat4/research/frontends/KeepersOfTheSecret7rst'
  for original in [directory/'rpc-extra-59301064efe3-BS_lib-15a29c5b.js',directory/'rpc-extra-6479bebd7c75-Game-15a29c5b.js']:
   expected=original.with_name('rpc-extra-decoded-'+original.name).read_text(encoding='utf8')
   self.assertEqual(x.decode_static_strings(original.read_text(encoding='utf8')),expected)
  with self.assertRaises(ValueError):x.decode_static_strings('fetch("https://example.com")')
 def test_static_decoder_rejects_non_arithmetic_checksum(self):
  bad='const _0xa=["1"];_0xb=_0xb-0x1;try{const _0xc=__import__("os");if(x){} }(_0xd,0x1)'
  with self.assertRaises(ValueError):x.decode_static_strings(bad)
 def test_grand_patron_exact_bid_registry_and_continuation(self):
  initial,meta=self.meta('GrandPatron7rst');modes=x.plan(initial,meta)
  self.assertEqual([m['request'] for m in modes],[{}, {'bid':1,'purchased_feature':'buy_bonus'},{'bid':2,'purchased_feature':'buy_bonus'},{'bid':3,'purchased_feature':'buy_bonus'},{'bid':4}])
  self.assertEqual([m['cost_native']/m['bet_native'] for m in modes],[1,100,250,1000,1.3])
  mode=modes[2];bet=mode['bet_native'];cost=mode['cost_native']
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'step':{'win':'5'}}},{'final':True,'balance':100000-cost+12,'resp':{'step':{'win':'7'}}}])
  self.assertEqual(x.run(h,mode)['win_native'],12)
  self.assertEqual(calls,[{'bet':str(bet),'bid':2,'purchased_feature':'buy_bonus'},{'bet':str(bet),'bid':2}])
 def test_big_bucks_native_buy_120_and_cumulative_round_win(self):
  initial,meta=self.meta('BigBucksSaloon');modes=x.plan(initial,meta);mode=modes[1];bet=mode['bet_native'];cost=mode['cost_native']
  self.assertEqual(cost,bet*120)
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'round':{'win':'5'}}},{'final':True,'balance':100000-cost+12,'resp':{'round':{'win':'12'}}}])
  self.assertEqual(x.run(h,mode)['win_native'],12)
  self.assertEqual(calls,[{'bet':bet,'purchased_feature':'buy_bonus'},{'bet':bet}])
 def test_clash_exact_product_ids_prices_and_both_native_choices(self):
  initial,meta=self.meta('ClashofGodsAnubisvsHades');modes=x.plan(initial,meta)
  self.assertEqual(len(modes),12)
  self.assertEqual([m['cost_native']/m['bet_native'] for m in modes[::2]],[1,10,3,800,100,300])
  mode=modes[-1];bet=mode['bet_native'];cost=mode['cost_native']
  calls,h=self.harness([{'final':False,'balance':100000-cost,'resp':{'super_spin':{'bet':bet,'round':{'stages':[{'totalWin':0,'isNextFree':True}]}}}},{'final':True,'balance':100000-cost+2*bet,'resp':{'super_spin':{'bet':bet,'round':{'stages':[{'totalWin':20}]}}}}])
  self.assertEqual(x.run(h,mode)['win_native'],2*bet)
  self.assertEqual(calls[0]['feature_buy'],'super_buy_bonus');self.assertEqual(calls[0]['buyBonusModeMultiplier'],300)
  self.assertNotIn('bonus_type',calls[0]);self.assertEqual(calls[1]['bonus_type'],'1');self.assertIsNone(calls[1]['purchased_feature'])
  self.assertEqual(calls[1]['buyBonusModeMultiplier'],1)
  checks,rounds=x.audit(initial,h.parent.events,meta);self.assertTrue(checks[0]['ok']);self.assertEqual(rounds[0]['mode']['bonus_choice'],'1')
 def test_aztec_respects_empty_enabled_products_and_explicit_finish_ack(self):
  initial,meta=self.meta('AztecsClawWildDice');modes=x.plan(initial,meta)
  self.assertEqual([m['name'] for m in modes],['normal'])
  mode=modes[0];bet=mode['bet_native']
  calls,h=self.harness([{'final':False,'balance':100000-bet+5,'resp':{'win_amount':5,'bonus_game':'WILD_DICES'}},{'final':True,'balance':100000-bet+5,'resp':{'win_amount':10,'bonus_game':'WILD_DICES_FINISH'}},{'final':True,'balance':100000-bet+15}])
  self.assertEqual(x.run(h,mode)['win_native'],15)
  self.assertEqual(calls,[{'bet':bet,'bet_type':'bet'},{'bet':bet,'bet_type':'bet','bonus_game':'WILD_DICES'},{'bet':bet,'bet_type':'bet','bonus_game':'WILD_DICES_FINISH'}])
  checks,rounds=x.audit(initial,h.parent.events,meta);self.assertTrue(checks[0]['ok']);self.assertEqual(rounds[0]['last_event'],2)
 def test_aztec_product_contract_has_mutually_exclusive_ante_and_wild(self):
  source=next((ROOT/'bgaming-private-chat4/research/frontends/AztecsClawWildDice').glob('review*')).read_text(encoding='utf8')
  initial,_=self.meta('AztecsClawWildDice');meta=x.metadata(source,['buy_bonus','buy_chance','buy_bonus_and_chance']);modes=x.plan(initial,meta)
  self.assertEqual([m['cost_native']//m['bet_native'] for m in modes],[1,2,5,80])
  self.assertTrue(x._request(modes[-1])['instant_bonus_game'])
  self.assertFalse(any('ante_bet' in m['request'] and 'wild_bet' in m['request'] for m in modes))
 def harness(self,replies):
  replies=iter(replies);calls=[]
  h=SimpleNamespace(last={'balance':100000,'state':None},parent=SimpleNamespace(events=[],money_checks=[]))
  def request(method,req):
   calls.append(req);response={'result':next(replies)};h.parent.events.append({'request':{'method':method,'params':{'req':req}},'response':response});return response
  h.request=request
  return calls,h
