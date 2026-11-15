import copy
import json
from pathlib import Path
import unittest
import protocol

ROOT=Path(__file__).resolve().parent.parent

class ConditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api=json.loads((ROOT/'private/bloody-har/api.json').read_text(encoding='utf8'))
        cls.info=next(x['response'] for x in cls.api if x['path']=='/game/info')

    def test_all_captured_extra_prices_match_state_bound_request(self):
        self.assertTrue(hasattr(protocol,'extra_spin_request'),'state-bound Buy contract missing')
        previous=None;count=0
        for item in self.api:
            if item['path']!='/game/play':continue
            action=item['request']['action']
            if action.startswith('extra_spin_'):
                self.assertEqual(protocol.extra_spin_request('bloody-mary',previous['response'],self.info,action),item['request'])
                self.assertAlmostEqual(previous['response']['balance']-item['request']['bet'],item['response']['balance'])
                count+=1
            previous=item
        self.assertEqual(count,56)

    def test_changed_price_and_unadvertised_buy_are_rejected(self):
        self.assertTrue(hasattr(protocol,'extra_spin_request'),'state-bound Buy contract missing')
        parent=next(x['response'] for x in self.api if x['path']=='/game/play' and x['request']['action']=='buy_FS_3SC')
        changed=copy.deepcopy(parent)
        next(x for x in changed['wager']['data'][-1]['pending_actions'] if x['kind']=='Buy')['cost']+=1
        with self.assertRaises(ValueError):protocol.extra_spin_request('bloody-mary',changed,self.info,'extra_spin_fs')
        with self.assertRaises(ValueError):protocol.extra_spin_request('bloody-mary',parent,self.info,'extra_spin_sfs')
        with self.assertRaises(ValueError):protocol.extra_spin_request('another-game',parent,self.info,'extra_spin_fs')

    def test_compound_captured_rounds_sum_every_debit_and_payout(self):
        for action in ['buy_FS_3SC','buy_SFS_3SC']:
            root=next(x for x in self.api if x['path']=='/game/play' and x['request']['action']==action)
            rid=root['response']['roundId']
            continuations=[{'request':x['request'],'response':x['response']} for x in self.api if x['path']=='/game/play' and x['request'].get('roundId')==rid]
            complete=next(x for x in self.api if x['path']=='/game/complete' and x['request']['roundId']==rid)
            expected_cost=root['request']['bet']+sum(x['request'].get('bet',0) for x in continuations)
            result=protocol.audit_round(root['response']['balance']+root['request']['bet'],self.info,root['request'],root['response'],complete['request'],complete['response'],continuations)
            self.assertEqual(result['cost'],expected_cost)
            self.assertEqual(result['balance_after'],complete['response']['balance'])

if __name__=='__main__':unittest.main()
