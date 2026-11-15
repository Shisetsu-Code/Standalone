"""Source-gated native FUN protocols. Importing/planning never sends requests.

All money is original integer native subunits. Live server verification remains
the caller's responsibility; synthetic tests are not evidence of live success.
"""
import hashlib
import itertools
import re

DICE = ('RocketDice', 'RocketDiceXY')
MINES = ('MineGems', 'FortuneRedPackets', 'Minesweeper', 'MinesweeperXY')


def metadata(source, gid):
    """Prove game-specific wire and UI controls from its cached official client."""
    if gid in DICE:
        patterns = [r'command:"roll",options:\{bet:\w+,kind:\w+\?"over":"under",score:\w+\}',
                    r'command:"risk",options:\{chosen:\w+\}', r'command:"finish"',
                    r'risk.canBeStarted=3===\w+.length', r'\[1,2,3,4,5,6\]',
                    r'game.win', r'result,totalBet:', r'options.currency.subunits',
                    r'"finished"===\w+.game.state',
                    r'isCommandAvailable\("close"\)\?this.finishGame\(\).finally\(\w+\):this.isCommandAvailable\("roll"\)\?\w+\(\)',
                    r'revealBalance\(\w+=!1\)\{.{0,360}?"finish"===.*?latestData.requested_command.*?\(\w+\+=.*?latestData.result\)',
                    r'collect\(\)\{.*?data.balance\+=.*?data.winToShow.*?finishGame\(\)']
        family = 'native-rocket-dice'
    elif gid in ('MineGems', 'FortuneRedPackets'):
        patterns = [r'command:\w+\[0\],options:\{bet:\w+.A.data.totalBet,field:this.fieldSize,position:Number\(\w+\[1\]\)\}',
                    r'command:"stop"', r'var \w+="step"', r'\w+="start"',
                    r'case"alive"', r'case"closed"', r'winBet=\w+.result',
                    r'options.fields.forEach', r'options.currency.subunits']
        family = 'native-mine-ladder'
    elif gid in ('Minesweeper', 'MinesweeperXY'):
        patterns = [r'\.games\.' + gid + r'=\{',
                    r'command:\w+\?"step":"start",options:\{bet:.*?\.Bet.config.subunits,field:.*?\.Bet.field,position:\w+\}',
                    r'command:"stop"', r'"alive"===\w+.game.state',
                    r'summ:\w+.result/.*?\.Bet.config.subunits', r'fields:.*?\.options.fields']
        family = 'native-mine-ladder'
    else:
        raise ValueError('Unsupported native table game')
    proofs = []
    for pattern in patterns:
        match = re.search(pattern, source)
        if not match:
            raise ValueError('Unproved native table source: ' + pattern)
        proofs.append(dict(pattern=pattern, offset=match.start(), excerpt=match.group(0)))
    return dict(native_tables_verified=True, game_id=gid, protocol=family,
                source_sha256=hashlib.sha256(source.encode()).hexdigest(), proofs=proofs)


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('Unverified native amount: ' + name)
    return value


def _available(response, command):
    commands = response.get('available_commands', [])
    return bool(commands.get(command)) if isinstance(commands, dict) else command in commands


def dice_terminal(response):
    """Source recognizes finished outcomes; roll availability proves ready again.

    A finished outcome can still require finish/collection, as the official play
    path checks close before permitting roll. Never infer closure from its label.
    """
    return (response.get('game',{}).get('state') in ('closed','finished')
            and _available(response,'roll')
            and not any(_available(response,c) for c in ('finish','close','risk')))


