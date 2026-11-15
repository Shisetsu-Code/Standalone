"""Source-bound FortuneSkyLanterns paid choices; no continuation guessing."""
import hashlib
from decimal import Decimal, InvalidOperation
import re


_HOOKS = (
    'A.zb().Ig("FortuneSkyLanterns",this)',
    'Uc:function(a,b){return10*b}',
    'Cb.ZV(this.la,this.ti,1,this.kj,this.fo,v.$p,function(a){e.kY(a)})',
    'tRa:function(){returnthis.RJ?[this.RJ.I3(),this.RJ.nc()]:[]}',
    'I3:function(){returnthis.dk+1}',
    'hDd=[128,64,32,16,8,4,2,1.5,1.1,0]',
    'gta:6E6,fta:3E6',
)
_LABELS = ('128x', '64x', '32x', '16x', '8x', '4x', '2x', '1.5x', '1.1x', 'Special')


def _number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid_lantern_native_number') from exc
    if isinstance(value, bool) or not result.is_finite():
        raise ValueError('invalid_lantern_native_number')
    return result


def _integers(values):
    if not isinstance(values, list) or not values:
        raise ValueError('missing_lantern_native_values')
    result = [_number(value) for value in values]
    if any(value < 0 or value != value.to_integral_value() for value in result):
        raise ValueError('invalid_lantern_native_integer')
    return [int(value) for value in result]


def plans(init, source):
    """Return ten minimum-cost paid profiles using client-owned scene tags.

    Pass bytes read from disk, or those same bytes decoded as UTF-8, so the
    source digest preserves the original line endings.
    """
    raw = source.encode('utf8') if isinstance(source, str) else source
    if not isinstance(raw, bytes):
        raise ValueError('invalid_lantern_source')
    compact = re.sub(r'\s+', '', raw.decode('utf8'))
    if any(hook not in compact for hook in _HOOKS):
        raise ValueError('unreviewed_lantern_source_contract')
    if 1 not in _integers(init.get('ase')):
        raise ValueError('lantern_selection_one_unavailable')
    positive = [value for value in _integers(init.get('cup')) if value > 0]
    if not positive:
        raise ValueError('no_positive_lantern_cps')
    denominations = init.get('dn')
    if not isinstance(denominations, list) or not denominations:
        raise ValueError('missing_lantern_denomination')
    denominations = [_number(value) for value in denominations]
    if any(value <= 0 for value in denominations):
        raise ValueError('invalid_lantern_denomination')
    cps, dn = min(positive), min(denominations)
    cost = Decimal(100) * 10 * cps * dn
    if cost <= 0 or cost != cost.to_integral_value():
        raise ValueError('nonintegral_lantern_native_cost')
    base = dict(sel=1, cps=cps, dn=float(dn), atb=0, cost_native=int(cost),
                cost_formula='Uc(sel,cps) = 10*cps; native = 100*dn*10*cps',
                source_sha256=hashlib.sha256(raw).hexdigest())
    return [dict(base, key='normal' if number == 1 else f'lantern-{number}',
                 kind='normal' if number == 1 else 'variant',
                 position=[number, 3000000 + number], label=f'Lantern {number} · {label}')
            for number, label in enumerate(_LABELS, 1)]


def assert_closed(md):
    """Reject obligations absent from this game's reviewed controller."""
    if not isinstance(md, dict):
        raise ValueError('missing_lantern_result')
    remaining = _number(md.get('fsr', 0))
    if remaining != 0 or md.get('rf') or md.get('bpd'):
        raise ValueError('unreviewed_lantern_pending_state')


def validate_position(profile, request):
    """Require the exact reviewed type/tag pair, including integer types."""
    expected = profile.get('position')
    actual = request.get('pos')
    if (not isinstance(expected, list) or len(expected) != 2
            or any(type(value) is not int for value in expected)
            or not 1 <= expected[0] <= 10 or not 3000000 <= expected[1] < 6000000
            or not isinstance(actual, list) or len(actual) != 2
            or any(type(value) is not int for value in actual) or actual != expected):
        raise ValueError('lantern_position_mismatch')
