"""Static ActionCable contracts; no websocket client, network, automatic actions or files.

All amounts stay exactly as received. Source names ending in _cents never establish
currency units: settings.currencies[settings.currency].subunits is authoritative.
NativeLedger is a conservative one-plan observer. The parent persists raw frames,
claims each send before transport, prevents retries/reconnect replay, and owns fresh
FUN credentials, pacing, socket lifecycle, round association and final reporting.
"""
import copy
from decimal import Decimal
import hashlib
import json
import re

PINS = {
    'BInvestLive': '663cd6a40e9f8d022c8fc3648f5b3d64cf675210589d43c928561666500887b6',
    'DragonsCrash': '9c5a47eaf9c03078993b39eeba4261e4fdd62d61f02e6eef10b38f2726119718',
    'GiftX': '177be69296e30dc5bd2f989c5c583e2db1de91206e43482f149e9e1f734e0cdd',
    'SpaceXY': 'd332893e03646db2c144baea16bc555d3dd8737fc78cda037765c3f98b47403a',
    'TopEagle': '8f3948587ccb5430bccac76f8a8e9248347abf07d64eb5b8aa9bd6be5ee35255',
}
CHANNEL = 'CrashGames::GameChannel'


def metadata(gid, source):
    digest = hashlib.sha256(source.encode('utf8')).hexdigest()
    if gid not in PINS or digest != PINS[gid]:
        raise ValueError('Exact reviewed source for this game required')
    needles = ['window.__OPTIONS__.websocket_url', 'CrashGames::GameChannel',
               'createConsumer']
    for pattern in [r'command:"message",identifier:this.identifier,data:JSON\.stringify\([te]\)', r'[et]\.action=[et],this\.send\([et]\)']:
        match = re.search(pattern, source)
        if not match:
            raise ValueError('ActionCable serialization contract missing')
        needles.append(match.group(0))
    invest = gid == 'BInvestLive'
    if invest:
        needles += ['connected(){this.perform("game_info")}', 'Wt=0',
                    'bet_cents:t,time:e,request_id:Wt,bet_type:i',
                    'Gt.perform("cancel_bet",{uuid:t,request_id:Wt}),Wt++',
                    'makeBet(o.A.data.totalBet,Date.now(),"increase")',
                    'makeBet(o.A.data.totalBet,Date.now(),"decrease")',
                    'CORE_STATES:{BETTING:{name:"waiting"',
                    'o.A.data.currency=t.currencies[t.currency].code',
                    'o.A.data.currencyDivider=o.A.data.currencies[t.currency].subunits',
                    'case"balance":o.A.currentScene.updateBalance(t.changes.value)',
                    'void 0!==(null==i?void 0:i.win_cents)',
                    'o.A.data.stats.profit+=o.A.data.win_cents']
        levels, native = [], []
        first_id, cashout_time = 0, False
    else:
        levels_match = re.search(r'cashOutLevels=\[([^\]]+)\]', source)
        if not levels_match:
            raise ValueError('Explicit UI automatic targets missing')
        levels = levels_match.group(1).split(',')
        # Source UI explicitly multiplies displayed target by 100, separate from money.
        scale = re.search(r'auto_cashout_set_on=Math\.round\([te]\*([\w$]+)\)\|\|void 0', source)
        if not scale or not re.search(r'\b' + re.escape(scale.group(1)) + r'=100\b', source):
            raise ValueError('Automatic multiplier conversion not proved')
        native = [int(Decimal(value) * 100) for value in levels]
        needles += [levels_match.group(0), scale.group(0),
                    'auto_cashout_set_on:', 'time:Date.now()',
                    'this.isCurrencyInitialized', 'currencyDivider', 'subunits',
                    'case"player_bets"', 'case"balance"',
                    'this._fixClientIdForBet', 'requestId===',
                    'lastReceivedBalance']
        reserve = re.search(r'\b[\w$]+-=[\w$]+\.bet_cents', source)
        if not reserve:
            raise ValueError('Source pending reservation display missing')
        needles.append(reserve.group(0))
        first_id, cashout_time = 2, gid != 'GiftX'
    evidence = []
    for needle in needles:
        offset = source.find(needle)
        if offset < 0:
            raise ValueError('Reviewed source contract missing: ' + needle)
        evidence.append(dict(offset=offset, excerpt=needle))
    for pattern in [r'connected\(\)\{[^}]{0,100}game_info[^}]*\}',
                    r'send\([te],[et]\)\{return[^}]+\}',
                    r'\.send\("(?:make_bet|cancel_bet|cashout)",\{[^}]+\}',
                    r'case"settings":[^;]{0,160}',
                    r'case"balance":[^;]{0,160}']:
        for match in re.finditer(pattern, source):
            evidence.append(dict(offset=match.start(), excerpt=match.group(0)))
    return dict(game_id=gid, source_sha256=digest, source_verified=True,
                channel=CHANNEL, transport='ActionCable JSON websocket',
                websocket_url_source='window.__OPTIONS__.websocket_url',
                subprotocol='actioncable-v1-json',
                actions=['game_info', 'make_bet', 'cancel_bet'] + ([] if invest else ['cashout']),
                first_bet_request_id=first_id, cashout_time=cashout_time,
                auto_targets_ui=levels, auto_targets_native=native,
                direction_choices=['increase', 'decrease'] if invest else [],
                betting_phase='waiting' if invest else 'awaiting',
                evidence=evidence,
                unknowns=['No received fresh WS game_info or action fixtures yet.',
                          'Successful initial request_id echo requires received proof; no amount-only matching is permitted.',
                          'Server payout rounding/fees and native debit timing must be observed; bot simulation formulas are not server evidence.',
                          'Native final balance verification is a snapshot; parent must retain delayed packets and synchronization errors before completing a mode.'])


