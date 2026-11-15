"""Settle one paid RT entry followed by a native no-extra-debit choice."""
from decimal import Decimal

def merged_game(response):
    game=response['result']['game']
    return {**game,**(game.get('gameData') or {})}

def active_choices(value):
    if isinstance(value,dict):
        choices=value.get('choices')
        if isinstance(choices,dict) and choices.get('available'):return choices['available']
        for item in value.values():
            found=active_choices(item)
            if found:return found
    if isinstance(value,list):
        for item in value:
            found=active_choices(item)
            if found:return found
    return []

def reconcile_choice(first,last,before,minimum,selected,offered,*,response_history=None):
    original=first['result'];final=last['result'];cash=original['user']['balance']['cash'];ending=final['user']['balance']['cash']
    game=merged_game(last);before=Decimal(str(before));minimum=Decimal(str(minimum))
    debit=Decimal(str(cash['afterBet']));after=Decimal(str(ending['atEnd']));win=Decimal(str(game['win']['total']))
    history=response_history if response_history is not None else [{'requested':selected,
        'selected_echo':game.get('choices',{}).get('selected'),'success':last['success'],
        'wallet':ending,'offered_options':offered}]
    continuity=bool(history);no_extra=bool(history);previous=Decimal(str(cash['atEnd']))
    for item in history:
        wallet=item.get('wallet',{})
        if not all(key in wallet for key in ['atStart','afterBet','atEnd']):
            continuity=False;no_extra=False;continue
        opening,after_bet,closing=(Decimal(str(wallet[k])) for k in ['atStart','afterBet','atEnd'])
        continuity=continuity and opening==previous;no_extra=no_extra and opening==after_bet
        previous=closing
    checks={'both_responses_accepted':first['success'] is True and last['success'] is True,
        'opening_balance':Decimal(str(cash['atStart']))==before,
        'minimum_base':Decimal(str(original['game']['stake']))==minimum,
        'original_debit':before-minimum==debit,
        'choice_wallet_continuity':continuity,
        'choice_has_no_additional_debit':no_extra,
        'choice_final_wallet_matches_chain':bool(history) and previous==after,
        'choice_was_offered':selected in offered,
        'selected_choice_echo':str(game.get('choices',{}).get('selected'))==str(selected),
        'all_recorded_choices_honored':bool(history) and all(item.get('success') is True and str(item.get('requested'))==str(item.get('selected_echo')) for item in history),
        'all_recorded_choices_offered':bool(history) and all(item.get('requested') in item.get('offered_options',[]) for item in history),
        'wallet_ledger':before-minimum+win==after,'nonnegative_credit':win>=0,
        'no_pending_choice':not active_choices(final)}
    return {'before':str(before),'debit':str(debit),'after':str(after),'stake':str(minimum),'factor':'1',
            'cost':str(minimum),'choice_extra_cost':'0','win':str(win),'checks':checks,'passed':all(checks.values())}
