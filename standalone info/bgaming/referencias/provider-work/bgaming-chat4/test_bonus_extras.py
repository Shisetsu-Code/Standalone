import unittest,copy
from unittest.mock import patch
from run_demo_qa import Demo
class BonusExtras(unittest.TestCase):
 def state(self,wallet=10000,prices=None):return {'balance':{'wallet':wallet,'game':0},'flow':{'state':'freespins','available_actions':['init','freespin','buy_extra_bonus']},'features':{'bonus_data':{'bonus_game_prices':prices or {'extra_spin':221,'extra_board':664,'extra_multiplier':None,'regenerate_bonus':None}}}}
 def test_each_offered_extra_once_then_freespins_no_new_spin(self):
  d=Demo({'game_id':'FrozenFruit'});d.protocol_metadata={'extra_bonus_command_verified':True,'extra_bonus_types':['extra_spin','extra_board','extra_multiplier','regenerate_bonus']};d.active_mode={};calls=[];current=self.state()
  def call(command,options=None):
   nonlocal current
   calls.append((command,options));current=copy.deepcopy(current)
   if command=='buy_extra_bonus':
    name=options['bonus_type'];current['balance']['wallet']-=current['features']['bonus_data']['bonus_game_prices'][name];current['features']['bonus_data']['last_purchased_extra_bonus']=name
   elif command=='freespin':current['flow']={'state':'closed','available_actions':['init','spin']}
   else:self.fail('Unexpected wager command')
   d.events.append({'request':{'command':command},'response':current});return current
  d.call=call;result=d.settle(current);self.assertEqual([c[0] for c in calls],['buy_extra_bonus','buy_extra_bonus','freespin']);self.assertEqual(result['balance']['wallet'],9115);self.assertEqual(d.active_extra_types,{'extra_spin','extra_board'});self.assertTrue(all(c['ok'] for c in d.money_checks))
 def test_unknown_optional_choice_does_not_send_anything(self):
  d=Demo({'game_id':'Unknown'});d.call=lambda *a:self.fail('Unexpected request')
  with patch('legacy_metadata.prove_default',return_value={'extra_bonus_command_verified':False}):
   with self.assertRaises(RuntimeError):d.settle(self.state())
 def test_optional_source_modes_remain_partial_until_all_exercised(self):
  from run_demo_qa import completion_status
  report={'modes':[{'status':'closed','extra_types_offered':['extra_spin'],'extra_types_tested':['extra_spin']}]};meta={'extra_bonus_command_verified':True,'extra_bonus_types':['extra_spin','regenerate_bonus']}
  self.assertEqual(completion_status(report,meta),'partial');self.assertEqual(report['bonus_mode_coverage']['pending'][0]['bonus_type'],'regenerate_bonus')
if __name__=='__main__':unittest.main()
