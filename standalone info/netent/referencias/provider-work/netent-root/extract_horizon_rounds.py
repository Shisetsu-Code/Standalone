"""Build sanitized financial cases from this run's private native WS trace."""
import json,hashlib
from pathlib import Path
from horizon_contract import demo_balance,reconcile

OUT=Path(__file__).resolve().parent
PRIVATE=OUT.parents[1]/'netent-private-root'
state=json.loads((PRIVATE/'operator-state.json').read_text(encoding='utf8'))
source=Path(state['trace_file']);raw=source.read_bytes()
events=[json.loads(line) for line in raw.splitlines()]
wallet=None;initial=None;case=None;cases=[]
for event in events:
    if event.get('kind')!='ws' or not isinstance(event.get('data'),str):continue
    try:packet=json.loads(event['data']);body=packet.get('payload',packet)
    except (ValueError,AttributeError):continue
    balance=demo_balance(packet)
    if balance:
        wallet=balance
        if case:
            case['wallet_steps'].append({'amount':str(wallet['amount']),'version':wallet['version']})
        continue
    if body.get('type')=='SlotsCall' and event['direction']=='sent':
        details=body.get('details',{})
        if 'play' in details:
            if case:raise RuntimeError('New paid root before prior round closure')
            play=details['play']
            case={'mode':play['betCode'],'stake':str(play['stake']),'before':str(wallet['amount']),
                  'factor':str(initial['costFactors'][play['betCode']]),'wallet_steps':[],'steps':[],'requests':[]}
        if case:case['requests'].append(details)
    if body.get('type')=='SlotsResult' and event['direction']=='received':
        params=body.get('details',{}).get('params',{})
        if 'stakeIncrements' in params:initial=params
        if case and 'wins' in params:
            case['steps'].append({'next_action':params.get('nextAction'),'wins':params['wins'],'game':params.get('game')})
            if params.get('nextAction')=='spin':
                result=reconcile(stake=case['stake'],factor=case['factor'],before=case['before'],
                    debit=case['wallet_steps'][0]['amount'],after=str(wallet['amount']),
                    win=params['wins']['total'],closed=not params['wins'].get('pending'))
                case.update(result)
                case['checks']['minimum_base']=case['stake']==str(min(initial['stakeIncrements']))
                case['passed']=all(case['checks'].values());cases.append(case);case=None
proof={'provider':'NetEnt','slug':'jack-and-the-beanstalk-2-goat-enterprise','catalog_ordinal':19,
       'transport':'WS via local provider relay 8793','source_sha256':hashlib.sha256(raw).hexdigest(),
       'source_snapshot':'native relay operator capture','mode_cost_factors':initial['costFactors'],
       'cases':cases,'open_case':case,'verified_cases':sum(c['passed'] for c in cases),
       'all_game_modes_complete':{c['mode'] for c in cases if c['passed']}==set(initial['costFactors'])}
(OUT/'live').mkdir(exist_ok=True)
(OUT/'live/jack-native-rounds.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'verified_cases':proof['verified_cases'],'modes':[c['mode'] for c in cases],
                  'steps':[len(c['steps']) for c in cases],'open_case':case is not None}))