def plan(initial, meta):
    """All thresholds/risk triples or field/column/collection-depth activators.

    Depths greater than one and risk triples require a random survival/win trigger.
    They remain needs_trigger when the paid attempt closes before reaching it.
    No enumeration of exponentially many prior outcome paths is implied.
    """
    if not meta.get('native_tables_verified') or meta.get('game_id') not in DICE + MINES:
        raise ValueError('Native table source proof missing')
    options = initial['options']; currency = options['currency']; gid = meta['game_id']
    if currency.get('code') != 'FUN' or currency.get('subunits') != 100:
        raise ValueError('Only source-proved native FUN units supported')
    _integer(initial.get('balance'), 'balance')
    bet = _integer(options.get('min_bet'), 'min_bet')
    if not bet or bet > _integer(options.get('max_bet'), 'max_bet'):
        raise ValueError('Invalid native bet limits')
    command = 'roll' if gid in DICE else 'start'
    ready=initial.get('game', {}).get('state') in ('idle','closed')
    if gid in DICE:ready=initial.get('game',{}).get('state')=='idle' or dice_terminal(initial)
    if not _available(initial, command) or not ready:
        raise ValueError('Native initial state is not ready')
    common = dict(protocol=meta['protocol'], command=command, cost_native=bet,
                  source_sha256=meta['source_sha256'], game_id=gid)
    modes = []
    if gid in DICE:
        table = initial['paytable']
        if set(table) != {'over', 'under'} or set(table['over']) != set(map(str,range(2,12))) or set(table['under']) != set(map(str,range(3,13))):
            raise ValueError('Unexpected Rocket Dice threshold table')
        for kind in ('over','under'):
            for score in sorted(table[kind], key=int):
                modes.append(dict(common, name=f'{kind}:{score}/collect',options=dict(bet=bet,kind=kind,score=int(score))))
        for chosen in itertools.combinations(range(1,7),3):
            modes.append(dict(common,name='risk:'+','.join(map(str,chosen)),
                              options=dict(bet=bet,kind='over',score=2),risk_chosen=list(chosen)))
    else:
        fields = options['fields']; table = options['paytable']
        if not fields or len(set(fields)) != len(fields) or set(table) != set(fields):
            raise ValueError('Unexpected native field table')
        for field in fields:
            if not re.fullmatch(r'[2-6]x(?:3|6|9|12|15)',field):
                raise ValueError('Unproved native field dimensions')
            width,height = map(int,field.split('x'))
            if len(table[field]) != height:
                raise ValueError('Native field payout depth mismatch')
            for position in range(width):
                for depth in range(1,height+1):
                    target_kind='first_step_selector' if depth==1 else 'conditional_collection_depth'
                    modes.append(dict(common,name=f'{target_kind}/field:{field}/position:{position}/depth:{depth}',
                                      options=dict(bet=bet,field=field,position=position),target_depth=depth,
                                      target_kind=target_kind))
    return modes


def dice_pending_credit(response, command=None):
    """A finish result is excluded from its original raw balance, per revealBalance.

    This is an explicit pending-credit view; it never changes response.balance.
    Other result fields or unresolved finishes are not treated as wallet credit.
    """
    action=response.get('game',{}).get('action')
    if command is not None and action is not None and command!=action:
        raise ValueError('Rocket response action differs from requested command')
    command=command or action or response.get('requested_command')
    result=response.get('result')
    prize=0 if result is None else _integer(result,'result')
    if command=='finish':
        if not dice_terminal(response):raise ValueError('Rocket finish is not terminal and ready for roll')
        return prize
    if prize:raise ValueError('Unsupported Rocket result outside source-proved finish')
    return 0


def dice_effective_balance(response, command=None):
    return _integer(response.get('balance'),'balance')+dice_pending_credit(response,command)


