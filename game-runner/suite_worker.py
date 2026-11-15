"""Offline suite binding and one-shot local bridge. Native journals remain private.

The collector owns protocol encoding; this bridge never reconstructs a payout from
wallets and never treats a wallet_check flag as a monetary receipt.
"""
import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
from decimal import Decimal, ROUND_DOWN, localcontext

SUPPORTED = {'nolimit', 'elk', 'pragmatic', 'reelkingdom', 'endorphina', 'hacksaw',
             'threeoaks', 'habanero', 'playngo', 'ela-games', 'amigogaming',
             'peterandsons', 'thunderspin', 'bgaming', 'netent', 'playson',
             'rubyplay', '1spin4win', 'egt-digital', 'irondog', 'smartsoft',
             'spinomenal', 'betsoft', 'playtech', 'evoplay', 'mascot', 'yggdrasil',
             'kagaming', 'belatra', 'redtiger', 'amusnet'}
# These reviewed workers currently depend on browser-owned transport/state. An
# HTTP bridge must not silently open a browser or borrow that owner's campaign.
BROWSER = {'kagaming', 'belatra', 'netent', 'playson'}
FILES = {
    'redtiger': ['bet-collector/collection_redtiger_http.py',
                 'provider-work/redtiger/reconciled-coverage.json'],
    'nolimit': ['demo-dashboard/nolimit_client.py', 'demo-dashboard/nolimit_protocol.py', 'demo-dashboard/nolimit_run.py'],
    'elk': ['demo-dashboard/elk_client.py', 'demo-dashboard/elk_protocol.py'],
    'pragmatic': ['demo-dashboard/catalog_smoke.py', 'demo-dashboard/catalog_lifecycle.py', 'demo-dashboard/coverage_inventory.py', 'demo-dashboard/coverage_branches.py'],
    'endorphina': ['demo-dashboard/endorphina_client.py', 'demo-dashboard/endorphina_rounds.py'],
    'playngo': ['demo-dashboard/playngo_client.py', 'demo-dashboard/playngo_rules.py'],
    'ela-games': ['ela-games-private/direct_demo.py'],
    'habanero': ['provider-work/habanero-export/data/habanero-brandgameid-map-all.json', 'provider-work/habanero-export/data/habanero-samples.json'],
    '1spin4win': ['provider-work/mocks/1spin4win/harvest.py', 'provider-work/mocks/1spin4win/build_bank.py'],
    'smartsoft': ['smartsoft-private/cobertura-slots.json'],
    'threeoaks': ['demo-dashboard/threeoaks/reference/serializer-bindings.json',
                  'demo-dashboard/threeoaks/reference/continuation-bindings.json',
                  'demo-dashboard/threeoaks/reference/lucky_penny_2.client.js'],
    'egt-digital': ['provider-work/mocks/egt-digital/harvest.py'],
    'irondog': ['provider-work/mocks/irondog/harvest.py'],
    'spinomenal': ['spinomenal-private/client.py', 'spinomenal-private/tower_client.py', 'spinomenal-private/table_client.py', 'spinomenal-private/all_modes.py'],
    'betsoft': ['betsoft-private/inspect_demo.py', 'betsoft-private/audit.py', 'betsoft-private/rounds-audit.json',
                'demo-dashboard/betsoft/summary.json'],
    'playtech': ['playtech-private-root/run_direct_game.py', 'provider-work/playtech-root/direct_session.py',
                 'provider-work/playtech-root/playtech_engine/primitives.py',
                 *['provider-work/playtech-root/' + name for name in ('native-gpas-catalog.json',
                    'catalog-capture-status.json', 'native-command-bindings.json',
                    'supplier-catalogue-plan.json', 'catalog-complete.json')]],
    'evoplay': ['bet-collector/full_playtech_evoplay_families.py', 'demo-dashboard/evoplay/slot_bootstrap.py'],
    'bgaming': ['provider-work/bgaming-chat4/run_demo_qa.py', 'provider-work/bgaming-chat4/native_variants.py'],
    'rubyplay': ['provider-work/rubyplay-chat2/' + name for name in (
        'native_contracts.json', 'catalogs/official-links.json', 'results/live-summary.json',
        'prepare_next_game.py', 'open_next_session.py', 'validate_next_init.cjs',
        'native_bundle.cjs', 'plan_next_normal.cjs')],
}
for _pid, _names in {'amigogaming': ('discover', 'native', 'live_actions', 'campaign'),
                     'thunderspin': ('native', 'contracts', 'campaign'),
                     'peterandsons': ('analyze_hars', 'protocol', 'campaign')}.items():
    FILES[_pid] = [f'provider-work/{_pid}-chat4/code/{name}.py' for name in _names]
