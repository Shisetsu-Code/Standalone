"""Pure source-pinned American Roulette boards, caps and native response checks."""
import hashlib
import re
from pathlib import Path

from kagaming_roulette import RouletteBlocked, _integer, _minimum_sum, native_cost

SOURCE_SHA256='39ca616cfb8f0081866ba7a232964646b4e331cbc95304017ac20db20707c978'
COMMON_SHA256='6cf1bdace2d5fb0a889364ad05fa3a3a31ed2fc37aa79b36be4ee71a6e49a0f2'
BOARD_SIZE=158


def _source(source):
    if isinstance(source,bytes):source=source.decode('utf8')
    if not isinstance(source,str) or hashlib.sha256(source.encode('utf8')).hexdigest()!=SOURCE_SHA256:
        raise RouletteBlocked('AmericanRoulette source changed')
    return source


def neighbor_groups(source):
    """Parse all 38 native wTb clauses, preserving exact source order."""
    source=_source(source)
    match=re.search(r'wTb:function\(a\)\{return (.*?)\},LWb:',source,re.S)
    if not match:raise RouletteBlocked('AmericanRoulette neighbor source missing')
    expression=re.sub(r'\s+','',match[1])
    clauses=re.findall(r'(\d+)==a\?\[([0-9,]+)\]:',expression)
    reconstructed=''.join(key+'==a?['+values+']:' for key,values in clauses)+'[]'
    if reconstructed!=expression or [int(key) for key,_ in clauses]!=list(range(38)):
        raise RouletteBlocked('AmericanRoulette neighbor clauses changed')
    result={int(key):[int(value) for value in values.split(',')] for key,values in clauses}
    if any(len(values)!=5 or len(set(values))!=5 or any(value not in list(range(37))+[157] for value in values)
           for values in result.values()):
        raise RouletteBlocked('AmericanRoulette neighbor fields changed')
    return result


def _limit_classes(source):
    match=re.search(r'GLa:function\(a\)\{var b=-1;(.+?)return this\.jQa\.jtd\(b\)',source,re.S)
    if not match:raise RouletteBlocked('AmericanRoulette limit mapping missing')
    clauses=[]
    for part in re.sub(r'\s+','',match[1]).rstrip(';').split(':'):
        found=re.fullmatch(r'(.+?)\?b=(\d+)',part) or re.fullmatch(r'(.+)&&\(b=(\d+)\)',part)
        if not found or not re.fullmatch(r'[0-9a<>=&|()]+',found[1]) or not 0<=int(found[2])<=10:
            raise RouletteBlocked('AmericanRoulette limit expression changed')
        clauses.append((found[1],int(found[2])))
    result=[]
    for field in range(BOARD_SIZE):
        selected=next((kind for expression,kind in clauses if eval(
            expression.replace('a',str(field)).replace('&&',' and ').replace('||',' or '),
            {'__builtins__':{}})),None)
        if selected is None:raise RouletteBlocked('AmericanRoulette field has no cap class')
        result.append(selected)
    return result


