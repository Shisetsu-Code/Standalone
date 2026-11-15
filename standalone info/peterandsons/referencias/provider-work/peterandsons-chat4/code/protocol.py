"""Native demo normalization and offline wallet audit. No networking."""
from decimal import Decimal
import re

def money(value):
    number=Decimal(str(value))
    if not number.is_finite() or number<0:raise ValueError('invalid_native_amount')
    return number

def take_round_request(game,response):
    if 'take_round' not in response.get('wager',{}).get('next',[]) or not response.get('roundId'):
        raise ValueError('take_action_not_advertised')
    return {'game':game,'provider':'peterandsons','action':'take_round',
            'complete':False,'asyncWin':False,'roundId':response['roundId']}

def extra_spin_request(game,response,info,action):
    if game!='bloody-mary' or action not in ('extra_spin_fs','extra_spin_sfs'):
        raise ValueError('conditional_action_outside_reviewed_contract')
    wager=response.get('wager',{})
    if action not in wager.get('next',[]) or not response.get('roundId'):
        raise ValueError('buy_action_not_advertised')
    step=wager['data'][-1]
    state='SESSION_FS' if action=='extra_spin_fs' else 'SESSION_SFS'
    if step['state']!=state:raise ValueError('conditional_state_mismatch')
    offers=[a for a in step.get('pending_actions',[]) if a.get('name')==action and a.get('kind')=='Buy']
    configs=[a for o in info['config']['per_state'][state]['continuation_offers'] for a in o['actions'] if a.get('name')==action and a.get('kind')=='Buy']
    if len(offers)!=1 or len(configs)!=1:raise ValueError('conditional_offer_missing_or_ambiguous')
    offer,config=offers[0],configs[0]
    if offer.get('display')!=config.get('display') or offer.get('payload')!=config.get('payload'):
        raise ValueError('conditional_configuration_mismatch')
    display=offer['display'];counter=step['counters'][display['cost_counter']]
    base=money(step['bet_amount'])
    value=counter['value_per_bet'].get(str(step['bet_amount']),counter['default_value'])
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<len(display['cost_table']):
        raise ValueError('conditional_price_counter_invalid')
    cost=money(offer['cost'])
    if cost<=0 or cost!=base*money(display['cost_table'][value]) or cost!=cost.to_integral_value():
        raise ValueError('conditional_native_price_mismatch')
    return {'game':game,'provider':'peterandsons','action':action,'complete':False,
            'asyncWin':False,'bet':float(cost/100),'roundId':response['roundId']}

def settlement_rejected(play,journal):
    return (journal.get('path')=='/game/complete' and journal.get('status')=='received'
            and journal.get('http_status')==400
            and journal.get('response',{}).get('error',{}).get('code')=='TRANSACTION_REJECTED'
            and bool(play.get('roundId')) and journal.get('request',{}).get('roundId')==play['roundId']
            and not play.get('wager',{}).get('next')
            and bool(play.get('wager',{}).get('data'))
            and play['wager']['data'][-1].get('closes_game_round') is True)

def minimum_modes(info):
    result=[]
    for action,table in info['bets'].items():
        if not re.fullmatch(r'[A-Za-z0-9_]+',action):raise ValueError('unsafe_native_action_identifier')
        if action=='main':kind='normal'
        elif action.startswith('buy_'):kind='purchase'
        elif action=='buy' and money(info.get('config',{}).get('buy_configuration',{}).get('BUY',0))>0:kind='purchase'
        elif action.startswith('bet_'):kind='special'
        elif action=='bet' and money(info.get('config',{}).get('special_bets_configuration',{}).get('BET',0))>0:kind='special'
        else:raise ValueError('unknown_action_family:'+action)
        values=[money(v) for v in table['available']]
        if not values or min(values)<=0:raise ValueError('invalid_native_bet_menu')
        result.append({'id':action,'kind':kind,'bet':float(min(values))})
    if not any(m['id']=='main' for m in result):raise ValueError('missing_native_normal_mode')
    return sorted(result,key=lambda m:(m['id']!='main',m['id']))

def audit_round(before,info,play_request,play_response,complete_request,complete_response,continuations=None):
    action=play_request['action'];bet=money(play_request['bet']);before=money(before)
    if bet not in [money(x) for x in info['bets'][action]['available']]:raise ValueError('stake_not_in_native_menu')
    if play_request.get('complete') is not False or play_request.get('asyncWin') is not False:raise ValueError('unreviewed_settlement_mode')
    if complete_request['roundId']!=play_response['roundId']:raise ValueError('round_binding_mismatch')
    if complete_request.get('game')!=play_request['game'] or complete_request.get('provider')!='peterandsons':raise ValueError('game_binding_mismatch')
    packets=[play_response];previous=play_response;total_cost=bet;wallet=money(play_response['balance'])
    for continuation in continuations or []:
        request=continuation['request']
        expected=take_round_request(play_request['game'],previous) if request.get('action')=='take_round' else extra_spin_request(play_request['game'],previous,info,request.get('action'))
        if request!=expected:raise ValueError('unreviewed_continuation_request')
        response=continuation['response']
        if response.get('roundId')!=play_response['roundId']:raise ValueError('continuation_round_binding_mismatch')
        charge=money(request.get('bet',0));total_cost+=charge;wallet-=charge
        if charge>0 and response.get('balance') is None:raise ValueError('missing_conditional_debit_balance')
        if response.get('balance') is not None and money(response['balance'])!=wallet:raise ValueError('unexpected_continuation_wallet_change')
        packets.append(response);previous=response
    wager=packets[-1]['wager'];steps=[step for packet in packets for step in packet['wager']['data']]
    if wager.get('next') or not steps or steps[-1].get('closes_game_round') is not True:raise ValueError('native_round_not_closed')
    if money(play_response['balance'])!=before-bet:raise ValueError('debit_mismatch')
    win=sum((money(packet['wager']['win']) for packet in packets),Decimal(0))
    if money(complete_response['finalWin'])!=win:raise ValueError('payout_mismatch')
    if money(complete_response['balance'])!=before-total_cost+win:raise ValueError('balance_mismatch')
    for packet in packets:
        cumulative=Decimal(0)
        for step in packet['wager']['data']:
            cumulative+=money(step['action_winnings'])
            if money(step['round_winnings'])!=cumulative:raise ValueError('internal_cumulative_win_mismatch')
        if cumulative!=money(packet['wager']['win'])*100:raise ValueError('internal_units_mismatch')
    return {'passed':True,'cost':float(total_cost),'payout':float(win),'balance_before':float(before),
            'balance_after':float(money(complete_response['balance'])),'internal_steps':len(steps),
            'states':[step['state'] for step in steps],'round_closed':True,'wallet_check':'match'}
