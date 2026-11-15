"""Source-bound KA bonus choices. This module performs no requests or wallet audit.

The reveal arrays contain rewards, not picked flags. The native client restores
disabled choices using mk, except SilkRoad which uses m2. FruitParty's nonzero
mk also identifies its second phase; the first picked basket stays disabled.
"""
import hashlib
import re


_FAMILIES = {
    'CrazyCircus': (27, 'mk', ('b=h.lJ()', 'z.Xd(b,d)', 'h.CD[d]')),
    'SilkRoad': (5, 'm2', ('b=b.hT', 'z.Xd(b,d)', 'this.F(d).$K(0,0,!1)')),
    'FastBlast': (20, 'mk', ('f=e.lJ()', 'z.Xd(f,a)', 'e.ixa[a]')),
    'FruitParty': (6, 'mk', ('h=0!==this.Y.En.lJ()', 'z.Xd(this.Y.En.lJ(),n)', 'w.QJc(this.Y.En.CD[n])')),
    'Neanderthals': (3, 'mk', ('e=b.lJ()', 'z.Xd(e,f)', 'b.CD[f]')),
    'Kitty': (15, 'mk', ('a.gla-z.ez(a.lJ())', 'b=this.Y.En.CD', '0<b[d]')),
    'KungFu': (3, 'mk', ('h=g.lJ()', 'z.Xd(h,0)', 'z.Xd(h,2)', 'f.sQ()?d.wz():d.Sy()')),
    'Jungle': (6, 'mk', ('f=0!==this.Y.En.lJ()', 'z.Xd(this.Y.En.lJ(),n)', 'p.QJc(this.Y.En.CD[n])')),
    'Ares': (15, 'mk', ('g=e.lJ()', 'z.Xd(g,h)', 'd.ck(!1,f,!0,null)', 'd.Y.En.sQ()?')),
    'WildChristmas': (5, None, ('LR:5', 'e.sma(function(){b.bb()})')),
    'Space': (3, None, ('x.qh(3)', 'e=b.lJ()', 'z.Xd(e,f)', 'b.wz()')),
    'LuxuryGarage': (3, None, ('g.Mue(h,0)', 'g.Mue(h,1)', 'g.Mue(h,2)', 'd.wz(b)')),
    'FairyDust': (6, None, ('x.qh(6)', 'b.wz()', 'a.Hy&&a.Hy(a.Y)')),
    'KAAllStarSportsDay': (4, None, ('LR:4', 'String(a+1)+"_selection.mp3"', 'b.bb()')),
    'LazyRich': (4, None, ('LR:4', 'b.Y=a.Y,b.bb()')),
}

CHOICE_COUNTS={game:profile[0] for game,profile in _FAMILIES.items()}


def is_supported(game):
    return game in _FAMILIES


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('invalid_bonus_pick_integer')
    return value


def _text(source):
    return source.decode('utf8') if isinstance(source, bytes) else source


def source_proof(game, source, common_source):
    """Validate source anchors and return hashes for the parent's evidence record."""
    if game not in _FAMILIES:
        raise ValueError('unsupported_bonus_pick_family')
    count, mask_field, anchors = _FAMILIES[game]
    source, common = _text(source), _text(common_source)
    required = anchors + ((f'x.qh({count})',) if mask_field is not None else ())
    common_required = ('a.gn=this.Gw;a.p=this.JQb;a.sid=this.Lmb',
                       'return"/command/bonusPick"', 'c.fS(b.c)&&(this.slb=b.c)',
                       'c.Hk(b.mk)&&(this.mQb=wb(b.mk))',
                       'c.Hk(b.m2)&&(this.hT=wb(b.m2))',
                       'sQ:function(){return this.slb}',
                       'lh:function(){return 2==this.JJa&&null!=this.En&&!this.En.sQ()}')
    if not isinstance(source,str) or not isinstance(common,str) or any(t not in source for t in required) or any(t not in common for t in common_required) or not re.search(r'Cb\.zI\(this\.la,[ab],\s*this\.Y\.lj\(\)',source):
        raise ValueError('bonus_pick_source_contract_changed')
    return {'game': game, 'choice_count': count, 'mask_field': mask_field,
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'common_source_sha256': hashlib.sha256(common.encode()).hexdigest()}


