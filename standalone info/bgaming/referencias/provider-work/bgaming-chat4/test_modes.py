import json,unittest,copy
from pathlib import Path
from run_demo_qa import modes_from_init, trusted, Demo
from analyze import Sanitizer
P=Path(__file__).parent
class ModeDiscovery(unittest.TestCase):
 def init(self,gid):return next(x['response'] for x in json.loads((P/(gid+'.reference.json')).read_text(encoding='utf8')) if x['request']['command']=='init')
 def test_semantic_player_bets_preserved(self):
  self.assertEqual(Sanitizer().clean({"player":1.95,"player_pair":13,"player_id":"private"}),{"player":1.95,"player_pair":13,"player_id":"[REDACTED]"})
 def test_baccarat_declared_types(self):
  init=json.loads((P/"ClassicBaccarat.init.reference.json").read_text(encoding='utf8'))["response"]
  modes=modes_from_init(init);self.assertEqual(len(modes),10);self.assertEqual(modes[0]["options"],{"bets":[{"type":"player","amount":100}]});self.assertEqual(modes[-1]["command"],"demo_play");self.assertEqual(modes[-1]["cost_native"],0)
 def test_sugar_plinko_modes(self):
  init=json.loads((P/"SugarPlinko.init.reference.json").read_text(encoding='utf8'))["response"]
  modes=modes_from_init(init);self.assertEqual(len(modes),216);self.assertEqual({x["cost_native"] for x in modes},{10,12,14,16,18,20});self.assertEqual(sum(not x["options"]["purchased_feature"] for x in modes),27)
 def test_baccarat_side_bet_limit(self):
  init=json.loads((P/"ClassicBaccarat.init.reference.json").read_text(encoding='utf8'))["response"]
  modes=modes_from_init(init);side=next(x for x in modes if x["name"]=="bet:player_pair");self.assertEqual(side["cost_native"],200);self.assertEqual(len(side["options"]["bets"]),2)
 def test_plinko_multi_outcome_conservation(self):
  fixture=json.loads((P/"SugarPlinko.respin.reference.json").read_text(encoding='utf8'));d=Demo({"game_id":"SugarPlinko"});d.prev=fixture["before"]
  def received(command,options):
   d.events.append(fixture["event"]);return fixture["event"]["response"]
  d.call=received
  mode={"command":"play","options":fixture["event"]["request"]["options"],"cost_native":fixture["cost_native"]}
  result=d.run_sugar_mode(mode,fixture["before"]);self.assertEqual(result["win_native"],24);self.assertEqual(result["win_components_native"],[15,9]);self.assertEqual(result["final_balance"],99917);self.assertTrue(d.money_checks[-1]["ok"])
 def test_gold(self):
  m=modes_from_init(self.init('GoldRushWithJohnny'));self.assertEqual([(x['name'],x['cost_native']) for x in m],[('normal',10),('freespin_buy',500),('bonus_buy',400)])
 def test_st_patrick(self):
  m=modes_from_init(self.init('StPatricksPotsHoldAndWin'));self.assertEqual([x['cost_native'] for x in m],[10,14,700,2000,10000]);self.assertEqual([x['options']['purchased_feature_level'] for x in m if 'purchased_feature_level' in x['options']],['0','1','2'])
 def test_reject_other_currency(self):
  r=copy.deepcopy(self.init('GoldRushWithJohnny'));r['options']['currency']['code']='USD'
  with self.assertRaises(ValueError):modes_from_init(r)
 def test_reject_unverified_fraction(self):
  r=copy.deepcopy(self.init('GoldRushWithJohnny'));r['options']['feature_options']['feature_multipliers']['freespin_buy']=1251
  with self.assertRaises(ValueError):modes_from_init(r)
 def test_verified_client_ceiling_only_changes_expected_debit_not_wire_bet(self):
  r=copy.deepcopy(self.init('GoldRushWithJohnny'));r['options']['available_bets']=[10];r['options']['feature_options']['feature_multipliers']={'base_bet':100,'freespin_chance':132,'freespin_buy':1251}
  with self.assertRaises(ValueError):modes_from_init(r)
  modes=modes_from_init(r,{'price_rounding':{'antebet':'ceil','purchase':'ceil'}});self.assertEqual([m['cost_native'] for m in modes],[10,14,126]);self.assertEqual([m['options']['bet'] for m in modes],[10,10,10])
 def test_source_verified_default_feature_denominator(self):
  r=copy.deepcopy(self.init('GoldRushWithJohnny'));r['options']['feature_options']['feature_multipliers']={'freespin_buy':10000}
  with self.assertRaises(ValueError):modes_from_init(r)
  m=modes_from_init(r,{'feature_default_base_bet':100,'source_verified':True});self.assertEqual(m[1]['cost_native'],1000)
 def test_native_rows_kept_for_normal_purchase_and_continuations(self):
  r=json.loads((P/'live/BigTunaBonanza.json').read_text(encoding='utf8'))['events'][0]['response']
  meta={'feature_default_base_bet':100,'source_verified':True,'rows_parameter_verified':True,'rows_feature_level_verified':True,'rows_normal_factors':{'4':'1'}}
  modes=modes_from_init(r,meta);self.assertEqual([x['cost_native'] for x in modes],[10,1000,15]);self.assertTrue(all(x['options']['rows']=='4' for x in modes));self.assertTrue(all(x['continuation_options']=={'rows':'4'} for x in modes))
 def test_rows_normal_price_does_not_double_charge_purchase(self):
  r=json.loads((P/'live/KrakensHunger.json').read_text(encoding='utf8'))['events'][0]['response'];meta={'feature_default_base_bet':100,'source_verified':True,'rows_parameter_verified':True,'rows_feature_level_verified':True,'rows_normal_factors':{'3':'1','4':'2','5':'4'}};modes=modes_from_init(r,meta)
  self.assertEqual([m['cost_native'] for m in modes],[5,600,7,10,1000,15,20,1500,30]);self.assertEqual([m['options']['bet'] for m in modes],[5]*9)
 def test_scratch_fixed_native_stake_uses_play(self):
  r=json.loads((P/'live/CapymaniaGreen.json').read_text(encoding='utf8'))['events'][0]['response'];m=modes_from_init(r,{'fixed_play_verified':True})
  self.assertEqual(m,[{'name':'normal','command':'play','options':{'bet':100,'bonus':False},'cost_native':100}])
 def test_legacy_bootstrap_loads_metadata_without_rpc_branch(self):
  from types import SimpleNamespace
  init=self.init('GoldRushWithJohnny');cfg={'currency':'FUN','server_id':'demo','identifier':'TestDemo','api':'https://demo.bgaming-network.com/api','csrfTokenHeaderName':'X-Test','csrfTokenHeaderValue':'unit-test'}
  class Page:
   url='https://demo.bgaming-network.com/play/TestDemo/FUN?server=demo'
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return ('window.__OPTIONS__='+json.dumps(cfg)).encode()
  demo=Demo({'game_id':'TestDemo','demo_url':Page.url});demo.opener=SimpleNamespace(open=lambda *args,**kwargs:Page());demo.call=lambda command:init
  self.assertEqual(demo.launch(),init)
 def test_reject_untrusted_endpoint(self):
  for u in ['https://example.org/api','http://demo.bgaming-network.com/api','https://demo.bgaming-network.com.evil.org/api']:
   with self.assertRaises(ValueError):trusted(u)
 def test_closed_game_with_unresolved_money_difference_stays_partial(self):
  from run_demo_qa import completion_status
  report={'modes':[{'status':'closed'}],'checks':[{'ok':False}]};self.assertEqual(completion_status(report,{}),'partial')
  report['checks'][0]['superseded']=True;self.assertEqual(completion_status(report,{}),'complete_declared_modes')
 def test_prepared_native_family_bootstraps_without_default_seed(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  gid='HotChilliBells';initial=copy.deepcopy(json.loads((P/'live'/(gid+'.json')).read_text(encoding='utf8'))['events'][0]['response']);initial['options'].pop('default_seed',None);self.assertNotIn('default_seed',initial['options']);meta=json.loads((P/'protocols'/(gid+'.native-variants.json')).read_text(encoding='utf8'));cfg={'currency':'FUN','server_id':'demo','identifier':gid,'api':'https://demo.bgaming-network.com/api','csrfTokenHeaderName':'X-Test','csrfTokenHeaderValue':'unit-test'}
  class Page:
   url='https://demo.bgaming-network.com/play/HotChilliBells/FUN?server=demo'
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return ('window.__OPTIONS__='+json.dumps(cfg)).encode()
  demo=Demo({'game_id':gid,'demo_url':Page.url});demo.opener=SimpleNamespace(open=lambda *args,**kwargs:Page());demo.call=lambda command:initial
  with patch('run_demo_qa.importlib.reload',side_effect=lambda module:module),patch('legacy_metadata.prove_native_variants',return_value=meta):result=demo.launch()
  self.assertEqual(len(modes_from_init(result)),10);self.assertTrue(all(m['options']['bet']==20 for m in modes_from_init(result)))
 def test_purchase_tier_must_be_confirmed_even_when_price_matches(self):
  old={'balance':{'wallet':100000,'game':0},'flow':{'state':'ready','available_actions':['spin']}};mode={'command':'spin','options':{'bet':10,'purchased_feature':'freespin_buy','purchased_feature_level':'1'},'cost_native':1000};d=Demo({'game_id':'Test'});d.call=lambda *args:{'balance':{'wallet':99000,'game':0},'flow':{'state':'closed','purchased_feature':{'name':'freespin_buy','level':'2'}}}
  with self.assertRaises(RuntimeError):d.run_mode(mode,old)
  d=Demo({'game_id':'Test'});d.call=lambda *args:{'balance':{'wallet':99000,'game':0},'flow':{'state':'closed','purchased_feature':{'name':'freespin_buy','level':1}}};self.assertEqual(d.run_mode(mode,old)['status'],'closed')
if __name__=='__main__':unittest.main()
