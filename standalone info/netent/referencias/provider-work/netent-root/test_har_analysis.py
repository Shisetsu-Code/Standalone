import unittest
from har_analysis import reconcile


class RoundTests(unittest.TestCase):
    def sample(self):
        return ({'playMode':'demo','stake':2,'gameMode':0,'bonusId':None},
                {'success':True,'result':{'user':{'balance':{'cash':{'atStart':'9994.00','afterBet':'9992.00','atEnd':'10034.20'}}},
                 'game':{'stake':'2.00','win':{'total':'42.20'},'hasState':False,'spinMode':'Normal',
                         'respin':[{'spinMode':'Respin','win':{'total':'42.20'},
                                    'freeSpins':[{'spinMode':'FreeSpin','win':{'total':'35.60'}}]}]}}})

    def test_nested_bonus_is_one_wallet_credit(self):
        request,response=self.sample();r=reconcile(request,response,'9994.00')
        self.assertTrue(r['passed']);self.assertEqual(r['credit'],'42.20')
        self.assertEqual(len(r['internal_steps']),2)
        self.assertEqual(r['closing_balance'],'10034.20')

    def test_balance_or_continuity_discrepancy_stays_failed(self):
        request,response=self.sample();self.assertFalse(reconcile(request,response,'9993.00')['passed'])
        response['result']['user']['balance']['cash']['atEnd']='10076.40'
        self.assertFalse(reconcile(request,response,'9994.00')['passed'])

    def test_open_state_and_non_demo_are_not_certified(self):
        request,response=self.sample();response['result']['game']['hasState']=True
        self.assertFalse(reconcile(request,response,'9994.00')['passed'])
        response['result']['game']['hasState']=False;request['playMode']='real'
        self.assertFalse(reconcile(request,response,'9994.00')['passed'])