def _meta(meta):
    gid = meta.get('game_id')
    if gid not in PINS or not meta.get('source_verified') or meta.get('source_sha256') != PINS[gid]:
        raise ValueError('Pinned source metadata required')
    return gid


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Native integer outside contract')
    return value


def game_info_action(meta):
    _meta(meta)
    return {'action': 'game_info'}


def decode_frame(meta, frame):
    """Validate one already decoded ActionCable frame; no send or subscription side effects."""
    _meta(meta)
    if not isinstance(frame, dict):
        raise ValueError('ActionCable frame object required')
    kind = frame.get('type')
    if kind in ('welcome', 'ping', 'disconnect'):
        return dict(kind='control', type=kind, frame=copy.deepcopy(frame))
    identifier = frame.get('identifier')
    try:
        channel = json.loads(identifier)
    except (TypeError, ValueError):
        raise ValueError('ActionCable channel identifier required') from None
    if channel != {'channel': CHANNEL}:
        raise ValueError('Different ActionCable subscription')
    if kind in ('confirm_subscription', 'reject_subscription'):
        return dict(kind='control', type=kind, frame=copy.deepcopy(frame))
    message = frame.get('message')
    _packets(message)
    return dict(kind='game_message', message=copy.deepcopy(message))


def _packets(message):
    if not isinstance(message, dict):
        raise ValueError('Game message object required')
    if message.get('error'):
        return []
    packets = message.get('data')
    if not isinstance(packets, list) or any(not isinstance(p, dict) or not isinstance(p.get('state'), str) or 'changes' not in p for p in packets):
        raise ValueError('Game data/state/changes packet array required')
    return packets


def _settings(settings):
    if not isinstance(settings, dict):
        raise ValueError('Native settings required')
    currencies = settings.get('currencies', {})
    currency_id = settings.get('currency')
    currency = currencies.get(str(currency_id), currencies.get(currency_id, {}))
    if currency.get('code') != 'FUN':
        raise ValueError('Only selected native FUN currency is authorized')
    subunits = _integer(currency.get('subunits'), 1)
    minimum = _integer(settings.get('min_bet'), 1)
    maximum = _integer(settings.get('max_bet'), minimum)
    default = _integer(settings.get('default_bet', minimum), minimum)
    if default > maximum:
        raise ValueError('Default native bet exceeds maximum')
    return dict(currency_code='FUN', currency_id=currency_id, subunits=subunits,
                min_bet_native=minimum, max_bet_native=maximum, default_bet_native=default)


