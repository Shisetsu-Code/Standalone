import unittest
from lucky_birds import metadata,plan,closed_result
class LuckyBirds(unittest.TestCase):
 def test_three_literal_birds_and_complete_round_wire(self):
  s='a.birdColor="red",b.birdColor="orange",c.birdColor="blue";req:{bet:t,action:"start"};req:{bet:e,action:"step",bird:t};req:{bet:t,action:"cashout"};P.resp.win'
  m=metadata(s);a={'result':{'currency':'FUN','currency_attributes':{'subunits':100},'balance':100000,'state':None,'freebets':None,'config':{'bet_limits':[100,200]}}};self.assertEqual([x['bird'] for x in plan(a,m)],['red','orange','blue'])
  with self.assertRaises(ValueError):metadata(s.replace('birdColor="blue"','birdColor="green"'))
 def test_native_cashout_and_crash_round_balance(self):
  self.assertTrue(closed_result(10000,100,{'balance':10100,'final':True,'resp':{'result':'win','win':200}})['ok'])
  self.assertTrue(closed_result(10000,100,{'balance':9900,'final':True,'resp':{'result':'crash'}})['ok'])
  with self.assertRaises(ValueError):closed_result(10000,100,{'balance':9901,'final':True,'resp':{'result':'crash'}})
