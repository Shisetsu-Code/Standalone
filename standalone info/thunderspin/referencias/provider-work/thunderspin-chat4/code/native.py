"""Pure ThunderSpin native ledger verification; no network or credentials."""
from decimal import Decimal

def number(value):
    n=Decimal(str(value))
    if not n.is_finite() or n<0:raise ValueError('invalid_native_amount')
    return n

def audit_packets(packets):
    sessions={};closed=[]
    for p in packets:
        if p['http_status']!=200:raise ValueError('unconfirmed_http')
        x=p['response'];endpoint=p['endpoint'];fp=p['session_fingerprint']
        if x.get('ErrorCode') or x.get('Error') or (isinstance(x.get('status'),dict) and x['status'].get('code',0)>=400):raise ValueError('native_error')
        if endpoint=='_Initialise':
            if sessions.get(fp,{}).get('current'):raise ValueError('initialise_during_round')
            if x['Balance'].get('Demo') is not True:raise ValueError('not_demo')
            sessions[fp]={'balance':number(x['Balance']['ScoreCents']),'currency':x['Balance']['Currency'],'current':None,'game':p['game'],'gamble_disabled':x.get('GameSettings',{}).get('IsGambleAllowed') is False,'gamble_enabled':x.get('GameSettings',{}).get('IsGambleAllowed') is True}
            continue
        if endpoint=='_Ping':continue
        if endpoint=='_Gamble':
            state=sessions[fp];case=state['current'];q=p['request'];g=x.get('Gamble',{});b=x['Balance']
            if not case or not state['gamble_enabled'] or not case.get('accept_pending') or case.get('gamble') or set(q)-{'sid','data'} or isinstance(q.get('data'),bool) or q.get('data') not in (0,1) or not isinstance(g.get('IsWin'),bool):raise ValueError('gamble_not_offered_or_contract_mismatch')
            old=case['payout_cents'];payout=number(b['TotalWinCents']);expected=old*2 if g['IsWin'] else number(0);bank=number(b['ScoreCents']);held=case['balance_before_cents']-case['cost_cents']
            if payout!=expected or old<=0:raise ValueError('gamble_payout_mismatch')
            if b.get('Currency',state['currency'])!=state['currency']:raise ValueError('currency_changed')
            limit_paid=g['IsWin'] and isinstance(g.get('MaxGambleCount'),int) and isinstance(g.get('CurrentGamble'),int) and g['MaxGambleCount']>0 and g['CurrentGamble']>=g['MaxGambleCount'] and bank==held+payout
            if bank!=(held+payout if limit_paid else held):raise ValueError('gamble_balance_mismatch')
            case.update(mode='GAMBLE',payout_cents=payout,pre_gamble_payout_cents=old,gamble={'choice':q['data'],'is_win':g['IsWin'],'payout_cents':float(payout)},accept_pending=g['IsWin'] and not limit_paid);case['requests']+=1
            if not g['IsWin'] or limit_paid:
                case.update(balance_after_cents=bank,currency=state['currency'],closed=True,closure='native_Gamble_loss' if not g['IsWin'] else 'native_Gamble_limit_credit');case.pop('expected_mode');case.pop('accept_pending',None)
                closed.append({k:float(v) if isinstance(v,Decimal) else v for k,v in case.items()});state['balance']=bank;state['current']=None
            continue
        if endpoint=='_AcceptWin':
            state=sessions[fp];case=state['current']
            if not case or not case.get('accept_pending') or set(p['request'])-{'sid'}:raise ValueError('accept_not_offered')
            b=x['Balance'];bank=number(b['ScoreCents']);expected=case['balance_before_cents']-case['cost_cents']+case['payout_cents']
            if bank!=expected:raise ValueError('accept_balance_credit_mismatch')
            if b.get('Currency',state['currency'])!=state['currency']:raise ValueError('currency_changed')
            case['requests']+=1;case.update(balance_after_cents=bank,currency=state['currency'],closed=True,closure='native_AcceptWin_and_exact_credit');case.pop('expected_mode');case.pop('accept_pending',None)
            closed.append({k:float(v) if isinstance(v,Decimal) else v for k,v in case.items()});state['balance']=bank;state['current']=None;continue
        if endpoint not in ('_Roll','_BuyBonus'):raise ValueError('unknown_native_endpoint')
        state=sessions[fp];b=x['Balance'];cost=number(b['TotalBetCents']);bank=number(b['ScoreCents']);win=number(b['TotalWinCents'])
        if b['Currency']!=state['currency']:raise ValueError('currency_changed')
        if state['current'] is None:
            if x['Mode']!='root' or cost<=0:raise ValueError('unbound_paid_entry')
            state['current']={'game':state['game'],'mode':'BUY_BONUS' if endpoint=='_BuyBonus' else 'NORMAL','balance_before_cents':state['balance'],'cost_cents':cost,'payout_cents':Decimal(0),'requests':0,'expected_mode':'root'}
        else:
            if endpoint!='_Roll' or cost!=0:raise ValueError('continuation_debited')
        case=state['current']
        if x['Mode']!=case['expected_mode']:raise ValueError('native_mode_transition_mismatch')
        case['requests']+=1;case['payout_cents']+=win;case['expected_mode']=x['NextMode']
        case['accept_pending']=x.get('waitForAcceptWin') is True and x['NextMode']=='root' and x.get('FreeSpinsLeft',0)==0
        if 'roundWin' in x:reported=number(x['roundWin'])
        else:
            summaries=[v['Value'] for v in x.get('Variables',[]) if v.get('Name')=='SummaryWinCents']
            if len(summaries)!=1:raise ValueError('round_win_summary_missing')
            reported=number(summaries[0])
        if reported!=case['payout_cents']:raise ValueError('round_win_accumulation_mismatch')
        accept_clear=x.get('waitForAcceptWin') is False or ('waitForAcceptWin' not in x and state['gamble_disabled'])
        finished=x['NextMode']=='root' and accept_clear and x.get('FreeSpinsLeft',0)==0
        expected=case['balance_before_cents']-case['cost_cents']+(case['payout_cents'] if finished else 0)
        if bank!=expected:raise ValueError('balance_credit_or_debit_mismatch')
        if finished:
            case['balance_after_cents']=bank;case['currency']=state['currency'];case['closed']=True;case.pop('expected_mode');case.pop('accept_pending',None)
            closed.append({k:float(v) if isinstance(v,Decimal) else v for k,v in case.items()});state['balance']=bank;state['current']=None
    unfinished=[{'game':s['game'],'status':'capture_or_operation_not_closed','requests':s['current']['requests']} for s in sessions.values() if s['current']]
    return {'closed_rounds':closed,'unfinished_rounds':unfinished}
