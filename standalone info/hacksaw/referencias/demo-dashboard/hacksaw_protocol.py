"""Pure parsing and native-round validation for official Hacksaw demos."""
from decimal import Decimal
from html import unescape
import hashlib
import json
import re


def parse_catalog(source):
    result=[];seen=set()
    for attrs,body in re.findall(r'<li\b([^>]*\bclass="GridListItem"[^>]*)>(.*?)</li>',source,re.S):
        gid=re.search(r'data-gameid="(\d+)"',attrs)
        name=re.search(r'aria-label="([^"]+)"',attrs)
        link=re.search(r'href="(/games/[^"?#]+)',body)
        if not gid or not name or not link or gid[1] in seen:continue
        seen.add(gid[1])
        result.append({'id':gid[1],'name':unescape(name[1]).split(' |')[0],
                       'slug':link[1].rsplit('/',1)[-1],'details_url':'https://www.hacksawgaming.com'+link[1]})
    return result


def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if k.lower() in {'sessionuuid','token','playerid','authorization','cookie','set-cookie'} else redact(v)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    return value


def continuation(round,selected=None):
    state=round['status'];actions=round.get('possibleActions') or []
    if state=='completed':return None
    if actions:
        if selected is not None and selected not in actions:raise ValueError('unoffered_native_action')
        return selected if selected is not None else actions[0]
    if state=='wfwpc':return 'win_presentation_complete'
    raise ValueError('unsupported_native_round_state:'+str(state))


def choice_point(round):
    actions=round.get('possibleActions') or []
    if not actions:return None
    last=(round.get('events') or [{}])[-1]
    family={'status':round['status'],'actions':sorted(actions),'event':last.get('etn'),'choice':(last.get('c') or {}).get('choice')}
    node=hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16]
    return {'node':node,'family':family,'options':actions}


def check_round(before,bet,multiplier,responses):
    if not responses:raise ValueError('missing_round_responses')
    rounds=[r.get('round') or {} for r in responses]
    ids={r.get('roundId') for r in rounds}
    if len(ids)!=1 or None in ids:raise ValueError('round_identity_changed')
    if any(r.get('statusCode')!=0 for r in responses if 'statusCode' in r):raise ValueError('provider_error_in_round')
    if rounds[-1].get('status')!='completed' or rounds[-1].get('possibleActions'):raise ValueError('round_not_closed')
    balance=responses[-1].get('accountBalance')
    if not balance or balance.get('balance') is None:raise ValueError('missing_final_balance')
    win=sum((Decimal(str(e.get('wa','0'))) for r in rounds for e in r.get('events') or []),Decimal(0))
    cost=Decimal(str(bet))*Decimal(str(multiplier));expected=Decimal(str(before))-cost+win
    after=Decimal(str(balance['balance']))
    if expected!=after:raise ValueError('wallet_mismatch:expected='+str(expected)+',actual='+str(after))
    return {'cost':str(cost),'win':str(win),'balance_after':str(after),'wallet_check':'match','round_id':next(iter(ids))}