FILES['reelkingdom'] = FILES['pragmatic']


_WINDOWS_JOB = None


def install_process_job():
    """Keep descendants owned even after this Windows worker terminates.

    Win32 layouts/semantics follow Microsoft's JOBOBJECT_BASIC_LIMIT_INFORMATION,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION and AssignProcessToJobObject docs.
    No breakaway flag or inheritable job handle is granted to children.
    """
    global _WINDOWS_JOB
    if os.name != 'nt' or _WINDOWS_JOB is not None:
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                    ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                     'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.argtypes = ()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.SetHandleInformation.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
    kernel.SetHandleInformation.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError('suite_windows_job_creation_unavailable:' + str(ctypes.get_last_error()))
    information = ExtendedLimits()
    information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    if (not kernel.SetHandleInformation(handle, 1, 0)
            or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(information), ctypes.sizeof(information))
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise RuntimeError('suite_windows_job_assignment_unavailable:' + str(error))
    # Do not close this handle from atexit: it also owns our process. The kernel
    # closes it on exit/termination and kills children, even with redirected IO.
    _WINDOWS_JOB = (kernel, handle)

def read(path):
    # Decimal preserves native JSON precision, including tiny nonzero payouts.
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_float=Decimal)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def durable(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, default=str)
        stream.flush()
        os.fsync(stream.fileno())


def identity(mode):
    return {key: mode.get(key) for key in ('key', 'type', 'requires_prerequisites', 'execution_source')}


NATIVE_CASE_PROVIDERS = {'smartsoft', 'threeoaks', 'rubyplay', 'bgaming', 'betsoft', 'spinomenal'}


def binding(provider, game, mode):
    identity = [provider, str(game['id']), game.get('record', {}), mode]
    if provider == 'playtech' and os.environ.get('EVIDENCIA_PLAYTECH_ROOT'):
        identity.append(str(resolve_local_root(os.environ['EVIDENCIA_PLAYTECH_ROOT'])))
    if provider in NATIVE_CASE_PROVIDERS and os.environ.get('EVIDENCIA_NATIVE_CASE_ROOT'):
        identity.append(str(resolve_local_root(os.environ['EVIDENCIA_NATIVE_CASE_ROOT'])))
    if provider == 'redtiger':
        for module in ('collection_redtiger_http', 'collection_full_misc'):
            source = importlib.util.find_spec(module)
            if source and source.origin:
                identity.append(hashlib.sha256(Path(source.origin).read_bytes()).hexdigest())
    return digest(identity)


def require_identity(expected, actual):
    if identity(expected) != identity(actual):
        raise ValueError('suite_inventory_mode_identity_changed')


def offline_audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise RuntimeError('offline_preflight_external_io_forbidden')


def setup(root):
    root = Path(root).resolve(strict=True)
    if not (root / 'bet-collector/collection_worker.py').is_file():
        raise ValueError('suite_collection_worker_missing')
    sys.path[:0] = [str(root / 'bet-collector'), str(root / 'bet-collector/vendor'), str(root / 'demo-dashboard')]
    return root


@lru_cache(maxsize=4)
def resolve_local_root(path):
    return Path(path).resolve(strict=True)


def provider_root(root, provider):
    if provider == 'playtech' and os.environ.get('EVIDENCIA_PLAYTECH_ROOT'):
        return resolve_local_root(os.environ['EVIDENCIA_PLAYTECH_ROOT'])
    if provider in NATIVE_CASE_PROVIDERS and os.environ.get('EVIDENCIA_NATIVE_CASE_ROOT'):
        return resolve_local_root(os.environ['EVIDENCIA_NATIVE_CASE_ROOT'])
    return root


