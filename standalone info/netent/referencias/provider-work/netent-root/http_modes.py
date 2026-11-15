"""Native Red Tiger mathModes IDs and one-debit demo settlement checks."""
from decimal import Decimal, InvalidOperation


def mode_plan(game):
    modes = [{'mode': 'Spin', 'id': 0, 'factor': '1', 'kind': 'normal'}]
    complete = not game.get('hasChoices') and not game.get('hasGambleGame')
    seen = {0}
    for item in game.get('mathModes') or []:
        try:
            identifier = item['id']
            factor = Decimal(str(item['priceMultiplier']))
            if type(identifier) is not int or identifier in seen or not factor.is_finite() or factor <= 0:
                complete = False
                continue
            seen.add(identifier)
            modes.append({'mode': str(item['name']) + ':' + str(identifier), 'id': identifier,
                          'factor': str(factor), 'kind': item['type']})
        except (KeyError, TypeError, ValueError, InvalidOperation):
            complete = False
    if game.get('hasFeatureBuy') and not any(m['kind'] == 'featureBuy' for m in modes):
        complete = False
    if game.get('gameModes') and not game.get('mathModes'):
        complete = False
    return modes, complete


def reconcile_mode(request, response, previous, mode, *, configuration=None):
    result = response['result']; game = result['game']; cash = result['user']['balance']['cash']
    before, debit, after = (Decimal(str(cash[k])) for k in ['atStart', 'afterBet', 'atEnd'])
    stake = Decimal(str(request['stake'])); factor = Decimal(mode['factor']); cost = stake * factor
    win = Decimal(str(game['win']['total']))
    configuration = configuration or {}
    def pending_choice(value):
        if isinstance(value,dict):
            choices=value.get('choices')
            if isinstance(choices,dict) and choices.get('available'):return True
            return any(pending_choice(v) for v in value.values())
        return isinstance(value,list) and any(pending_choice(v) for v in value)
    no_pending=(not pending_choice(result) and not (configuration.get('hasChoices') and result.get('bonusChance'))
                and game.get('nextAction') in [None,'spin'] and not game.get('pending'))
    persistent_atomic = (configuration.get('stateful') is True and game.get('spinMode') in ['Normal','FreeSpins','FreeSpin','Respins','Respin']
        and not configuration.get('hasGambleGame'))
    checks = {'success': response['success'] is True, 'demo': request['playMode'] == 'demo',
              'continuity': before == Decimal(str(previous)), 'native_mode_id': request['gameMode'] == mode['id'],
              'no_promotional_bonus': request.get('bonusId') is None,
              'request_stake_matches_game': stake == Decimal(str(game['stake'])),
              'debit': before - cost == debit, 'credit': debit + win == after,
              'wallet_ledger': before - cost + win == after, 'nonnegative_credit': win >= 0,
              'round_settled': no_pending and (game.get('hasState') is False or persistent_atomic)}
    return {'before': str(before), 'debit': str(debit), 'after': str(after), 'cost': str(cost),
            'win': str(win), 'checks': checks, 'passed': all(checks.values())}
