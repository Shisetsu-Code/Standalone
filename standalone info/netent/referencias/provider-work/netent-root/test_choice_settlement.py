import unittest
from choice_settlement import reconcile_choice

class ChoiceSettlementTests(unittest.TestCase):
    def test_one_paid_entry_then_a_free_collect_credits_root_win_once(self):
        first={'success':True,'result':{'user':{'balance':{'cash':{'atStart':'10000','afterBet':'9999.9','atEnd':'9999.9'}}},'game':{'stake':'0.1','choices':{'available':['collect','gamble']}}}}
        last={'success':True,'result':{'user':{'balance':{'cash':{'atStart':'9999.9','afterBet':'9999.9','atEnd':'10000.4'}}},'game':{'stake':'0.1','win':{'total':'0.5'},'choices':{'selected':'collect','available':None},'hasState':False}}}
        result=reconcile_choice(first,last,'10000','0.1','collect',['collect','gamble'])
        self.assertTrue(result['passed']);self.assertEqual(result['cost'],'0.1');self.assertEqual(result['win'],'0.5')
        history=[{'requested':'gamble','selected_echo':'collect','success':True},
                 {'requested':'collect','selected_echo':'collect','success':True}]
        self.assertFalse(reconcile_choice(first,last,'10000','0.1','collect',['collect','gamble'],response_history=history)['passed'])
        history=[{'requested':'gamble','selected_echo':'gamble','success':True,
                  'wallet':{'atStart':'9999.9','afterBet':'9999.8','atEnd':'9999.9'},'offered_options':['collect','gamble']},
                 {'requested':'collect','selected_echo':'collect','success':True,
                  'wallet':last['result']['user']['balance']['cash'],'offered_options':['collect','gamble']}]
        self.assertFalse(reconcile_choice(first,last,'10000','0.1','collect',['collect','gamble'],response_history=history)['passed'])
        history[0]['wallet']['afterBet']='9999.9'
        self.assertTrue(reconcile_choice(first,last,'10000','0.1','collect',['collect','gamble'],response_history=history)['passed'])
        last['result']['user']['balance']['cash']['afterBet']='9999.8'
        self.assertFalse(reconcile_choice(first,last,'10000','0.1','collect',['collect','gamble'])['passed'])
