import unittest
import importlib.util
from pathlib import Path
from decimal import Decimal

spec=importlib.util.spec_from_file_location('horizon_contract',Path(__file__).with_name('horizon_contract.py'))
contract=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists(): spec.loader.exec_module(contract)

class BalanceTests(unittest.TestCase):
    def test_free_round_restore_requires_same_wallet_and_native_state(self):
        validate=getattr(contract,'validate_restore',None);self.assertIsNotNone(validate)
        expected={'nextAction':'freespin','wins':{'total':.12},'game':{'totalKeys':1}}
        validate(expected,dict(expected),'995','995')
        with self.assertRaises(ValueError):validate(expected,dict(expected),'995','990')
        with self.assertRaises(ValueError):validate(expected,{**expected,'nextAction':'spin'},'995','995')
        restored={**expected,'game':{**expected['game'],'featureBuyEnabled':True}}
        validate(expected,restored,'995','995',initial_game={'featureBuyEnabled':True})
        with self.assertRaises(ValueError):validate(expected,restored,'995','995',initial_game={'featureBuyEnabled':False})

    def test_demo_wallet_array_is_used_instead_of_generic_zero(self):
        extract=getattr(contract,'demo_balance',lambda frame:None)
        packet={'payload':{'type':'balanceUpdated','args':{'balance':0,'currencyCode':'USD','balances':[{'id':'demo-test-session','amount':1000,'version':1}]}}}
        self.assertEqual(extract(packet),{'amount':Decimal('1000'),'currency':'USD','version':1})

    def test_generic_balance_without_demo_wallet_is_not_certified(self):
        extract=getattr(contract,'demo_balance',lambda frame:'not implemented')
        self.assertIsNone(extract({'payload':{'type':'balanceUpdated','args':{'balance':1000,'balances':[{'id':'real-session','amount':1000}]}}}))

    def test_ante_cost_and_wallet_equation(self):
        reconcile=getattr(contract,'reconcile',lambda **kwargs:{'passed':False})
        self.assertTrue(reconcile(stake='0.2',factor='1.5',before='999.8',debit='999.5',after='1000',win='0.5',closed=True)['passed'])

    def test_unresolved_or_wrong_balance_is_retained_as_failed(self):
        reconcile=getattr(contract,'reconcile',lambda **kwargs:{'passed':True})
        for after,closed in [('999.9',True),('1000',False)]:
            self.assertFalse(reconcile(stake='0.2',factor='1.5',before='999.8',debit='999.5',after=after,win='0.5',closed=closed)['passed'])

    def test_free_continuations_never_create_another_paid_play(self):
        details=getattr(contract,'continuation_details',lambda action:None)
        for action in ['respin','freespin','featureexecution','jackpotpayout']:
            self.assertEqual(details(action),{'continue':{}})
        for action in ['spin','userdecision','unknown']:
            with self.assertRaises(ValueError):details(action)

    def test_unchanged_prior_settlement_is_not_the_new_debit(self):
        extract=getattr(contract,'first_changed_balance',lambda before,steps:None)
        self.assertEqual(extract('999.9',[{'amount':'999.9'},{'amount':'998.9'},{'amount':'998.9'}]),'998.9')

    def test_first_wrong_changed_debit_is_not_replaced_with_a_later_match(self):
        extract=getattr(contract,'first_changed_balance',lambda before,steps:None)
        self.assertEqual(extract('100',[{'amount':'100'},{'amount':'97'},{'amount':'99'}]),'97')

if __name__=='__main__': unittest.main()
