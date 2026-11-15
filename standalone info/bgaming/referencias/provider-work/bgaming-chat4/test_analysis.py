import json, unittest, copy
from pathlib import Path
from analyze import normalize, Sanitizer
P=Path(__file__).parent
def load(n):return json.loads((P/n).read_text(encoding='utf-8-sig'))
class CapturedEvidence(unittest.TestCase):
 def test_reconciliation(self):
  r=load('reconciliation.json');self.assertEqual(len(r['checks']),199)
  self.assertTrue(all(x['ok'] for x in r['checks']))
  for gid in ('GoldRushWithJohnny','StPatricksPotsHoldAndWin'):
   rows=load(gid+'.normalized.json');rounds=[x for x in r['rounds'] if x['game']==gid]
   self.assertTrue(all(x['closed'] and x['win_native']==x['final_game_native'] for x in rounds))
   self.assertEqual(100000-sum(x['cost_native'] for x in rounds)+sum(x['win_native'] for x in rounds),rows[-1]['wallet']+rows[-1]['game_balance'])
 def test_mutation_detected(self):
  rows=load('GoldRushWithJohnny.normalized.json');a=next(x for x in rows if x['entry']==677);b=copy.deepcopy(next(x for x in rows if x['entry']==678))
  self.assertEqual(a['wallet']+a['game_balance']-30,b['wallet'])
  b['wallet']+=1;self.assertNotEqual(a['wallet']+a['game_balance']-30,b['wallet'])
 def test_continuations(self):
  rounds=load('reconciliation.json')['rounds'];special=[x for x in rounds if x['feature'] and len(x['commands'])>1]
  self.assertEqual([len(x['commands'])-1 for x in special],[20,7,12,11,5])
  self.assertEqual([x['cost_native'] for x in special],[1500,1200,10000,2000,700])
 def test_native_normalizer(self):
  for gid in ('GoldRushWithJohnny','StPatricksPotsHoldAndWin'):
   self.assertEqual([normalize(x) for x in load(gid+'.reference.json')],load(gid+'.normalized.json'))
 def test_catalog_coverage(self):
  c=load('catalog.json');self.assertEqual(len(c['games']),25);self.assertEqual(sum(x['game_id'] is not None for x in c['games']),21)
  self.assertEqual([x['status'] for x in c['coverage']['pages']],[0,200])
 def test_sanitizer(self):
  s=Sanitizer();v=s.clean({'t_key':'secret','launch_token':'secret','round_id':123,'bet':30,'win':84})
  self.assertEqual(v,{'t_key':'[REDACTED]','launch_token':'[REDACTED]','round_id':'round_id-1','bet':30,'win':84})
  self.assertEqual(s.clean({'round_id':123})['round_id'],'round_id-1')
if __name__=='__main__':unittest.main()