def decision(game, md, source, common_source):
    """Return closed/free_spin/bonus_pick, and deterministic first unpicked p.

    No request body is manufactured here: the parent supplies native sid and
    optional psp through its existing request identity/signature machinery.
    """
    proof = source_proof(game, source, common_source)
    if not isinstance(md,dict):
        raise ValueError('invalid_bonus_pick_metadata')
    if md.get('v') is not True or type(md.get('sid')) is not int or md['sid']<0 or not isinstance(md.get('tid'),str) or not md['tid'].strip():
        raise ValueError('unconfirmed_bonus_pick_metadata_identity')
    remaining = _integer(md.get('fsr',0))
    if md.get('rf') or (md.get('fsd') and remaining):
        raise ValueError('other_continuation_requires_review')
    bpd = md.get('bpd')
    row = dict(proof, action='free_spin' if remaining else 'closed',
               remaining=remaining, valid_picks=[], pick=None, mask=None,
               endpoint='/command/bonusPick', phase=None)
    if bpd is None:
        return row
    if not isinstance(bpd,dict) or type(bpd.get('c')) is not bool or type(bpd.get('s')) is not bool:
        raise ValueError('invalid_bonus_pick_flags')
    # Completed bpd may remain attached to a free-spin response. Its choice
    # payload is no longer consulted by the native controller's lh predicate.
    if bpd['c']:
        return row
    if type(md.get('acb')) is not int or md['acb'] != 2:
        raise ValueError('unrecognized_bonus_pick_state')
    count, field, _ = _FAMILIES[game]
    if field is not None and field not in bpd:
        raise ValueError('missing_bonus_pick_mask')
    mask = _integer(bpd[field]) if field is not None else None
    if mask is not None and mask >= 1 << count:
        raise ValueError('invalid_bonus_pick_mask')
    for name in ('rv','rv2'):
        if name in bpd:
            values = bpd[name]
            if not isinstance(values,list) or len(values)>count:
                raise ValueError('invalid_bonus_pick_reveals')
            for value in values:
                _integer(value)
    if game=='Kitty' and any(value>0 and not mask & (1<<p) for p,value in enumerate(bpd.get('rv',[]))):
        raise ValueError('kitty_reveal_mask_inconsistent')
    choices = [p for p in range(count) if mask is None or not mask & (1 << p)]
    if not choices:
        raise ValueError('pending_bonus_without_valid_choice')
    row.update(action='bonus_pick', valid_picks=choices, pick=choices[0], mask=mask,
               phase=('multiplier' if mask else 'coin') if game in ('FruitParty','Jungle') else None)
    return row


def validate_pick(row, pick):
    if row.get('action')!='bonus_pick' or type(pick) is not int or pick not in row['valid_picks']:
        raise ValueError('invalid_or_repeated_bonus_pick')
    return pick


def validate_transition(before, after, pick):
    """Reject repeated picks and lost/reset pending masks; money is audited elsewhere."""
    validate_pick(before,pick)
    if any(before.get(key)!=after.get(key) for key in ('game','source_sha256','common_source_sha256')):
        raise ValueError('bonus_pick_family_or_source_changed')
    if after['action']=='bonus_pick':
        if before.get('mask_field') is None:
            raise ValueError('one_shot_bonus_pick_did_not_complete')
        old,new=before['mask'],after['mask']
        if new != old | (1 << pick):
            raise ValueError('bonus_pick_mask_did_not_advance_exactly_once')
    elif after['action'] not in ('closed','free_spin'):
        raise ValueError('invalid_bonus_pick_transition')
    return after


