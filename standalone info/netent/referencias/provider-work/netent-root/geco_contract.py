"""Observed native CasinoGameServlet key/value protocol; monetary values in cents."""
from decimal import Decimal
from urllib.parse import parse_qsl
import re

def native_base_parameters(query):
    """SDK getBaseParameters plus ResourceHandler's persistent ne_ prefix."""
    if not query.get('sessid') or not query.get('gameId'):raise ValueError('Native session/game missing')
    return {k:v for k,v in query.items() if k in ['sessid','gameId'] or k.startswith('ne_')}


def unreviewed_stake_options(initial):
    """Different clients spell stake feature flags with dots or underscores."""
    terms=['buyfeature','featurebuy','buyfreespins','antebet','bonusbet','gambl','featurebet']
    found=[k for k,v in initial.items()
                  if any(word in re.sub(r'[^a-z0-9]','',k.lower()) for word in terms)
                  and str(v).lower() not in ['false','0','']]
    if initial.get('mathModes') not in [None,'','null']:found.append('mathModes')
    if initial.get('bl.standard') and ',' not in initial['bl.standard'] and initial['bl.standard']!='0':
        found.append('native_betline_selector')
    return sorted(found)


def parse(text):
    result={}
    for key,value in parse_qsl(text,keep_blank_values=True):
        if key in result and result[key]!=value:raise ValueError('Conflicting protocol fields')
        result[key]=value
    # Mega Joker's native response parser assigns nextaction=spin from its
    # allowedactions list. Only the unambiguous closed, single-spin case is used.
    if 'nextaction' not in result and result.get('gameover')=='true' and result.get('allowedactions')=='spin':
        result['nextaction']='spin'
    return result


def minimum_bet(initial,*,native_cost_coins=None):
    if initial.get('playforfun')!='true':raise ValueError('Public demo flag missing')
    if initial.get('nextaction')!='spin' or initial.get('gameover')!='true':
        raise ValueError('A restored round must not be replaced')
    denominations=[int(v) for v in initial['denomination.all'].split(',')]
    levels=[int(v) for v in initial['betlevel.all'].split(',')]
    lines=initial['bl.standard'].split(',')
    # Native ways clients send the selected bl.iN.id, not an index range.
    # Their coin weights are alternatives, rather than additive paylines.
    if len(lines)==1 and lines[0]!='0' and '/' in initial.get('bl.i0.line',''):
        indices=sorted(int(m.group(1)) for k in initial if (m:=re.fullmatch(r'bl\.i(\d+)\.id',k)))
        options=[(int(initial[f'bl.i{i}.coins']),initial[f'bl.i{i}.id']) for i in indices]
        if lines[0] not in {v for _,v in options} or not options or min(denominations+levels)<=0 or min(c for c,_ in options)<=0:
            raise ValueError('Invalid native ways selector')
        coins,identifier=min(options,key=lambda option:(option[0],int(option[1])))
        return {'denomination':min(denominations),'level':min(levels),'lines':identifier,
                'cost_cents':min(denominations)*min(levels)*coins}
    weights=[int(initial[f'bl.i{i}.coins']) for i in range(len(lines))]
    if min(denominations+levels)<=0 or min(weights)<0 or sum(weights)<=0:
        raise ValueError('Invalid native bet setting')
    denomination=min(denominations);level=min(levels)
    coins=sum(weights)
    if native_cost_coins is not None:
        if type(native_cost_coins) is not int or native_cost_coins<=0:raise ValueError('Invalid reviewed native coin cost')
        coins=native_cost_coins
    bet={'denomination':denomination,'level':level,'lines':'0-'+str(len(lines)-1),
         'cost_cents':denomination*level*coins}
    if native_cost_coins is not None:bet['native_cost_coins']=native_cost_coins
    return bet


def spin_parameters(bet):
    return {'bet.betlevel':bet['level'],'bet.denomination':bet['denomination'],'bet.betlines':bet['lines']}


def free_parameters(action,*,allowed=()):
    if action in ['spin','featurebuy'] or action not in ['drop','freespin','respin','initfreespin',*allowed]:
        raise ValueError('A new wager or player decision is not a free continuation')
    return {'action':action,'wantsreels':'true'}


def validate_restore(expected,restored):
    if restored.get('playforfun')!='true':raise ValueError('Restored session is not a confirmed demo')
    for key in ['credit','nextaction','totalwin.cents','gamestate.current']:
        if key in expected and expected[key]!=restored.get(key):raise ValueError('Restored round differs at '+key)
    if expected.get('gameRoundId') and restored.get('gameRoundId') and expected['gameRoundId']!=restored['gameRoundId']:
        raise ValueError('Restored round identifier differs')


def reconcile_round(initial,final,bet,*,factor=1):
    before=Decimal(initial['credit']);after=Decimal(final['credit'])
    cost=Decimal(bet['cost_cents'])*Decimal(str(factor));win=Decimal(final['totalwin.cents'])
    checks={'demo':initial.get('playforfun')=='true','minimum_base':bet==minimum_bet(initial,native_cost_coins=bet.get('native_cost_coins')),'positive_factor':Decimal(str(factor))>0,
            'wallet_ledger':before-cost+win==after,'nonnegative_credit':win>=0,
            'round_closed':final.get('gameover')=='true' and final.get('nextaction')=='spin'}
    return {'before':str(before/100),'debit':str((before-cost)/100),'after':str(after/100),
            'cost':str(cost/100),'win':str(win/100),'checks':checks,'passed':all(checks.values()),
            'debit_observation':'Derived from native cost; no separate after-bet wallet packet is exposed'}
