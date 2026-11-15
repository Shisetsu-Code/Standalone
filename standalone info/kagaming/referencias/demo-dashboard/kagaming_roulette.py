"""Source-bound French Roulette plans. Pure local planning; never sends requests."""
import hashlib
import heapq
import math
import re
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path


class RouletteBlocked(ValueError):
    """Required native evidence is absent or outside the reviewed contract."""


GROUPS = {37: [156, 58, 26, 80], 38: [1, 52, 62, 65, 81],
          39: [104, 54, 58, 64, 69, 99, 80],
          40: [53, 137, 63, 144, 73, 79]}


def _integer(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < (1 if positive else 0):
        raise RouletteBlocked(f'{name} must be a native nonnegative integer')
    return int(value)


def _limit_classes(source):
    match = re.search(r'GLa:function\(a\)\{var b=-1;(.+?)return this\.jQa\.jtd\(b\)', source, re.S)
    if not match:
        raise RouletteBlocked('FrenchRoulette source GLa limit mapping missing')
    clauses = []
    for part in match.group(1).replace('\n', '').replace('\r', '').rstrip(';').split(':'):
        found = re.fullmatch(r'(.+?)\?b=(\d+)', part) or re.fullmatch(r'(.+)&&\(b=(\d+)\)', part)
        if not found or not re.fullmatch(r'[0-9a<>=&|()]+', found[1]):
            raise RouletteBlocked('Unreviewed source limit expression')
        clauses.append((found[1], int(found[2])))
    result = []
    for index in range(157):
        selected = next((cls for condition, cls in clauses
                         if eval(condition.replace('a', str(index)).replace('&&', ' and ').replace('||', ' or '), {'__builtins__': {}})), None)
        if selected is None:
            raise RouletteBlocked(f'No source limit class for field {index}')
        result.append(selected)
    return result


def _minimum_sum(chips, minimum):
    """Exact unbounded chip sum using shortest reachable value per residue."""
    modulus = min(chips)
    if modulus > 100000:
        raise RouletteBlocked('Chip residue space exceeds reviewed planner limit')
    distances = [math.inf] * modulus
    distances[0] = 0
    pending = [(0, 0)]
    while pending:
        distance, residue = heapq.heappop(pending)
        if distance != distances[residue]:
            continue
        for chip in chips:
            candidate = distance + chip
            target = candidate % modulus
            if candidate < distances[target]:
                distances[target] = candidate
                heapq.heappush(pending, (candidate, target))
    return min(int(d) + max(0, (minimum-int(d)+modulus-1)//modulus)*modulus
               for d in distances if math.isfinite(d))


def native_cost(position, dn):
    """Native J.gc conversion, in wallet cents (reviewed denomination .01)."""
    if Decimal(str(dn)) != Decimal('.01'):
        raise RouletteBlocked('Only dn=0.01 has a reviewed wallet-unit contract')
    amount = sum(Decimal(str(x)) for x in position) * Decimal(str(dn)) * 100
    return int((amount + Decimal('0.00000011920929')).to_integral_value(rounding=ROUND_FLOOR))


def plans(init, source):
    try:
        chips = [_integer(x, 'cup chip', True) for x in init['cup']]
        dn = init['cud']
        md = init['sgr']['lsd']
        limits = [_integer(x, 'sm limit') for x in md['sm']]
        cps = _integer(md['cps'], 'initialized cps', True)
        atb = _integer(md['atb'], 'initialized atb')
    except (KeyError, TypeError) as error:
        raise RouletteBlocked(f'Missing native roulette initialization field: {error}') from error
    if not chips or len(limits) != 13 or limits[0] <= 0 or limits[1] < limits[0]:
        raise RouletteBlocked('Native cup and 13-entry sm table limits required')
    native_cost([1], dn)
    classes = _limit_classes(source)
    common = (Path(__file__).parent / 'kagaming/reference/game.min.2090.js').read_text(encoding='utf8')
    for marker in ['a.sel=this.xl', 'a.cps=this.kj', 'a.pos.push(this.ti[b])', 'Math.floor(a*b*100+1.1920929E-7)']:
        if marker not in common:
            raise RouletteBlocked('Native serialization/conversion source changed')
    original_cps = cps
    if cps not in chips:
        compact = re.sub(r'\s+', '', common)
        proof = [
            'Hd.Tg=function(){returnv.nb()?v.toa:uc.We()?uc.lfa():[]}',
            'Uc:function(a,b,d,e){a=0;if(0<e.length)for(varfine)a+=e[f];returna}',
            'this.Yha(a);b=A.zb().Vb(this.la).Mf();this.Cu(a.xl,b[this.zv],a.pC(),a.Zu(),!1,a.Lta)',
            'if(0>e)if(e=0,v.nb())for(varn=0;n<d.length;n++){varp=b.Uc(a.xl,d[n],a.pC(),a.Zu())*v.$p;0===n&&(h=p,e=n);if(1.1920929E-7>=Math.abs(p-k)){e=n;g=!0;break}varw=Math.abs(k-h),y=Math.abs(k-p);y<w&&(h=p,e=n)}',
        ]
        if init.get('mm') in (1, 2) or not all(marker in compact for marker in proof):
            raise RouletteBlocked('Initialized cps outside cup and cash-mode normalization proof unavailable')
        # Roulette Uc ignores cps, so every candidate p is identical. Yha sets
        # e=0 first; strict y<w cannot choose a later chip when distances tie.
        cps = chips[0]
    minimum = _minimum_sum(chips, limits[0])
    result = []
    source_digest = hashlib.sha256(source.encode('utf8')).hexdigest()
    serialization_digest = hashlib.sha256(common.encode('utf8')).hexdigest()

    def add(indices, key, label, field=None):
        if minimum*len(indices) > limits[1] or any(minimum > limits[2+classes[i]] for i in indices):
            return
        position = [0]*157
        for i in indices:
            position[i] += minimum
        result.append(dict(sel=sum(x > 0 for x in position), cps=cps, dn=dn,
                           atb=atb, cost_native=native_cost(position, dn),
                           cost_formula='floor(sum(pos)*dn*100+1.1920929E-7)',
                           source_sha256=source_digest,
                           serialization_source_sha256=serialization_digest,
                           kind='normal' if key == 'normal' else 'variant', key=key,
                           position=position, label=label, field_index=field))
        if original_cps != cps:
            result[-1]['initialized_cps'] = original_cps
            result[-1]['cps_normalization'] = 'native Yha first cash chip: roulette Uc independent of cps'

    for field in range(157):
        add([field], 'normal' if not result else f'roulette-{field}', f'Roulette field {field}', field)
    for group, indices in GROUPS.items():
        add(indices, f'racetrack-{group}', f'Racetrack group {group}')
    if not result:
        raise RouletteBlocked('No source-admissible minimum wager within field and table caps')
    return result


def validate_response(md, profile):
    position = profile['position']
    assert isinstance(position, list) and len(position) == 157, 'roulette wager board dimensions'
    assert all(type(x) is int and x >= 0 for x in position), 'roulette invalid field stake'
    # Native I8 counts occupied request fields; the accepted native response
    # reports the fixed board size in md.sel, matching FrenchRoulette FIb:157.
    assert profile['sel'] == sum(x > 0 for x in position), 'roulette request selection count'
    assert profile['sel'] > 0, 'roulette empty wager'
    if 'sel' in md:
        assert type(md['sel']) is int and md['sel'] == 157, 'roulette response board dimensions'
    if 'st' in md:
        assert isinstance(md['st'], list) and len(md['st']) == 1, 'roulette ball shape'
        ball = md['st'][0]
        assert type(ball) is int and 0 <= ball <= 36, 'roulette ball outside 0..36'
    if 'pos' in md:
        assert md['pos'] == position, 'roulette stake echo mismatch'


def assert_closed(md):
    assert not md.get('fs') and not md.get('fsr') and not md.get('rf') and not md.get('bpd'), 'roulette round pending'