def reconcile_round(before, cost, steps, source, common_source):
    """Audit spin and pick segments against native balances and terminal bpd.w.

    The source exposes absolute cr and cumulative w, not a guaranteed credit
    timing policy. Deferred and immediate credits are accepted only within
    accrued w, with exact settlement required at the completed segment.
    """
    from kagaming_core import integer
    before,cost=integer(before),integer(cost)
    if before<0 or cost<=0 or not steps:
        raise ValueError('invalid_bonus_round')
    first=steps[0]['request'];game=first.get('gn')
    proof=source_proof(game,source,common_source)
    common=_text(common_source)
    if any(token not in common for token in ('win:J.gc(a.Y.En.v4d)',
           'totalWin:J.gc(a.Y.En.SE())','c.Hk(b.lpw)&&(this.v4d=wb(b.lpw))',
           'var b=a.Ba+b.SE()', 'b.nsa(a.Yia)')):
        raise ValueError('bonus_money_source_contract_changed')
    previous=before;total_win=0;previous_md=None;previous_row=None
    spin_ids=set();round_tid=None;segment=None
    for index,step in enumerate(steps):
        req=step['request'];res=step.get('response',{});md=res.get('md',{})
        if step.get('status')!='received' or step.get('http_status')!=200 or res.get('e') is not False or type(res.get('ec')) is not int or res['ec']!=0 or md.get('v') is not True:
            raise ValueError('unconfirmed_native_bonus_response')
        if req.get('gn')!=game or ('gn' in md and md['gn']!=game):
            raise ValueError('bonus_game_identity_mismatch')
        if type(req.get('sid')) is not int or req['sid']<0 or ('sid' in md and (type(md['sid']) is not int or md['sid']<0)):
            raise ValueError('invalid_native_bonus_identity')
        if any(key in md and (type(md[key]) is bool or md[key]!=first.get(key)) for key in ('sel','cps','dn','atb')):
            raise ValueError('native_bonus_parameter_echo_mismatch')
        if index==0:
            round_tid=md.get('tid')
            if round_tid is None:
                raise ValueError('missing_bonus_round_identity')
        elif md.get('tid')!=round_tid:
            raise ValueError('bonus_round_identity_changed')
        row=decision(game,md,source,common_source)
        balance=integer(res['cr'])
        path=step.get('path','').rstrip('/')
        if path.endswith('/spin'):
            if index and (segment is not None or previous_row['action']!='free_spin'):
                raise ValueError('unexpected_paid_entry_after_bonus')
            if type(res.get('sid')) is not int or req.get('sid')!=res.get('sid') or req.get('sid') in spin_ids:
                raise ValueError('native_spin_identity_mismatch')
            spin_ids.add(req['sid'])
            if index and (req.get('pos') or any(req.get(k)!=first.get(k) for k in ('sel','cps','dn','atb'))):
                raise ValueError('changed_bonus_free_spin_parameters')
            pcr=integer(res['pcr']);win=integer(md['tw'])
            if win<0 or pcr!=previous-(cost if index==0 else 0) or balance!=pcr+win:
                raise ValueError('native_bonus_spin_wallet_mismatch')
            if integer(md['pbb'])!=previous or integer(md['obb'])!=balance:
                raise ValueError('native_bonus_spin_wallet_echo_mismatch')
            total_win+=win
            if row['action']=='bonus_pick':
                initial=integer(md['bpd'].get('w',0))
                if initial!=0:
                    raise ValueError('nonzero_initial_bonus_total_requires_review')
                segment={'credited':0,'w':0,'base_tw':win}
            elif md.get('bpd') and integer(md['bpd'].get('w',0))!=0:
                raise ValueError('unobserved_completed_bonus_requires_review')
        elif path.endswith('/bonusPick'):
            if set(req)-{'gn','p','sid','psp'} or not {'gn','p','sid'}<=set(req):
                raise ValueError('unexpected_bonus_pick_request_fields')
            if index==0 or segment is None or previous_row['action']!='bonus_pick':
                raise ValueError('bonus_pick_without_pending_trigger')
            validate_pick(previous_row,req.get('p'))
            if req.get('sid')!=previous_md.get('sid') or type(req.get('sid')) is not int or res.get('p')!=req['p'] or type(res.get('p')) is not int:
                raise ValueError('native_bonus_pick_identity_mismatch')
            if not isinstance(md.get('bpd'),dict):
                raise ValueError('missing_bonus_pick_result')
            validate_transition(previous_row,row,req['p'])
            bpd=md['bpd'];win=integer(bpd['w']);credit=balance-previous
            if win<segment['w'] or credit<0 or integer(md['tw'])!=segment['base_tw']:
                raise ValueError('native_bonus_total_or_base_changed')
            if 'lpw' in bpd and integer(bpd['lpw'])!=win-segment['w']:
                raise ValueError('native_bonus_last_pick_win_mismatch')
            segment['credited']+=credit
            if segment['credited']>win:
                raise ValueError('bonus_credited_beyond_accrued_win')
            total_win+=credit;segment['w']=win
            if row['action']!='bonus_pick':
                if segment['credited']!=win:
                    raise ValueError('bonus_terminal_settlement_mismatch')
                segment=None
        else:
            raise ValueError('unsupported_bonus_round_endpoint')
        previous=balance;previous_md=md;previous_row=row
    if segment is not None or previous_row['action']!='closed':
        raise ValueError('native_bonus_round_not_closed')
    if before-cost+total_win!=previous:
        raise ValueError('native_bonus_round_wallet_mismatch')
    return dict(proof,balance_before_native=before,cost_native=cost,
                win_native=total_win,balance_after_native=previous,
                internal_steps=len(steps),wallet_check='match')
