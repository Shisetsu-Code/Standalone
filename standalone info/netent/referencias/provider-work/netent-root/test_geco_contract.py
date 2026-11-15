import unittest
from geco_contract import parse, minimum_bet, spin_parameters, reconcile_round,free_parameters,validate_restore


class GecoTests(unittest.TestCase):
    def test_legacy_allowedactions_is_normalized_only_for_a_closed_single_spin(self):
        self.assertEqual(parse('allowedactions=spin&gameover=true')['nextaction'],'spin')
        self.assertNotIn('nextaction',parse('allowedactions=spin,collect&gameover=false'))

    def test_drop_resume_has_no_wager_and_requires_same_saved_round(self):
        self.assertEqual(free_parameters('drop'),{'action':'drop','wantsreels':'true'})
        with self.assertRaises(ValueError):free_parameters('spin')
        expected={'credit':'99985','nextaction':'drop','totalwin.cents':'15','gamestate.current':'basic'}
        restored={**expected,'playforfun':'true'}
        validate_restore(expected,restored)
        restored['credit']='99970'
        with self.assertRaises(ValueError):validate_restore(expected,restored)
    def initial(self):
        return parse('playforfun=true&credit=100000&denomination.all=1,2,5&betlevel.all=1,2&bl.standard=0,1,2&bl.i0.coins=1&bl.i1.coins=1&bl.i2.coins=1&gameover=true&nextaction=spin')

    def test_minimum_uses_native_line_coin_weights_and_cents(self):
        initial=self.initial();bet=minimum_bet(initial)
        self.assertEqual(bet['cost_cents'],3)
        self.assertEqual(spin_parameters(bet),{'bet.betlevel':1,'bet.denomination':1,'bet.betlines':'0-2'})
        initial['bl.i2.coins']='2'
        self.assertEqual(minimum_bet(initial)['cost_cents'],4)
        initial['bl.i1.coins']='0'
        self.assertEqual(minimum_bet(initial)['cost_cents'],3)

    def test_root_bonus_total_is_credited_once_and_closure_is_explicit(self):
        initial=self.initial();bet=minimum_bet(initial)
        final=parse('credit=100017&totalwin.cents=20&gameover=true&nextaction=spin')
        result=reconcile_round(initial,final,bet)
        self.assertTrue(result['passed']);self.assertEqual(result['win'],'0.2')
        final['credit']='99570'
        self.assertTrue(reconcile_round(initial,final,bet,factor=150)['passed'])
        final['credit']='100017'
        final['gameover']='false'
        self.assertFalse(reconcile_round(initial,final,bet)['passed'])
        final['gameover']='true';final['credit']='100037'
        self.assertFalse(reconcile_round(initial,final,bet)['passed'])

    def test_real_mode_and_invalid_denominations_are_rejected_before_play(self):
        initial=self.initial();initial['playforfun']='false'
        with self.assertRaises(ValueError):minimum_bet(initial)
        initial['playforfun']='true';initial['denomination.all']='0,1'
        with self.assertRaises(ValueError):minimum_bet(initial)

    def test_feature_bet_advertised_with_separators_requires_native_review(self):
        from geco_contract import unreviewed_stake_options
        self.assertEqual(unreviewed_stake_options({'supports_feature_bet':'true','feature.bet':'false'}),['supports_feature_bet'])
        self.assertEqual(unreviewed_stake_options({'featureBuy':'false','feature.bet':'false'}),[])
        self.assertEqual(unreviewed_stake_options({'gamble.enabled':'true','bet.hotlines':'0'}),['gamble.enabled'])

    def test_ways_selector_uses_native_id_and_minimum_cost_not_line_index(self):
        i=self.initial();i['bl.standard']='243'
        for k in list(i):
            if k.startswith('bl.i'):del i[k]
        for n,(identifier,coins) in enumerate([(3,1),(9,3),(27,8),(81,15),(243,25)]):
            i[f'bl.i{n}.id']=str(identifier);i[f'bl.i{n}.coins']=str(coins);i[f'bl.i{n}.line']='0/1/2,1,1,1,1'
        self.assertEqual(minimum_bet(i)['lines'],'3')
        self.assertEqual(minimum_bet(i)['cost_cents'],1)
        for k in list(i):
            if k.startswith('bl.i') and not k.startswith('bl.i0.'):del i[k]
        i['bl.i0.id']='243';i['bl.i0.coins']='25'
        self.assertEqual(minimum_bet(i)['lines'],'243')
        self.assertEqual(minimum_bet(i)['cost_cents'],25)

    def test_native_math_mode_selector_is_not_silently_omitted(self):
        from geco_contract import unreviewed_stake_options
        self.assertEqual(unreviewed_stake_options({'mathModes':'classic,max','mathMode':'null'}),['mathModes'])

    def test_reviewed_native_config_can_override_geometric_line_coin_total(self):
        initial=self.initial()
        bet=minimum_bet(initial,native_cost_coins=25)
        self.assertEqual(bet['cost_cents'],25)
        final=parse('credit=99975&totalwin.cents=0&gameover=true&nextaction=spin')
        self.assertTrue(reconcile_round(initial,final,bet)['passed'])
        with self.assertRaises(ValueError):minimum_bet(initial,native_cost_coins=0)

    def test_gambling_flag_and_non_indexed_selector_require_review(self):
        from geco_contract import unreviewed_stake_options
        self.assertEqual(unreviewed_stake_options({'FEATURE_GAMBLING':'true','bl.standard':'243'}),['FEATURE_GAMBLING','native_betline_selector'])

    def test_native_subsequent_request_preserves_auth_prefix_but_not_init_jurisdiction(self):
        from geco_contract import native_base_parameters
        query={'sessid':'demo-fixture','gameId':'slot-fixture','ne_mode':'demo','ne_evo_token':'fixture-token','jurisdictionCode':'CH','gameInit':'false','action':'init','bet.betlevel':'1'}
        self.assertEqual(native_base_parameters(query),{'sessid':'demo-fixture','gameId':'slot-fixture','ne_mode':'demo','ne_evo_token':'fixture-token'})