def game_info(meta, messages, *, owned_fresh):
    """Validate received source settings/balance/round, never assume FUN from launch URL."""
    gid = _meta(meta)
    if owned_fresh is not True:
        raise ValueError('Fresh owned public demo context required')
    found = {}
    for message in messages:
        if message.get('error'):
            raise ValueError('Game info error; no paid action permitted')
        for item in _packets(message):
            state, changes = item['state'], item['changes']
            if state == 'player_bets' and changes:
                raise ValueError('Existing own bets require separate recovery, not a new WS plan')
            if state == 'freespins' and changes and changes.get('status') in ('active', 'available'):
                raise ValueError('Funded/free rounds outside minimum ordinary FUN scope')
            found[state] = changes
    context = _settings(found.get('settings'))
    balance = _integer(found.get('balance', {}).get('value'))
    status = found.get('round', {}).get('status')
    if status not in ('created', 'awaiting', 'preparing', 'running', 'finished'):
        raise ValueError('Source round status missing')
    if gid == 'BInvestLive':
        bets = found['settings'].get('line_bets')
        if not isinstance(bets, list) or not bets or any(type(b) is not int or b <= 0 for b in bets) or context['min_bet_native'] not in bets:
            raise ValueError('BInvest native line_bets do not confirm minimum')
    context.update(game_id=gid, source_sha256=meta['source_sha256'], owned_fresh=True,
                   balance_native=balance, phase=status, owned_bets={}, coefficient_native=None,
                   bootstrap_note='BInvest awaits a source waiting packet before betting; raw round awaiting alone does not prove restored core UI readiness.')
    return context


def mode_plan(meta, context):
    gid = _meta(meta)
    if context.get('game_id') != gid or context.get('currency_code') != 'FUN' or not context.get('owned_fresh'):
        raise ValueError('Validated owned FUN game info required')
    minimum = context['min_bet_native']
    if gid == 'BInvestLive':
        return [dict(name=name, direction=direction, bet_native=minimum, maximum_rounds=1,
                     closes_by='matching UUID cancellation plus fresh balance' if name.startswith('cancel') else 'received own outcome plus fresh balance and finished round')
                for name, direction in [('increase', 'increase'), ('decrease', 'decrease'), ('cancel_increase', 'increase'), ('cancel_decrease', 'decrease')]]
    out = [dict(name='manual_cashout', bet_native=minimum, maximum_rounds=1),
           dict(name='cancel', bet_native=minimum, maximum_rounds=1)]
    out.extend(dict(name='auto_' + str(target), auto_native=target, bet_native=minimum, maximum_rounds=1)
               for target in meta['auto_targets_native'])
    if 2 * minimum <= context['max_bet_native']:
        out.append(dict(name='two_native_minimum_bets', bet_native=minimum, bet_count=2,
                        maximum_rounds=1, closes_by='each own UUID terminal + whole native ledger'))
    return out


def prepare(meta, context, action, request_id, *, now_ms=None, auto_native=None, direction=None, uuid=None):
    """One exact source action; parent claims/persists before sending, never retries."""
    gid = _meta(meta)
    if context.get('game_id') != gid or context.get('source_sha256') != meta['source_sha256'] or context.get('currency_code') != 'FUN' or not context.get('owned_fresh'):
        raise ValueError('Received validated FUN context required')
    _integer(request_id, meta['first_bet_request_id'])
    if action not in meta['actions'] or action == 'game_info':
        raise ValueError('Unproved paid action')
    owned = context.get('owned_bets', {})
    result = dict(action=action, request_id=request_id)
    phase = context.get('phase')
    if action == 'make_bet':
        if phase != meta['betting_phase']:
            raise ValueError('Source betting phase not observed')
        stake = _integer(context['min_bet_native'], 1)
        if context['balance_native'] < stake or len([b for b in owned.values() if b['status'] == 'accepted']) >= (1 if gid == 'BInvestLive' else 2):
            raise ValueError('Insufficient native balance or source slot limit')
        result.update(bet_cents=stake, time=_integer(now_ms, 1))
        if gid == 'BInvestLive':
            if direction not in ('increase', 'decrease') or auto_native is not None:
                raise ValueError('BInvest requires source direction, has no cashout target')
            result['bet_type'] = direction
        else:
            if direction is not None:
                raise ValueError('Crash bet has no direction field')
            if auto_native is not None:
                if type(auto_native) is not int or auto_native not in meta['auto_targets_native']:
                    raise ValueError('Automatic target is a source multiplier integer, not a monetary amount')
                result['auto_cashout_set_on'] = auto_native
    else:
        bet = owned.get(uuid)
        if not isinstance(uuid, str) or not uuid or not bet or bet['status'] != 'accepted':
            raise ValueError('Currently accepted owned UUID required')
        if action == 'cancel_bet' and phase != meta['betting_phase']:
            raise ValueError('Cancel outside source betting phase')
        if action == 'cashout' and (phase != 'running' or (gid == 'GiftX' and (context.get('coefficient_native') or 0) < 101)):
            raise ValueError('Cashout outside source running/minimum coefficient gate')
        result['uuid'] = uuid
        if action == 'cashout' and meta['cashout_time']:
            result['time'] = _integer(now_ms, 1)
    return result


