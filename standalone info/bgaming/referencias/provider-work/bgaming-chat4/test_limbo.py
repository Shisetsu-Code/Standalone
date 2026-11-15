import unittest,json
from pathlib import Path
from limbo import metadata,plan,settled
class Limbo(unittest.TestCase):
 def test_native_multiplier_units_and_quick_controls(self):
  s='c:"LimboXYScene",p:{targetMultiplierMin:1.05,targetMultiplierMax:1e4,targetMultiplierQuickBets:"1.05, 5, 10, 100"};command:"spin",options:{bet:this.totalBet,player_multiplier:Math.round(100*x.playerMultiplier)};x.result.win-x.result.bet'
  m=metadata(s);a=json.loads((Path(__file__).parent/'live/Limbo.json').read_text(encoding='utf8'))['events'][0]['response'];modes=plan(a,m)
  self.assertEqual([x['options']['player_multiplier'] for x in modes],[105,500,1000,10000]);self.assertEqual({x['cost_native'] for x in modes},{100})
  with self.assertRaises(ValueError):metadata(s.replace('Math.round(100*','Math.round(10*'))
 def test_money_and_terminal_state_require_native_evidence(self):
  r={'balance':10005,'result':{'bet':100,'win':105},'game':{'state':'closed'}}
  self.assertEqual(settled(10000,r,100)['win_native'],105)
  r['balance']=10004
  with self.assertRaises(ValueError):settled(10000,r,100)
