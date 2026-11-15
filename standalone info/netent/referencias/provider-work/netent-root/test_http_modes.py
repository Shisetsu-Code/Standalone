import unittest
from http_modes import mode_plan, reconcile_mode


class HttpModeTests(unittest.TestCase):
    def test_native_menu_preserves_ids_and_decimal_prices(self):
        modes, complete = mode_plan({'hasFeatureBuy': True, 'mathModes': [
            {'type': 'featureBuy', 'id': 101, 'name': 'FreeSpins', 'priceMultiplier': '150.00'}]})
        self.assertTrue(complete)
        self.assertEqual(modes[1], {'mode': 'FreeSpins:101', 'id': 101, 'factor': '150.00', 'kind': 'featureBuy'})
        self.assertFalse(mode_plan({'hasFeatureBuy': True, 'mathModes': []})[1])

    def test_buy_debits_price_once_and_uses_parent_win(self):
        request = {'playMode': 'demo', 'stake': 0.1, 'gameMode': 101, 'bonusId': None}
        response = {'success': True, 'result': {'user': {'balance': {'cash': {
            'atStart': '10000', 'afterBet': '9985', 'atEnd': '9990'}}},
            'game': {'stake': '0.1', 'win': {'total': '5'}, 'hasState': False,
                     'freeSpins': [{'spinMode': 'FreeSpin', 'win': {'total': '5'}}]}}}
        mode = {'id': 101, 'factor': '150', 'kind': 'featureBuy'}
        result = reconcile_mode(request, response, '10000', mode)
        self.assertTrue(result['passed'])
        self.assertEqual(result['cost'], '15.0')
        self.assertEqual(result['win'], '5')
        response['result']['user']['balance']['cash']['afterBet'] = '9999.9'
        self.assertFalse(reconcile_mode(request, response, '10000', mode)['passed'])
        request['gameMode'] = 102
        self.assertFalse(reconcile_mode(request, response, '10000', mode)['passed'])

    def test_unknown_menu_and_open_state_are_not_complete(self):
        self.assertFalse(mode_plan({'mathModes': [{'id': 101, 'priceMultiplier': '0', 'type': 'featureBuy'}]})[1])
        self.assertFalse(mode_plan({'hasChoices': True})[1])

    def test_persistent_state_is_not_an_unfinished_round(self):
        request = {'playMode': 'demo', 'stake': 0.1, 'gameMode': 0, 'bonusId': None}
        response = {'success': True, 'result': {'user': {'balance': {'cash': {
            'atStart': '10000', 'afterBet': '9999.90', 'atEnd': '9999.90'}}},
            'game': {'stake': '0.1', 'win': {'total': '0'}, 'spinMode': 'Normal', 'hasState': True}}}
        mode = {'id': 0, 'factor': '1', 'kind': 'normal'}
        config = {'stateful': True, 'hasChoices': False, 'hasGambleGame': False}
        self.assertFalse(reconcile_mode(request, response, '10000', mode)['passed'])
        self.assertTrue(reconcile_mode(request, response, '10000', mode, configuration=config)['passed'])
        response['result']['game']['spinMode'] = 'FreeSpins'
        self.assertTrue(reconcile_mode(request, response, '10000', mode, configuration=config)['passed'])
        response['result']['game']['nextAction'] = 'choose'
        self.assertFalse(reconcile_mode(request, response, '10000', mode, configuration=config)['passed'])
        response['result']['game'].pop('nextAction')
        config['hasChoices'] = True
        self.assertTrue(reconcile_mode(request, response, '10000', mode, configuration=config)['passed'])
        response['result']['choices'] = {'available': ['collect','exchange']}
        response['result']['game']['hasState'] = False
        self.assertFalse(reconcile_mode(request, response, '10000', mode, configuration=config)['passed'])