class NativeLedger:
    """Own UUID ledger with delayed absolute native balance reconciliation.

    register() is a once-only in-memory intent marker, never a send. Parent must
    persist its marker before transport and must not recreate ledger to retry an
    uncertain send. Successful initial bet acknowledgement requires exact top-level
    request_id and source bet amount/currency, never amount-only UI fallback.
    """
    def __init__(self, meta, context):
        _meta(meta)
        if context.get('game_id') != meta['game_id'] or context.get('source_sha256') != meta['source_sha256']:
            raise ValueError('Game/context proof mismatch')
        self.meta = copy.deepcopy(meta)
        self.base = copy.deepcopy(context)
        self.initial = _integer(context['balance_native'])
        self.balance = self.initial
        self.phase = context['phase']
        self.coefficient = context.get('coefficient_native')
        self.sequence = self.balance_at = self.finished_at = 0
        self.requests = {}
        self.bets = {}
        self.next_request_id = meta['first_bet_request_id']
        self.blocked = None

    def context(self):
        context = copy.deepcopy(self.base)
        context.update(balance_native=self.balance, phase=self.phase,
                       coefficient_native=self.coefficient, owned_bets=copy.deepcopy(self.bets))
        return context

    def register(self, action):
        if self.blocked or action.get('request_id') != self.next_request_id:
            raise ValueError('Blocked context, reused or skipped request ID; no replay')
        expected = prepare(self.meta, self.context(), action.get('action'), action.get('request_id'),
                           now_ms=action.get('time'), auto_native=action.get('auto_cashout_set_on'),
                           direction=action.get('bet_type'), uuid=action.get('uuid'))
        if action != expected:
            raise ValueError('Unproved wire fields')
        if any(r['status'] == 'pending' for r in self.requests.values()):
            raise ValueError('Wait for outstanding owned action before next send')
        self.requests[action['request_id']] = dict(action=copy.deepcopy(action), status='pending')
        self.next_request_id += 1

    def ingest(self, message):
        if message.get('error'):
            self.blocked = dict(error=message['error'], request_id=message.get('request_id'))
            request = self.requests.get(message.get('request_id'))
            if request:
                request['status'] = 'rejected'
            raise ValueError('Provider websocket error retained; no automatic retry')
        snapshot = copy.deepcopy(self.__dict__)
        try:
            self._ingest(message)
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            raise

    def _ingest(self, message):
        self.sequence += 1
        request_id = message.get('request_id')
        for packet in _packets(message):
            state, changes = packet['state'], packet['changes']
            if state == 'settings':
                current = _settings(changes)
                if any(current[k] != self.base[k] for k in ('currency_code', 'currency_id', 'subunits')):
                    raise ValueError('Native currency changed within owned plan')
            elif state == 'balance':
                self.balance, self.balance_at = _integer(changes.get('value')), self.sequence
            elif state == 'round':
                self.phase = changes.get('status')
                if self.phase == 'finished':
                    self.finished_at = self.sequence
            elif state == 'waiting' and self.meta['game_id'] == 'BInvestLive':
                self.phase = 'waiting'
            elif state == 'game':
                if self.meta['game_id'] == 'BInvestLive':
                    self.phase = 'game'
                elif 'coefficient' in changes:
                    self.coefficient = _integer(changes['coefficient'])
            elif state == 'synchronize_errors':
                data = changes.get('changes', changes)
                if data.get('status') != 'success':
                    self.blocked = dict(kind='synchronize_errors', details=copy.deepcopy(changes))
            elif state == 'player_bets' or state == 'bets':
                values = changes if isinstance(changes, list) else [changes]
                for value in values:
                    if isinstance(value, str):
                        if state == 'player_bets' and value in self.bets:
                            request = self.requests.get(request_id)
                            if not request or request['action']['action'] != 'cancel_bet' or request['action']['uuid'] != value:
                                raise ValueError('Removal lacks exact owned cancellation request ID')
                            bet = self.bets[value]
                            if bet['status'] != 'accepted':
                                raise ValueError('Owned UUID already terminal')
                            bet.update(status='canceled', terminal_at=self.sequence)
                            request['status'] = 'accepted'
                        continue
                    if not isinstance(value, dict):
                        raise ValueError('Unknown bet entry schema')
                    uuid = value.get('uuid')
                    if not isinstance(uuid, str) or not uuid:
                        raise ValueError('Source bet UUID required')
                    bet = self.bets.get(uuid)
                    if bet is None:
                        if state == 'bets':
                            continue  # Broadcast players never create an owned wager.
                        request = self.requests.get(request_id)
                        if not request or request['action']['action'] != 'make_bet' or request['status'] != 'pending':
                            raise ValueError('First own acknowledgement requires exact pending request ID')
                        sent = request['action']
                        if value.get('bet_cents') != sent['bet_cents'] or value.get('currency') != self.base['currency_id']:
                            raise ValueError('Native own bet acknowledgement differs from request/currency')
                        if self.meta['game_id'] == 'BInvestLive':
                            if value.get('bet_type') != sent['bet_type']:
                                raise ValueError('BInvest direction not confirmed')
                        elif (value.get('auto_cashout_set_on') or None) != sent.get('auto_cashout_set_on'):
                            raise ValueError('Automatic target differs from source request')
                        bet = dict(status='accepted', stake_native=sent['bet_cents'], payout_native=None,
                                   make_request_id=request_id, accepted_at=self.sequence)
                        self.bets[uuid] = bet
                        request['status'] = 'accepted'
                    if 'currency' in value and value['currency'] != self.base['currency_id']:
                        raise ValueError('Own UUID currency changed')
                    if 'bet_cents' in value and value['bet_cents'] != bet['stake_native']:
                        raise ValueError('Own UUID stake changed')
                    if 'win_cents' in value:
                        _integer(value['win_cents'])
                    # Crash clients branch on truthiness; BInvest branches on definedness.
                    if 'win_cents' in value and (self.meta['game_id'] == 'BInvestLive' or value['win_cents'] > 0):
                        payout = value['win_cents']
                        if bet['status'] == 'canceled' or (bet['payout_native'] is not None and bet['payout_native'] != payout):
                            raise ValueError('Conflicting terminal own UUID result')
                        if bet['payout_native'] is None:
                            bet.update(status='paid', payout_native=payout, terminal_at=self.sequence)
                        for request in self.requests.values():
                            if request['status'] == 'pending' and request['action'].get('action') == 'cashout' and request['action'].get('uuid') == uuid:
                                if request_id is not None and request_id != request['action']['request_id']:
                                    raise ValueError('Cashout response request ID mismatch')
                                request['status'] = 'accepted'

    def reconcile(self):
        if self.blocked:
            return dict(status='blocked', reason=copy.deepcopy(self.blocked))
        if not self.requests or any(r['status'] == 'pending' for r in self.requests.values()):
            return dict(status='pending', reason='Owned action acknowledgement unresolved')
        if not self.bets:
            return dict(status='pending', reason='No accepted own UUID')
        all_canceled = all(b['status'] == 'canceled' for b in self.bets.values())
        if not all_canceled and (not self.finished_at or self.finished_at < max(b['accepted_at'] for b in self.bets.values())):
            return dict(status='pending', reason='Parent round has not finished')
        barrier = max([b.get('terminal_at', b['accepted_at']) for b in self.bets.values()] + ([] if all_canceled else [self.finished_at]))
        if self.balance_at < barrier:
            return dict(status='pending', reason='Await native balance from terminal frame or later')
        cost = sum(b['stake_native'] for b in self.bets.values() if b['status'] != 'canceled')
        payout = sum(b['payout_native'] or 0 for b in self.bets.values() if b['status'] != 'canceled')
        expected = self.initial - cost + payout
        if self.balance != expected:
            raise ValueError('Native websocket ledger mismatch; never alter balances or replay')
        return dict(status='verified', initial_native=self.initial, cost_native=cost,
                    payout_native=payout, expected_native=expected, actual_native=self.balance,
                    native_snapshot_sequence=self.balance_at, terminal_sequence=barrier,
                    own_uuids=sorted(self.bets), outcome_scope='Received UUID payouts plus finished-round native reconciliation; no server rounding formula assumed', ok=True)