def plans(init,source):
    source=_source(source)
    common=(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes()
    if hashlib.sha256(common).hexdigest()!=COMMON_SHA256:
        raise RouletteBlocked('AmericanRoulette serialization source changed')
    try:
        chips=[_integer(value,'chip',True) for value in init['cup']]
        dn=init['cud'];md=init['sgr']['lsd']
        limits=[_integer(value,'table limit') for value in md['sm']]
        cps=_integer(md['cps'],'initialized cps',True)
        atb=_integer(md['atb'],'initialized atb')
    except (KeyError,TypeError) as error:
        raise RouletteBlocked('Missing AmericanRoulette native initialization') from error
    if not chips or len(limits)!=13 or limits[0]<=0 or limits[1]<limits[0]:
        raise RouletteBlocked('AmericanRoulette chips and 13 table limits required')
    native_cost([1],dn)
    original_cps=cps
    if cps not in chips:
        if init.get('mm') in (1,2):
            raise RouletteBlocked('AmericanRoulette chip normalization only reviewed in cash mode')
        # Pinned common Yha initializes e=0; roulette Uc ignores cps, so
        # every candidate distance ties and the native first chip remains.
        cps=chips[0]
    classes=_limit_classes(source);groups=neighbor_groups(source);result=[]

    def add(indices,key,label,field=None):
        # LWb adds the same chip to every neighbor field. Repeated chip
        # placements give equal reachable sums; the table minimum is total.
        threshold=(limits[0]+len(indices)-1)//len(indices)
        amount=_minimum_sum(chips,threshold)
        if amount*len(indices)>limits[1] or any(amount>limits[2+classes[index]] for index in indices):
            return
        position=[0]*BOARD_SIZE
        for index in indices:position[index]=amount
        profile=dict(game_id='AmericanRoulette',sel=len(indices),cps=cps,dn=dn,atb=atb,
                     position=position,cost_native=native_cost(position,dn),
                     cost_formula='floor(sum(pos)*dn*100+1.1920929E-7)',
                     source_sha256=SOURCE_SHA256,serialization_source_sha256=COMMON_SHA256,
                     kind='normal' if key=='normal' else 'variant',key=key,label=label,
                     field_index=field,limits_native=limits[:],chips_native=chips[:],
                     limit_classes=classes[:])
        if original_cps!=cps:
            profile.update(initialized_cps=original_cps,
                           cps_normalization='native Yha first cash chip: roulette Uc independent of cps')
        validate_position(profile);result.append(profile)

    for field in range(BOARD_SIZE):
        add([field],'normal' if not result else 'roulette-'+str(field),
            'American Roulette field '+str(field),field)
    for group,indices in groups.items():
        add(indices,'neighbors-'+str(group),'American Roulette neighbors '+str(group))
    if not result:raise RouletteBlocked('No AmericanRoulette minimum wager within native caps')
    if not any(profile['kind']=='normal' for profile in result):
        # If only groups are admissible, retain one normal entry as French
        # does for the first admissible board; all boards remain explicit.
        result[0]['kind']='normal';result[0]['key']='normal'
    return result


def validate_position(profile,request=None):
    """Validate occupied request count, exact chip reachability, caps and price."""
    if (profile.get('game_id')!='AmericanRoulette' or profile.get('source_sha256')!=SOURCE_SHA256
            or profile.get('serialization_source_sha256')!=COMMON_SHA256):
        raise RouletteBlocked('Unbound AmericanRoulette profile')
    position=profile.get('position')
    if not isinstance(position,list) or len(position)!=BOARD_SIZE or any(type(v) is not int or v<0 for v in position):
        raise RouletteBlocked('AmericanRoulette wager board dimensions or values')
    if type(profile.get('sel')) is not int or profile['sel']!=sum(value>0 for value in position) or not profile['sel']:
        raise RouletteBlocked('AmericanRoulette occupied field count')
    limits=profile.get('limits_native');classes=profile.get('limit_classes');chips=profile.get('chips_native')
    if not isinstance(limits,list) or len(limits)!=13 or not isinstance(classes,list) or len(classes)!=BOARD_SIZE or not chips:
        raise RouletteBlocked('AmericanRoulette profile limits missing')
    if not limits[0]<=sum(position)<=limits[1]:raise RouletteBlocked('AmericanRoulette table cap')
    for field,value in enumerate(position):
        if value and (value>limits[2+classes[field]] or _minimum_sum(chips,value)!=value):
            raise RouletteBlocked('AmericanRoulette field cap or unreachable chip sum')
    if type(profile.get('cost_native')) is not int or profile['cost_native']!=native_cost(position,profile['dn']):
        raise RouletteBlocked('AmericanRoulette source cost mismatch')
    if request is not None:
        if request.get('gn')!='AmericanRoulette' or request.get('pos')!=position:
            raise RouletteBlocked('AmericanRoulette request board mismatch')
        for key in ('sel','cps','dn','atb'):
            if isinstance(request.get(key),bool) or request.get(key)!=profile[key]:
                raise RouletteBlocked('AmericanRoulette request stake mismatch')


def validate_response(md,profile):
    validate_position(profile)
    if not isinstance(md,dict) or md.get('v') is not True:
        raise RouletteBlocked('AmericanRoulette invalid native result')
    if type(md.get('sel')) is not int or md['sel']!=BOARD_SIZE:
        raise RouletteBlocked('AmericanRoulette native response board requires confirmation')
    ball=md.get('st')
    if not isinstance(ball,list) or len(ball)!=1 or type(ball[0]) is not int or not (0<=ball[0]<=36 or ball[0]==157):
        raise RouletteBlocked('AmericanRoulette ball outside native wheel')
    position=md.get('pos')
    if not isinstance(position,list) or len(position)!=BOARD_SIZE or any(type(value) is not int or value<0 for value in position) or position!=profile['position']:
        raise RouletteBlocked('AmericanRoulette native stake board mismatch')
    for key in ('cps','dn','atb'):
        if isinstance(md.get(key),bool) or md.get(key)!=profile[key]:
            raise RouletteBlocked('AmericanRoulette native stake echo mismatch')
    if 'gn' in md and md['gn']!='AmericanRoulette':raise RouletteBlocked('AmericanRoulette native game mismatch')


def assert_closed(md):
    if not isinstance(md,dict) or md.get('v') is not True or any(md.get(key) for key in ('fs','fsr','rf','bpd','fsd')):
        raise RouletteBlocked('AmericanRoulette round pending or invalid')