def monetary_binding(provider, game=None):
    # Literal values below are already fixed and checked by those demo protocol
    # launchers; other providers must emit their native currency or bind it.
    known = {
        'yggdrasil': {'currency': 'EUR', 'currency_source': 'launcher_parameter', 'monetary_unit': 'major'},
        'mascot': {'currency': 'NAN', 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'egt-digital': {'currency': 'EGT', 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'elk': {'currency': 'EUR', 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'nolimit': {'currency': 'EUR', 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'endorphina': {'native_currency': True, 'monetary_unit': 'major'},
        'pragmatic': {'native_currency': True, 'monetary_unit': 'major'},
        'redtiger': {'native_currency': True, 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'reelkingdom': {'native_currency': True, 'monetary_unit': 'major'},
        'ela-games': {'native_currency': True, 'monetary_unit': 'native'},
        'playngo': {'currency': 'DEMO', 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'playtech': {'native_currency': True, 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'smartsoft': {'currency': 'DMO', 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'threeoaks': {'currency': 'FUN', 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'rubyplay': {'native_currency': True, 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'bgaming': {'currency': 'FUN', 'currency_source': 'native_response', 'monetary_unit': 'native'},
        'betsoft': {'currency': 'EUR', 'currency_source': 'native_response', 'monetary_unit': 'major'},
        'habanero': {'monetary_unit': 'major'},
    }
    value = dict(known.get(provider, {'monetary_unit': 'native'}))
    if provider == 'spinomenal' and str((game or {}).get('id', '')).startswith(('SlotMachine_', 'Tower_')):
        value['native_currency'] = True  # The bound FUN client supplies denomination metadata in its receipt.
    currency = (game or {}).get('record', {}).get('currency')
    if isinstance(currency, str) and currency.strip():
        value.setdefault('currency', currency)
        value.setdefault('currency_source', 'public_binding')
    return value


def ledger_contract_gaps(root, provider, game, mode):
    record = game.get('record', {})
    if provider == 'betsoft':
        from collection_full_misc import betsoft_currency_modes, betsoft_gamble_bound_modes, betsoft_modern_bound_modes, betsoft_root
        key = (record.get('game_id'), mode['key'])
        source = betsoft_root()
        if (key not in betsoft_currency_modes(source) and key not in betsoft_modern_bound_modes(source)
                and key not in betsoft_gamble_bound_modes(source)):
            return ['suite_betsoft_verified_legacy_currency_unavailable']
    if provider == 'bgaming':
        if 'game_id' not in record:
            return ['suite_independent_native_ledger_export_missing']
        from collection_full_node import bgaming_root, bgaming_rpc_modes, bgaming_rust_modes, bgaming_v1_modes, bgaming_v2_modes
        game_id = record['game_id']
        if mode['key'] in bgaming_v2_modes(game_id):
            return []
        if mode['key'] in bgaming_rust_modes(game_id):
            name = 'bgaming.exe' if os.name == 'nt' else 'bgaming'
            if (provider_root(root, provider) / 'bet-collector/game-runner/target/release' / name).is_file():
                return []
            return ['suite_missing_native_binary:bgaming']
        if mode['key'] in bgaming_rpc_modes(bgaming_root(), game_id):
            return []
        if mode['key'] in bgaming_v1_modes(bgaming_root(), game_id):
            return []
        return ['suite_independent_native_ledger_export_missing']
    if provider == 'playtech' and (record.get('engine') != 'gpas'
                                  or not mode.get('spec', {}).get('native_id')):
        return ['suite_gpas_explicit_native_mode_required']
    if provider == 'irondog':
        return ['suite_native_demo_wallet_contract_unavailable']
    if provider == 'habanero' and record.get('family') != 'play':
        return ['suite_independent_native_cost_contract_missing']
    if provider == 'mascot' and 'table_sha256' not in record:
        import collection_mascot as mascot
        bank, _ = mascot.load_bank(record['demo_id'])
        entry = mode.get('spec', {}).get('entry')
        rows = [row for row in bank['rounds'] if row.get('steps') and row['steps'][0]['request'] == entry]
        if not rows or any(len(mascot.winnings([step['response'] for step in row['steps']])) != 1 for row in rows):
            return ['suite_native_payout_contract_ambiguous']
    return []

@lru_cache(maxsize=128)
def provider_prerequisite_gaps(root, provider):
    gaps = []
    if provider not in SUPPORTED:
        gaps.append('suite_provider_contract_unreviewed')
    if provider in BROWSER:
        gaps.append('suite_browser_transport_requires_separate_owner')
    if provider == 'kendoo':
        gaps.append('provider_paused_by_user')
    for relative in FILES.get(provider, []):
        if not (root / relative).is_file():
            gaps.append('suite_missing_source:' + relative)
    for module in ('requests', 'websocket'):
        if importlib.util.find_spec(module) is None:
            gaps.append('suite_missing_python_dependency:' + module)
    if provider in ('hacksaw', 'smartsoft', 'threeoaks'):
        name = provider + ('.exe' if os.name == 'nt' else '')
        if not (root / 'bet-collector/game-runner/target/release' / name).is_file():
            gaps.append('suite_missing_native_binary:' + provider)
    if provider == 'rubyplay' and shutil.which('node') is None:
        gaps.append('suite_missing_runtime:node')
    return tuple(gaps)


def prerequisite_gaps(root, provider, game=None, mode=None):
    gaps = list(provider_prerequisite_gaps(provider_root(root, provider), provider))
    if game is not None and game.get('ready') is False:
        gaps.append('suite_game_not_ready')
    if mode is not None:
        if mode.get('ready') is False:
            gaps.append('suite_mode_not_ready')
        if mode.get('execution_source') == 'local_model' or (game or {}).get('record', {}).get('engine') == 'ngm':
            gaps.append('local_model_not_remote_settlement')
    if game is not None and mode is not None:
        gaps.extend(ledger_contract_gaps(root, provider, game, mode))
    return gaps


def provider_games(catalog, provider):
    extra = next((module for module in catalog.EXTRAS if provider in module.SUPPORTED), None)
    if extra:
        return extra.load_games(provider) or []
    if provider in ('pragmatic', 'reelkingdom'):
        return catalog.load_pragmatic()
    if provider == 'habanero':
        return catalog.load_habanero()
    if provider in catalog.SUPPORTED:
        return catalog.load_native(provider)
    return []


def capabilities(root):
    import collection_catalog as catalog
    result = {'schema_version': 1, 'entries': [], 'provider_gaps': {}}
    for provider in sorted(SUPPORTED | {'kendoo'}):
        gaps = prerequisite_gaps(root, provider)
        if gaps:
            result['provider_gaps'][provider] = gaps
            continue
        try:
            games = provider_games(catalog, provider)
        except Exception as exc:
            result['provider_gaps'][provider] = ['suite_inventory_unavailable:' + type(exc).__name__]
            continue
        if not games:
            result['provider_gaps'][provider] = ['suite_inventory_inputs_missing']
        try:
            entries = [
                dict(provider=provider, game=str(game['id']), mode=identity(mode),
                     binding_sha256=binding(provider, game, mode), monetary_binding=monetary_binding(provider, game),
                     gaps=prerequisite_gaps(root, provider, game, mode))
                for game in games for mode in game.get('modes', [])
            ]
        except ImportError as exc:
            result['provider_gaps'][provider] = ['suite_inventory_unavailable:' + type(exc).__name__]
            continue
        result['entries'].extend(entries)
    return result


def select_case(root, request):
    import collection_catalog as catalog
    provider = request['provider']
    gaps = prerequisite_gaps(root, provider)
    if gaps:
        raise ValueError(';'.join(gaps))
    games = [game for game in provider_games(catalog, provider) if str(game['id']) == request['game']]
    if len(games) != 1:
        raise ValueError('suite_game_identity_missing_or_ambiguous')
    game = games[0]
    modes = [mode for mode in game['modes'] if mode['key'] == request['mode']['key']]
    if len(modes) != 1:
        raise ValueError('suite_mode_identity_missing_or_ambiguous')
    mode = modes[0]
    require_identity(request['mode'], mode)
    if binding(provider, game, mode) != request['binding_sha256']:
        raise ValueError('suite_native_binding_changed_since_preflight')
    gaps = prerequisite_gaps(root, provider, game, mode)
    if gaps:
        raise ValueError(';'.join(gaps))
    budget = request.get('max_prerequisite_rounds', 0)
    if type(budget) is not int or not 0 <= budget <= 100:
        raise ValueError('suite_invalid_prerequisite_budget')
    if mode.get('requires_prerequisites') and not budget:
        raise ValueError('suite_prerequisite_budget_required')
    return dict(provider=provider, canonical_provider='pragmatic' if provider == 'reelkingdom' else provider,
                game_id=str(game['id']), canonical_game_id=str(game.get('canonical_id', game['id'])),
                game_name=game.get('name', str(game['id'])), game=game.get('record', {}), mode=mode,
                type=mode['type'], prerequisite_limit=budget,
                execution_source=mode.get('execution_source', 'native_remote'))


def money(value):
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ValueError('suite_missing_or_inexact_native_money')
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError('suite_invalid_native_money')
    return amount


def transport_steps(folder):
    journal = Path(folder) / 'transport.jsonl'
    if not journal.is_file() or journal.is_symlink():
        return []
    steps, http_endpoints, sockets = [], {}, {}
    fields = {'method': 'method', 'body': 'payload', 'payload': 'payload',
              'sequence': 'request_sequence', 'connection': 'connection',
              'status': 'http_status', 'phase': 'phase', 'error': 'error',
              'body_file': 'response_file'}
    with journal.open(encoding='utf8') as stream:
        for ordinal, line in enumerate(stream, 1):
            event = json.loads(line)
            stage = event['event']
            transport = 'websocket' if '_ws_' in stage or stage.startswith('ws_') else 'http'
            if stage == 'before_http':
                http_endpoints[event['sequence']] = event['url']
            if stage == 'before_ws_connect' and 'connection' in event:
                sockets[event['connection']] = event['url']
            endpoint = event.get('url') or (sockets.get(event.get('connection')) if transport == 'websocket'
                                            else http_endpoints.get(event.get('sequence')))
            step = dict(ordinal=ordinal, stage=stage, transport=transport, endpoint=endpoint)
            if event.get('phase') in ('bootstrap', 'financial_or_unknown'):
                step['financial_intent'] = False if event['phase'] == 'bootstrap' else None
            for key, normalized in fields.items():
                if key in event and (key != 'body' or stage == 'before_http'):
                    step[normalized] = event[key]
            steps.append(step)
    return steps


def normalize_outcome(case, result, folder, settings):
    """Recheck the collector's explicit independent ledger, never its match flag.

    These collector contracts populate win from provider award packets or their
    native auditor. Missing fields are a coverage gap, not a zero or balance delta.
    """
    if result.get('status') != 'completed' or result.get('closed') is not True:
        raise ValueError('suite_native_round_not_closed')
    if result.get('source', case.get('execution_source')) != 'native_remote':
        raise ValueError('suite_nonremote_outcome')
    if result.get('blocked'):
        raise ValueError('suite_provider_block_retained')
    if result.get('requested_mode_observed') is False:
        raise ValueError('suite_conditional_mode_unobserved')
    before = money(result.get('balance_before'))
    after = money(result.get('balance_after'))
    cost = money(result.get('cost'))
    payout = money(result.get('win'))
    if cost <= 0:
        raise ValueError('suite_native_cost_not_positive')
    with localcontext() as ctx:
        ctx.prec = 1000
        if case['provider'] == 'nolimit':
            cents = Decimal('0.01')
            if (result.get('closed_next_mode') != 'NORMAL'
                    or result.get('settlement_rule') != 'truncate_final_balance_2dp'
                    or money(result.get('extra_spin_costs', '0')) != 0
                    or before.quantize(cents) != before or cost.quantize(cents) != cost):
                raise ValueError('suite_nolimit_settlement_preconditions_failed')
            payout = payout.quantize(cents, rounding=ROUND_DOWN)
        matches = before - cost + payout == after
    if settings.get('currency_source') == 'native_response' and not result.get('currency'):
        raise ValueError('suite_native_currency_receipt_missing')
    currency = result.get('currency') or settings.get('currency')
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError('suite_native_currency_binding_missing')
    if result.get('currency') and settings.get('currency') and result['currency'] != settings['currency']:
        raise ValueError('suite_currency_binding_changed')
    unit = result.get('monetary_unit') or settings.get('monetary_unit')
    if unit not in ('major', 'native'):
        raise ValueError('suite_monetary_unit_binding_missing')
    # Every paid preparation must remain explicitly represented. Its own receipt
    # must expose a complete independent ledger before we can certify the attempt.
    prerequisites = result.get('prerequisites', result.get('prerequisite_rounds', []))
    previous_after = None
    for receipt in prerequisites:
        if receipt.get('closed') is not True or not all(receipt.get(k) is not None for k in ('balance_before', 'balance_after', 'cost', 'win')):
            raise ValueError('suite_prerequisite_ledger_incomplete')
        if previous_after is not None and money(receipt['balance_before']) != previous_after:
            raise ValueError('suite_prerequisite_owner_or_ledger_chain_broken')
        previous_after = money(receipt['balance_after'])
        with localcontext() as ctx:
            ctx.prec = 1000
            if money(receipt['balance_before']) - money(receipt['cost']) + money(receipt['win']) != money(receipt['balance_after']):
                raise ValueError('suite_prerequisite_ledger_mismatch')
    if previous_after is not None and previous_after != before:
        raise ValueError('suite_requested_root_not_chained_to_prerequisites')
    accounting = result.get('accounting')
    if accounting is not None:
        if not isinstance(accounting, dict) or accounting.get('uncertain_paid_roots') or accounting.get('requested_mode_observed') is not True:
            raise ValueError('suite_paid_root_accounting_uncertain')
        all_roots = accounting.get('all_paid_rounds', [])
        requested = accounting.get('requested_rounds', [])
        attempts = accounting.get('paid_root_attempts')
        if (type(attempts) is not int or attempts != len(all_roots)
                or accounting.get('closed_paid_roots') != attempts
                or len(requested) != 1 or attempts != len(prerequisites) + 1
                or len(accounting.get('prerequisite_rounds', [])) != len(prerequisites)):
            raise ValueError('suite_paid_root_accounting_incomplete')
        for retained, declared in zip(accounting['prerequisite_rounds'] + requested,
                                      prerequisites + [result]):
            for canonical, native in (('balance_before','balance_before_native'),
                                      ('balance_after','balance_after_native'),
                                      ('cost','cash_debit_native'), ('win','cash_payout_native')):
                if money(retained.get(native)) != money(declared.get(canonical)):
                    raise ValueError('suite_paid_root_accounting_ledger_changed')
            if retained.get('closed') is not True:
                raise ValueError('suite_paid_root_accounting_not_closed')
    manifest = []
    for path in sorted(Path(folder).rglob('*')):
        if path.is_file() and not path.is_symlink():
            manifest.append({'path': path.relative_to(folder).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    native_journal = {'smartsoft': 'smartsoft-native.jsonl', 'threeoaks': 'threeoaks-native.jsonl',
                      'bgaming': 'bgaming-native.jsonl'}.get(case['provider'])
    if not any(item['path'] in ('transport.jsonl', 'native.json', 'native-full-misc.jsonl', native_journal) or item['path'].endswith('.journal.json') for item in manifest):
        raise ValueError('suite_native_owner_and_receipts_missing')
    return dict(native_round_id=str(result['round_id']) if result.get('round_id') is not None else None,
                currency=currency, monetary_unit=unit,
                currency_source=result.get('currency_source', 'native_response') if result.get('currency') else settings.get('currency_source', 'public_binding'),
                balance_before=str(before), balance_after=str(after), cost=str(cost), payout=str(payout), native_closed=True,
                checks={'suite_independent_wallet_ledger': matches, 'suite_native_closure': True, 'suite_prerequisite_ledgers': True},
                native_data={'transport': 'suite_process', 'owner_evidence_directory': str(folder),
                             'native_contract': 'collection_worker:' + case['provider'],
                             'evidence': manifest, 'transport_steps': transport_steps(folder), 'result': result})


def execute(root, folder):
    folder = Path(folder).resolve(strict=True)
    install_process_job()
    request = read(folder / 'bridge-request.json')
    case = select_case(root, request)
    # Exclusive marker prohibits replay even if the caller invokes the script twice.
    durable(folder / 'bridge-dispatched.json', {'attempt_id': folder.name, 'binding_sha256': request['binding_sha256']})
    durable(folder / 'input.json', case)
    from collection_families import execution_contract
    historical = execution_contract(case['provider'],
        {'id': case['game_id'], 'record': case['game'], 'modes': [case['mode']]}, case['mode'], suite=root)
    durable(folder / 'historical-contract.json', historical)
    proxy = 'http://127.0.0.1:8793'
    os.environ.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy,
                      NO_PROXY='127.0.0.1,localhost,::1', PYTHONDONTWRITEBYTECODE='1')
    for name in ('THREEOAKS_BROWSER_LAUNCHER', 'THREEOAKS_TRANSPORT'):
        os.environ.pop(name, None)
    os.chdir(folder)
    sys.argv = [str(root / 'bet-collector/collection_worker.py'), str(folder)]
    # Same process: no untracked extra Python worker and no automatic replay.
    runpy.run_path(str(root / 'bet-collector/collection_worker.py'), run_name='__main__')
    result = read(folder / 'result.json')
    outcome = normalize_outcome(case, result, folder, request)
    durable(folder / 'bridge-outcome.json', outcome)
    return {'outcome_file': 'bridge-outcome.json'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite-root', required=True, type=Path)
    parser.add_argument('--capabilities', action='store_true')
    parser.add_argument('--attempt', type=Path)
    args = parser.parse_args()
    try:
        install_process_job()
        root = setup(args.suite_root)
        if args.capabilities:
            sys.addaudithook(offline_audit)
            answer = capabilities(root)
        else:
            if args.attempt is None:
                raise ValueError('suite_attempt_required')
            answer = execute(root, args.attempt)
        print(json.dumps(answer, default=str))
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'class': type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
