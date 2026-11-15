"""Observed Horizon contracts; no network or financial requests generated."""
from decimal import Decimal


def demo_balance(packet):
    body = packet.get('payload',packet)
    if body.get('type') != 'balanceUpdated': return None
    args=body.get('args',{})
    wallets=[item for item in args.get('balances',[]) if str(item.get('id','')).startswith('demo-')]
    if len(wallets)!=1: return None
    item=wallets[0]
    return {'amount':Decimal(str(item['amount'])),'currency':args.get('currencyCode'),'version':item.get('version')}


def reconcile(*,stake,factor,before,debit,after,win,closed):
    stake,factor,before,debit,after,win=map(lambda x:Decimal(str(x)),(stake,factor,before,debit,after,win))
    cost=stake*factor
    checks={'positive_stake':stake>0,'positive_factor':factor>0,
            'debit_matches_cost':before-debit==cost,
            'wallet_matches_root_win':after==before-cost+win,
            'round_closed':closed is True}
    return {'stake':str(stake),'factor':str(factor),'cost':str(cost),'before':str(before),
            'debit':str(debit),'after':str(after),'win':str(win),'checks':checks,'passed':all(checks.values())}


def continuation_details(action):
    # Native commons.ne bundle a7f77a30: non-Spin executes sendContinueRequest;
    # userdecision requires its game-specific interaction payload first.
    if action not in {'respin','freespin','featureexecution','jackpotpayout'}:
        raise ValueError('Unreviewed continuation or player decision')
    return {'continue':{}}


def first_changed_balance(before,steps):
    opening=Decimal(str(before))
    for step in steps:
        if Decimal(str(step['amount']))!=opening:return str(step['amount'])
    # No separately observed debit: retain the opening amount so the cost check
    # fails instead of inferring or manufacturing a debit from the expected cost.
    return str(before)


def validate_restore(expected,actual,expected_wallet,actual_wallet,*,initial_game=None):
    if Decimal(str(expected_wallet))!=Decimal(str(actual_wallet)):
        raise ValueError('Restored demo wallet differs')
    for key in ['nextAction','wins','symbols','freeSpins','game','nextData']:
        restored=actual.get(key)
        if key=='game' and isinstance(restored,dict) and isinstance(expected.get(key),dict):
            restored=dict(restored)
            for field in set(restored)-set(expected[key]):
                if field in {'payouts','featureBuyMultiplier','freeSpins','featureBuyEnabled'} and initial_game and field in initial_game and restored[field]==initial_game[field]:
                    restored.pop(field)
        if expected.get(key)!=restored:raise ValueError('Restored native state differs at '+key)