def reconcile(before, response, cost, *, protocol=None, command=None):
    """Check original balances; Rocket finish uses a separately proved credit view.

    For Rocket pass the previous full raw response, protocol='native-rocket-dice',
    and the request command. A positive finish must match previous game.win.
    Mines retain direct original scalar settlement semantics.
    """
    if response.get('errors'):
        raise ValueError('Native table server error; response retained')
    balance = _integer(response.get('balance'),'balance')
    if protocol=='native-rocket-dice':
        cost=_integer(cost,'cost')
        before_raw=_integer(before.get('balance'),'before balance') if isinstance(before,dict) else _integer(before,'before')
        before_pending=dice_pending_credit(before) if isinstance(before,dict) else 0
        after_pending=dice_pending_credit(response,command)
        finish=(command or response.get('game',{}).get('action'))=='finish'
        if finish:
            held=before.get('game',{}).get('win') if isinstance(before,dict) else None
            if held is None and after_pending:
                raise ValueError('Positive Rocket finish requires preceding native game.win')
            if held is not None and _integer(held,'held game.win')!=after_pending:
                raise ValueError('Rocket finish prize differs from preceding held award')
        raw_expected=before_raw+before_pending-cost
        effective_expected=raw_expected+after_pending
        effective_actual=balance+after_pending
        if balance!=raw_expected:
            raise ValueError(f'Rocket native raw wallet mismatch: expected {raw_expected}, actual {balance}')
        return dict(kind='rocket_dice_native_pending_credit',expected=effective_expected,actual=effective_actual,
                    before_raw_native=before_raw,before_effective_native=before_raw+before_pending,
                    raw_expected_native=raw_expected,raw_actual_native=balance,cost_native=cost,
                    win_native=after_pending,pending_credit_before_native=before_pending,
                    pending_credit_after_native=after_pending,ok=True)
    before = _integer(before,'before'); cost = _integer(cost,'cost')
    result = response.get('result')
    win = 0 if result is None else _integer(result,'result')
    expected = before-cost+win
    if expected != balance:
        raise ValueError(f'Native table wallet mismatch: expected {expected}, actual {balance}')
    return dict(kind='native_tables_wallet',expected=expected,actual=balance,
                cost_native=cost,win_native=win,ok=True)


def run(demo, mode, initial):
    """Caller supplies transport and rate limiting; max one paid round per call.

    demo.call must retain original requests/responses before returning. No exception
    retries, init refreshes, or hidden wager attempts occur here.
    """
    if mode.get('protocol') not in ('native-mine-ladder','native-rocket-dice'):
        raise ValueError('Unsupported native table mode protocol')
    current = demo.prev or initial
    ready=current.get('game',{}).get('state') in ('idle','closed')
    if mode['protocol']=='native-rocket-dice':ready=current.get('game',{}).get('state')=='idle' or dice_terminal(current)
    if not ready:
        raise ValueError('Refuse new native wager with unresolved previous round')
    spendable=dice_effective_balance(current) if mode['protocol']=='native-rocket-dice' else current['balance']
    if spendable < mode['cost_native']:
        return dict(mode=mode,status='insufficient_demo_balance')
    demo.active_mode=mode; start=len(demo.events)

    def send(command, options=None, cost=0):
        nonlocal current
        if not _available(current,command):
            raise ValueError('Native command not currently advertised: '+command)
        before=current if mode['protocol']=='native-rocket-dice' else current['balance']
        response=demo.call(command,options) if options is not None else demo.call(command)
        # Preserve continuation evidence even if reconciliation fails.
        demo.prev=response; current=response
        check=reconcile(before,response,cost,protocol=mode['protocol'],command=command);demo.money_checks.append(check)
        return response

    send(mode['command'],mode['options'],mode['cost_native'])
    reached = True
    if mode['protocol']=='native-mine-ladder':
        depth=1
        while depth < mode['target_depth'] and current.get('game',{}).get('state')=='alive':
            send('step',mode['options']);depth+=1
        reached=depth==mode['target_depth'] and (
            mode['target_depth']==1 or current.get('game',{}).get('state')=='alive'
            or (type(current.get('result')) is int and current['result']>0))
        if current.get('game',{}).get('state')=='alive': send('stop')
    elif mode['protocol']=='native-rocket-dice':
        if 'risk_chosen' in mode:
            reached=_available(current,'risk') and current.get('game',{}).get('win',0)>0
            if reached: send('risk',{'chosen':mode['risk_chosen']})
        if not dice_terminal(current): send('finish')
    else:
        raise ValueError('Unsupported native table mode protocol')
    terminal=dice_terminal(current) if mode['protocol']=='native-rocket-dice' else current.get('game',{}).get('state')=='closed'
    if not terminal:
        raise ValueError('Native round did not close; response retained')
    extra={}
    if mode['protocol']=='native-rocket-dice':
        extra=dict(final_effective_balance_native=dice_effective_balance(current),
                   final_pending_credit_native=dice_pending_credit(current))
    return dict(mode=mode,status='closed' if reached else 'needs_trigger',
                final_state=current['game']['state'],final_balance=current['balance'],
                first_event=start,last_event=len(demo.events)-1,**extra)
