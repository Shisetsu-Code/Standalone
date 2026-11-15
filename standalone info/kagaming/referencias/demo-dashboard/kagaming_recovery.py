"""Read-only audit of a lost French Roulette response using native last-spin data.

The original HTTP response remains missing. This verifier never synthesizes it.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from kagaming_roulette import plans, assert_closed, validate_response

PROJECT = Path(__file__).resolve().parent
DEFAULT_ROOT = PROJECT / 'kagaming/batches/1-100'


def _int(value, label, positive=False):
    assert type(value) is int and value >= (1 if positive else 0), f'invalid integer {label}'
    return value


def _timestamp(value):
    assert type(value) in (int, float) and math.isfinite(value) and value > 0, 'invalid journal timestamp'
    return value


def audit_recovered(case, root=DEFAULT_ROOT):
    result = {'game': case.get('game'), 'mode': case.get('mode'),
              'recovered_from': 'native_initialization', 'passed': False}
    try:
        root = Path(root)
        assert case['game'] == 'FrenchRoulette', 'recovery family unsupported'
        assert case['status'] == 'verified', 'recovery not reviewed as verified'
        assert case['original_response_missing'] is True, 'original missing-response flag required'
        assert case['steps'] == [], 'original response must remain absent; synthetic steps forbidden'
        evidence = case['native_recovery']
        assert evidence['method'] == 'same_identity_initialization_lsd', 'unknown recovery method'
        assert isinstance(evidence['recovery_session_group'], str) and evidence['recovery_session_group'], 'missing recovery group'
        identity = evidence['original_identity_sha256']
        assert isinstance(identity, str) and re.fullmatch('[0-9a-f]{64}', identity), 'invalid identity digest'
        assert identity == evidence['reauthenticated_identity_sha256'], 'recovery identity differs'

        uncertain, query = evidence['uncertain_attempt'], evidence['query']
        assert 'response' not in uncertain and 'http_status' not in uncertain, 'original response evidence is not absent'
        assert uncertain['status'] in ('sending', 'uncertain') and uncertain['path'] == '/kaga/command/spin', 'unrecognized original request journal'
        assert query['status'] == 'received' and type(query['http_status']) is int and query['http_status'] == 200, 'native initialization not received'
        assert query['path'] == '/kaga/rmp/startGame', 'native initialization path required'
        assert _timestamp(query['started_at']) >= _timestamp(uncertain['started_at']), 'query predates uncertain request'
        assert query['request']['gn'] == 'FrenchRoulette', 'query requested another game'
        response = query['response']
        assert response.get('e') is False and type(response.get('ec')) is int and response['ec'] == 0, 'native query failed'
        assert response.get('gn') == 'FrenchRoulette' or response.get('sgr', {}).get('gn') == 'FrenchRoulette', 'native game identity missing'
        for obj in (response, response['sgr']):
            if 'gn' in obj:
                assert obj['gn'] == 'FrenchRoulette', 'native game identity mismatch'
        selected = response['sgr']
        assert selected.get('e') is False and type(selected.get('ec')) is int and selected['ec'] == 0, 'selected game query failed'
        md = selected['lsd']
        assert md.get('v') is True, 'native last spin invalid'

        source = (PROJECT / 'kagaming/reference/frenchroulette.js').read_text(encoding='utf8')
        initialization = json.loads((root / 'initializations/FrenchRoulette.json').read_text(encoding='utf8'))
        profile = case['profile']
        planned = next((p for p in plans(initialization, source) if p['key'] == profile['key']), None)
        assert planned is not None, 'mode absent from source-derived plans'
        for key in ('sel', 'cps', 'dn', 'atb', 'cost_native', 'cost_formula', 'source_sha256',
                    'serialization_source_sha256', 'kind', 'key', 'position'):
            assert profile[key] == planned[key], f'source profile mismatch: {key}'
        for key in ('sel', 'cps', 'atb', 'cost_native'):
            _int(profile[key], f'profile {key}')
        _int(case['atb'], 'case atb')
        assert all(type(x) is int and x >= 0 for x in profile['position']), 'profile stake types'
        assert case['mode'] == planned['kind'] and case['atb'] == planned['atb'], 'case mode differs'
        cost = _int(planned['cost_native'], 'planned cost', True)
        request = uncertain['request']
        assert set(request) == {'gn', 'sel', 'sid', 'cps', 'atb', 'dn', 'pos'}, 'uncertain request shape changed'
        assert request['gn'] == 'FrenchRoulette', 'uncertain request game differs'
        _int(request['sid'], 'original request sid', True)
        for key in ('sel', 'cps', 'atb'):
            _int(request[key], f'request {key}')
        for key in ('sel', 'cps', 'dn', 'atb'):
            assert request[key] == planned[key], f'uncertain request differs: {key}'
        assert request['pos'] == planned['position'], 'uncertain request stake differs'
        assert all(type(x) is int and x >= 0 for x in request['pos']), 'uncertain request stake types'
        assert request['sel'] == sum(x > 0 for x in request['pos']), 'uncertain occupied field count'
        for key in ('cps', 'atb'):
            _int(md[key], f'native {key}')
        for key in ('cps', 'dn', 'atb'):
            assert md[key] == planned[key], f'native last-spin parameter differs: {key}'
        assert 'sel' in md and 'pos' in md and 'st' in md, 'incomplete native roulette evidence'
        assert isinstance(md['pos'], list) and all(type(x) is int and x >= 0 for x in md['pos']), 'native stake types'
        validate_response(md, planned)
        assert_closed(md)
        assert not response.get('fs') and not response.get('rf') and not response.get('bpd'), 'initialization reports pending state'

        previous_name = evidence['previous_case']
        assert isinstance(previous_name, str) and re.fullmatch(r'[A-Za-z0-9_-]+\.json', previous_name), 'unsafe preceding case filename'
        previous_bytes = (root / 'traces' / previous_name).read_bytes()
        assert hashlib.sha256(previous_bytes).hexdigest() == evidence['previous_case_sha256'], 'preceding case changed'
        previous = json.loads(previous_bytes)
        assert previous['game'] == 'FrenchRoulette' and previous['status'] == 'verified' and previous['wallet_check'] == 'match', 'preceding case unverified'
        assert previous['session_group'] == case['session_group'], 'preceding case belongs to another original session'
        prior_md = previous['steps'][-1]['response']['md']
        before = _int(previous['balance_after_native'], 'preceding balance')
        assert _int(md['pbb'], 'native prior balance') == before, 'native preceding balance differs'
        sid = _int(md['sid'], 'native recovered sid', True)
        prior_sid = _int(prior_md['sid'], 'native preceding sid', True)
        assert sid != prior_sid, 'native last spin did not advance'
        assert isinstance(md['tid'], str) and md['tid'] and md['tid'] != prior_md['tid'], 'native transaction did not advance'
        win = _int(md['tw'], 'native win')
        after = _int(md['obb'], 'native closing balance')
        assert after == _int(response['bl'], 'native initialization balance') == before-cost+win, 'native wallet reconciliation failed'
        for key, value in (('balance_before_native', before), ('cost_native', cost), ('win_native', win), ('balance_after_native', after)):
            assert _int(case[key], key) == value, f'recovery summary differs: {key}'
        assert _int(case['internal_steps'], 'internal steps') == 1 and case['wallet_check'] == 'match', 'recovery summary not reconciled'
        result.update(passed=True, native_steps=0)
    except Exception as error:
        result['error'] = str(error)
    return result
