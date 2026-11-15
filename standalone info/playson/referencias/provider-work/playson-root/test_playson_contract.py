import unittest,json
from pathlib import Path
from xml.etree import ElementTree as E
from playson_contract import parse,quote,settle,reference_rounds
FIX=json.loads((Path(__file__).parent/'fixtures/captured-rounds.json').read_text(encoding='utf8'))
class PlaysonContractTests(unittest.TestCase):
 def test_captured_catalog_has_exactly100_canonical_titles(self):
  rows=json.loads((Path(__file__).parent/'catalog-captured.json').read_text(encoding='utf8'))['games']
  self.assertEqual(len(rows),100);self.assertEqual(len({r['slug']for r in rows}),100)
  self.assertTrue(all(r['site_url']=='https://playson.com/game/'+r['slug']for r in rows))
 def test_minimum_quote_and_two_purchase_costs(self):
  q=quote(parse(FIX[1]['initial']));self.assertEqual((q['line_bet_minor'],q['base_cost_minor'],q['buy_multipliers']),(2,20,[70,150]))
  self.assertEqual(quote(parse(FIX[0]['initial']))['base_cost_minor'],20)
 def test_invalid_and_unknown_prices_block_before_play(self):
  for value in ['','0','-1','2,word']:
   r=parse(FIX[1]['initial']);r.find('extra/stakeIncrement').text=value
   with self.subTest(value=value),self.assertRaises(ValueError):quote(r)
  r=parse(FIX[1]['initial']);r.find('game').set('buy_feature_cost','70,0')
  with self.assertRaises(ValueError):quote(r)
 def test_all_captured_roots_have_independent_ledgers(self):
  roots=[c for f in FIX for c in reference_rounds(f)]
  self.assertEqual(len(roots),16);self.assertTrue(all(c['passed']for c in roots));self.assertEqual(sum(c['kind']=='purchase'for c in roots),2)
  buys=[c for c in roots if c['kind']=='purchase'];self.assertEqual([(c['cost_minor'],c['win_minor'],len(c['steps']))for c in buys],[(15000,6600,10),(7000,2600,5)])
  self.assertTrue(all(not c['minimum_observed']for c in roots))
 def test_open_bonus_is_never_a_completed_purchase(self):
  f=json.loads(json.dumps(FIX[1]));f['financial']=f['financial'][:3];rs=reference_rounds(f);self.assertEqual(len(rs),1);self.assertFalse(rs[0]['passed']);self.assertFalse(rs[0]['checks']['round_closed'])
 def test_wrong_final_wallet_stays_failed(self):
  f=json.loads(json.dumps(FIX[0]));r=parse(f['financial'][0]['response']);r.find('user_new').set('cash','0');f['financial'][0]['response']=E.tostring(r,encoding='unicode');self.assertFalse(reference_rounds(f)[0]['passed'])
 def test_ante_quote_is_decimal_and_binds_reply_mode(self):
  from playson_contract import start_case
  initial=parse(FIX[1]['initial']);initial.find('game').set('chance_booster','1.5,5')
  self.assertEqual(quote(initial)['ante_multipliers'],['1.5','5'])
  request=parse('<client command="bet"><bet cash="2"/><chance_booster type="1.5"/></client>')
  reply=parse('<server command="bet" status="ok"><state current_state="idle"/><game cash-bet="20" cash-bet-game="20" cash-win="0" chance_booster_type="1.5"/><user_new cash="970"/></server>')
  case=settle(start_case(initial,reply,request,1000));self.assertEqual((case['mode'],case['cost_minor']),('Ante:1.5',30));self.assertTrue(case['passed'])
  reply.find('game').set('chance_booster_type','5');self.assertFalse(settle(start_case(initial,reply,request,1000))['passed'])

 def test_purchased_free_spins_close_under_original_cost(self):
  from playson_contract import start_case,snapshot
  initial=parse(FIX[1]['initial']);initial.find('extra/stakeIncrement').text='1';initial.find('game').set('buy_feature_cost','75,400')
  request=parse('<client command="bet"><bet cash="1"/><buy freegame="true" type="0"/></client>')
  entry=parse('<server command="bet" status="ok"><state current_state="fs"/><game cash-bet="10" cash-bet-game="10" cash-win="0" bonus_games="2" bonus_game_type="bought" bonus_game_sub_type="0"/><user_new cash="250"/></server>')
  case=start_case(initial,entry,request,1000);self.assertTrue(case['purchase_binding']);self.assertFalse(settle(case)['passed'])
  for remaining,cashwin,total,wallet in [(1,20,20,270),(0,30,50,300)]:
   r=parse(f'<server command="bet" status="ok"><state current_state="{"idle"if remaining==0 else"fs"}"/><game cash-bet="0" cash-bet-game="10" cash-win="{cashwin}" free-win="{total}" bonus_games="{remaining}"/><user_new cash="{wallet}"/></server>')
   case['steps'].append(snapshot(r,'free_bet'))
  settle(case);self.assertEqual((case['cost_minor'],case['win_minor'],case['after_minor']),(750,50,300));self.assertTrue(case['passed'])
  case['steps'][1]['native_cash_bet_minor']=10;self.assertFalse(settle(case)['passed'])

 def test_demo_reconnect_adjustment_is_separate_from_winnings(self):
  from playson_contract import start_case,snapshot
  initial=parse(FIX[1]['initial']);request=parse('<client command="bet"><bet cash="2"/></client>')
  reply=parse('<server command="bet" status="ok"><state current_state="idle"/><game cash-bet="20" cash-bet-game="20" cash-win="0"/><user_new cash="1080"/></server>')
  reply.find('user_new').set('cash','980');reply.find('state').set('current_state','bonus');reply.set('status','bonus');c=start_case(initial,reply,request,1000)
  final=parse('<server command="bonus" status="bet"><state current_state="idle"/><bonus win="0"/><user_new cash="1080"/></server>');c['steps'].append(snapshot(final,'bonus'));self.assertFalse(settle(c)['passed'])
  c['demo_reconnect_adjustments']=[{'kind':'observed_test_reconnect_reset','before_minor':980,'after_minor':1080,'fixed_test_credit_minor':1080,'delta_minor':100,'ordinal':1}]
  settle(c);self.assertTrue(c['passed']);self.assertEqual(c['win_minor'],0)
  c['demo_reconnect_adjustments'][0]['delta_minor']=99;self.assertFalse(settle(c)['passed'])

 def test_legacy_quote_requires_source_bound_client_multiplier(self):
  r=parse(FIX[0]['initial']);r.find('game').attrib.pop('total_bet_mult')
  with self.assertRaises(ValueError):quote(r)
  q=quote(r,native_multiplier=20);self.assertEqual(q['base_cost_minor'],20);self.assertEqual(q['multiplier_origin'],'native_client_config')
 def test_single_untyped_purchase_uses_the_only_declared_price(self):
  from playson_contract import start_case
  r=parse(FIX[1]['initial']);r.find('game').attrib.pop('buy_feature_cost');r.find('game').set('free_game_cost','30')
  request=parse('<client><bet cash="2"/><buy freegame="true"/></client>')
  reply=parse('<server command="bet" status="bonus"><state current_state="bonus"/><game cash-bet="20" cash-bet-game="20" cash-win="0"/><user_new cash="400"/></server>')
  c=start_case(r,reply,request,1000);self.assertEqual(c['cost_minor'],600);self.assertTrue(c['purchase_binding'])

 def test_purchase_receipt_can_quote_total_cost_in_cash_bet_fields(self):
  from playson_contract import start_case
  initial=parse(FIX[1]['initial']);initial.find('game').set('buy_feature_cost','30,75')
  req=parse('<client><bet cash="2"/><buy freegame="true" type="0"/></client>')
  reply=parse('<server command="bet" status="ok"><state current_state="bonus"/><game cash-bet="600" cash-bet-game="600" cash-win="0"/><user_new cash="400"/></server>')
  c=start_case(initial,reply,req,1000);self.assertTrue(c['purchase_binding']);self.assertTrue(c['entry_base_cost_matches'])
 def test_fs_cascade_payout_uses_cash_packets_and_preserves_counter_difference(self):
  from playson_contract import snapshot
  c={'before_minor':1000,'cost_minor':20,'entry_base_cost_matches':True,'purchase_binding':True,'steps':[]}
  for kind,state,cash,credit,counter in [('paid_entry','fs',0,980,0),('free_bet','respin',0,980,0),('cascade_next','idle',50,1030,49)]:
   r=parse(f'<server command="bet" status="ok"><state current_state="{state}"/><game cash-bet="{20 if kind=="paid_entry"else 0}" cash-win="{cash}" free-win="{counter}" bonus_games="0"/><user_new cash="{credit}"/></server>');c['steps'].append(snapshot(r,kind))
  settle(c);self.assertTrue(c['passed']);self.assertEqual(c['win_minor'],50);self.assertEqual(c['native_free_counter_difference_minor'],-1)

 def test_purchased_choice_requires_a_server_offered_domain(self):
  from playson_contract import start_case
  initial=parse(FIX[1]['initial']);initial.find('game').set('buy_feature_cost','75,400')
  req=parse('<client><bet cash="2"/><buy freegame="true" type="0"/></client>')
  reply=parse('<server command="bet" status="game"><state current_state="choice"/><game cash-bet="20" cash-bet-game="20" cash-win="100" bonus_game_type="bought" bonus_game_sub_type="0"/><player_choice types="0,1"/><user_new cash="600"/></server>')
  self.assertTrue(start_case(initial,reply,req,2000)['purchase_binding']);reply.remove(reply.find('player_choice'));self.assertFalse(start_case(initial,reply,req,2000)['purchase_binding'])

 def test_native_ui_ante_domain_is_bound_when_server_omits_it(self):
  r=parse(FIX[0]['initial']);q=quote(r,native_ante_multipliers=['2','3']);self.assertEqual(q['ante_multipliers'],['2','3']);self.assertEqual(q['ante_domain_origin'],'native_client_config')
  r.find('game').set('chance_booster','1.5')
  with self.assertRaises(ValueError):quote(r,native_ante_multipliers=['2','3'])

 def test_xml_external_entities_are_rejected(self):
  with self.assertRaises(ValueError):parse('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><server/>')
if __name__=='__main__':unittest.main()
