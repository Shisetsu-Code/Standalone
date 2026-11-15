"""Pure prefix guard: reject an invalid native response before another action."""
from pathlib import Path

from kagaming_bonus_pick import is_supported, decision, validate_pick, validate_transition

REF=Path(__file__).parent/'kagaming/reference'


def _int(value):
    if type(value) is not int or value<0:
        raise ValueError('invalid_progress_native_integer')
    return value


def _bonus(game,md):
    return decision(game,md,(REF/(game.lower()+'.js')).read_bytes(),
                    (REF/'game.min.2090.js').read_bytes())


def validate_progress(profile,before,steps):
    """Validate the whole received journal prefix without requiring final closure.

    Spin credits follow tw. Bonus pick credits use absolute cr; final cumulative
    bonus settlement remains the source-bound reconciler's responsibility.
    """
    wallet=_int(before);cost=_int(profile.get('cost_native'))
    if cost==0 or not isinstance(steps,list) or not steps:
        raise ValueError('missing_progress_prefix')
    tid=None;game=None;previous=None;seen=set()
    for index,step in enumerate(steps):
        if not isinstance(step,dict) or step.get('status')!='received' or type(step.get('http_status')) is not int or step['http_status']!=200:
            raise ValueError('unconfirmed_progress_transport')
        req=step.get('request');res=step.get('response')
        if not isinstance(req,dict) or not isinstance(res,dict) or res.get('e') is not False or type(res.get('ec')) is not int or res['ec']!=0:
            raise ValueError('unconfirmed_progress_response')
        md=res.get('md')
        if not isinstance(md,dict) or md.get('v') is not True:
            raise ValueError('invalid_progress_native_result')
        _int(md.get('sid'));_int(req.get('sid'))
        if not isinstance(md.get('tid'),str) or not md['tid'].strip():
            raise ValueError('missing_progress_round_identity')
        if index==0:
            tid=md['tid'];game=req.get('gn')
            if not isinstance(game,str) or not game or profile.get('game_id',game)!=game:
                raise ValueError('progress_game_identity_mismatch')
        if md['tid']!=tid or req.get('gn')!=game or ('gn' in md and md['gn']!=game):
            raise ValueError('progress_round_or_game_identity_changed')
        win=_int(md.get('tw'));balance=_int(res.get('cr'))
        path=step.get('path','')
        terminal=None
        if game in ('HomeRunDerby','BonusPoker'):
            from kagaming_interactive import _state
            terminal=_state(game,md)
        elif game=='ChickenQuest':
            from kagaming_chicken import _state
            terminal=_state(game,md)
        elif game=='PenaltyShootout':
            from kagaming_penalty import validate_response
            terminal=validate_response(md,profile,req)
        if terminal is False and game in ('HomeRunDerby','BonusPoker','ChickenQuest') and win!=0:
            raise ValueError('pending_interactive_progress_credit')
        if path.endswith('/spin'):
            if index:
                from kagaming_core import needs_continuation
                if not needs_continuation(previous,game):
                    raise ValueError('progress_spin_after_terminal')
                if is_supported(game) and previous.get('bpd') and _bonus(game,previous)['action']=='bonus_pick':
                    raise ValueError('progress_spin_while_bonus_pick_pending')
            if _int(res.get('sid'))!=req['sid'] or req['sid'] in seen:
                raise ValueError('progress_spin_identity_mismatch')
            seen.add(req['sid'])
            pcr=_int(res.get('pcr'))
            if pcr!=wallet-(cost if index==0 else 0) or balance!=pcr+win or _int(md.get('pbb'))!=wallet or _int(md.get('obb'))!=balance:
                raise ValueError('progress_spin_wallet_mismatch')
            if is_supported(game) and md.get('bpd'):
                _bonus(game,md)
        elif path.endswith('/bonusPick'):
            if not previous or req['sid']!=previous['sid'] or _int(res.get('p'))!=_int(req.get('p')):
                raise ValueError('progress_bonus_pick_identity_mismatch')
            if set(req)-{'gn','p','sid','psp'}:
                raise ValueError('progress_bonus_pick_extra_fields')
            if game=='BonusPoker':
                from kagaming_interactive import assert_closed
                assert_closed(game,md)
                if req['p']>31 or balance!=wallet+win:
                    raise ValueError('progress_poker_settlement_mismatch')
            elif is_supported(game):
                prior_row=_bonus(game,previous);row=_bonus(game,md)
                validate_pick(prior_row,req['p']);validate_transition(prior_row,row,req['p'])
                if balance<wallet:
                    raise ValueError('progress_bonus_pick_unexpected_debit')
            else:
                raise ValueError('unsupported_progress_bonus_family')
        else:
            raise ValueError('unsupported_progress_endpoint')
        wallet=balance;previous=md
    return {'validated_steps':len(steps),'balance_after_native':wallet,'tid':tid}
