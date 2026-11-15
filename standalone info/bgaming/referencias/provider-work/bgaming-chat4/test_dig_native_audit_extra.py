import copy,json,unittest
from pathlib import Path
from bonus_choices_extra import audit_dig,metadata
ROOT=Path(__file__).resolve().parent;PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def fixture():
 archive=ROOT/'live/attempts/DigDigDigger.before-received-dig-loss-classification.json';r=json.loads((archive if archive.exists() else ROOT/'live/DigDigDigger.json').read_text(encoding='utf8'));r['events']=r['events'][:3];r['protocol_metadata']['dig_choice_source']=metadata('DigDigDigger',next((PRIVATE/'research/legacy/DigDigDigger').rglob('bundle.js')).read_text(encoding='utf8'));return r
class DigAudit(unittest.TestCase):
 def test_repeated_outcome_win_on_gamble_is_not_an_extra_prize(self):
  r=fixture();r['events'][2]['response']['balance']['wallet']=99990;result=audit_dig(r);self.assertEqual(result['failed'],0);self.assertEqual(result['checks'][-1]['expected_native'],{'wallet':99990,'game':0})
 def test_received_actual_wallet_discontinuity_remains_failed(self):
  r=fixture();original=copy.deepcopy(r);result=audit_dig(r);self.assertGreater(result['failed'],0);self.assertTrue(any(c.get('event')==2 and not c['ok'] for c in result['checks']));self.assertEqual(r,original)
 def test_only_explicit_init_resets_next_paid_baseline_and_does_not_supersede_failure(self):
  r=fixture();init=copy.deepcopy(r['events'][0]);init['response']['balance']={'wallet':100000,'game':0};r['events'].append(init);spin=copy.deepcopy(r['events'][1]);spin['response']['balance']={'wallet':99990,'game':0};spin['response']['outcome']['win']=0;spin['response']['flow'].update(state='closed',available_actions=['init','spin']);r['events'].append(spin);result=audit_dig(r);self.assertTrue(any(c.get('event')==2 and not c['ok'] for c in result['checks']));self.assertTrue(any(c.get('event')==3 and c.get('baseline_reset') and not c['ok'] for c in result['checks']));self.assertTrue(any(c.get('event')==4 and c['kind']=='dig_paid_native_balance' and c['ok'] for c in result['checks']))
 def test_purchase_cost_comes_from_native_whitelist_tier_and_ceil_source_not_reported_cost(self):
  r=fixture();r['events'][2]['response']['balance']['wallet']=99990;spin=copy.deepcopy(r['events'][1]);spin['request']['options']={'bet':10,'purchased_feature':'freespin_buy','purchased_feature_level':'1'};spin['response']['balance']={'wallet':98890,'game':0};spin['response']['outcome']['win']=0;spin['response']['flow'].update(state='freespins',available_actions=['init','freespin'],purchased_feature={'name':'freespin_buy','level':'1'});r['events'].append(spin);result=audit_dig(r);self.assertEqual(result['failed'],0);self.assertEqual(result['checks'][-1]['cost_native'],1100);spin['request']['options']['purchased_feature_level']='10';self.assertGreater(audit_dig(r)['failed'],0)
 def test_unknown_purchase_and_failed_action_do_not_raise_or_become_accepted(self):
  r=fixture();r['events'][2]['response']['balance']['wallet']=99990;spin=copy.deepcopy(r['events'][1]);spin['request']['options']={'bet':10,'purchased_feature':'global_only'};r['events'].append(spin);r['events'].append({'request':{'command':'spin'},'status':'uncertain'});result=audit_dig(r);self.assertGreaterEqual(result['failed'],2);self.assertEqual(result['game_id'],'DigDigDigger')
if __name__=='__main__':unittest.main()
