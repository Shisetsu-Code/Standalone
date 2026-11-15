"""Conservative native rules; undocumented feature selectors stop for review."""
from decimal import Decimal
import re

def latest(items,code):
    return next((args for c,args in reversed(items) if c==code),None)

def object_text(source,start):
    depth=0;quote=None;escaped=False
    for index in range(start,len(source)):
        char=source[index]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
            continue
        if char in ('"',"'",'`'):quote=char
        elif char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth==0:return source[start:index+1]
    raise ValueError('inherited_object_not_closed')

def inherited_default_profile(source,configuration):
    if not configuration or configuration.get('creditDisplay')!=0:raise ValueError('inherited_bet_lock_not_verified')
    maps=list(re.finditer(r'objects:Object.assign\(Object.assign\(\{\},([\w$]+)\.objects\),\{',source))
    if not maps:raise ValueError('inherited_game_map_missing')
    game_map=maps[-1];parent=game_map[1];overrides=object_text(source,game_map.end()-1)
    override_bet=re.search(r'\bbet:([\w$]+)(?=[,}])',overrides)
    if len(re.findall(r'\bbet:',overrides))>1:raise ValueError('inherited_game_bet_overrides_ambiguous')
    if re.search(r'\bbet:',overrides) and not override_bet:raise ValueError('inherited_game_overrides_bet')
    registry=re.search(r'(?<![\w.$])'+re.escape(parent)+r'=\{objects:Object.assign\(Object.assign\(\{\},[\w$]+\.objects\),\{',source)
    if not registry:raise ValueError('inherited_parent_registry_missing')
    parent_map=object_text(source,registry.end()-1);binding=re.search(r'\bbet:([\w$]+)(?=[,}])',parent_map)
    if not binding:raise ValueError('inherited_bet_binding_missing')
    descriptor=re.search(r'(?<![\w.$])'+re.escape(binding[1])+r'=\{label:"VideoSlotBet",components:\[([\w$]+),',source)
    if not descriptor:raise ValueError('inherited_bet_component_missing')
    effective_lines=None
    if override_bet:
        merged=re.search(r'(?<![\w.$])'+re.escape(override_bet[1])+r'=[\w$]+\.merge\('+re.escape(binding[1])+r',\{components:\[\{component:'+re.escape(descriptor[1])+r',params:\{betMaxLines:(\d+)\}\}\]\}\)',source[:game_map.start()])
        if not merged:raise ValueError('inherited_game_overrides_bet')
        effective_lines=int(merged[1])
    definition=re.search(r'(?<![\w.$])'+re.escape(descriptor[1])+r'=\(\(\)=>\{',source)
    if not definition:raise ValueError('inherited_settings_definition_missing')
    body=object_text(source,definition.end()-1)
    defaults=re.search(r'get defaultParams\(\)\{return Object.assign\(Object.assign\(\{\},super.defaultParams\),\{betMaxCoins:(\d+),betMaxLines:(\d+)\}\)\}',body)
    if not defaults:raise ValueError('inherited_defaults_missing')
    game_configs=list(re.finditer(r'buildGame\(new ([\w$]+)\(',source[:game_map.start()]))
    if not game_configs:raise ValueError('inherited_game_config_missing')
    config=re.search(r'(?<![\w.$])'+re.escape(game_configs[-1][1])+r'=\(\(\)=>\{',source)
    if not config:
        config=re.search(r'class '+re.escape(game_configs[-1][1])+r' extends [\w$]+\{',source)
    if not config:raise ValueError('inherited_game_config_definition_missing')
    config_body=object_text(source,config.end()-1)
    line_lock=re.search(r'get lock\(\)\{return super.lock\|([\w$]+)\.LINE\}',config_body)
    reviewed_config=config_body.replace(line_lock[0],'') if line_lock else config_body
    if any(term in reviewed_config for term in ('get lock()','get betMode()','get creditDisplay()','_betMode')):raise ValueError('inherited_custom_lock_requires_review')
    superclass=re.search(r'class(?: [\w$]+)? extends ([\w$]+)',source[config.start():config.end()]+config_body)
    if not superclass:raise ValueError('inherited_config_superclass_missing')
    parent_class=superclass[1]
    local=re.search(r'(?:^|[,;])'+re.escape(parent_class)+r'=([\w$]+)(?=[,;])',config_body)
    if local:parent_class=local[1]
    declaration=re.search(r'class '+re.escape(parent_class)+r'(?: extends [\w$]+)?\{',source)
    if not declaration:raise ValueError('inherited_config_parent_definition_missing')
    parent_body=object_text(source,declaration.end()-1)
    dynamic=re.search(r'get lock\(\)\{const\{betMode:(\w+)\}=this;return \1===([\w$]+)\.FIXED\?([\w$]+)\.LINE\|\3\.COIN\|\3\.FIXED_BET:\1===\2\.NO_COINS\?\3\.NO_COINS_DISPLAY:\3\.NONE\}',parent_body)
    credit=re.search(r'(?:const|var) (\w+)=[\w$.]+\.parseInt\(t\.creditDisplay,0\);return',parent_body)
    if not dynamic or not credit:raise ValueError('inherited_parent_dynamic_lock_not_verified')
    mode=re.escape(dynamic[2]);value=re.escape(credit[1])
    transition=r'this\._betMode='+mode+r'\.NORMAL,'+value+r'===([\w$]+)\.COINS_FIXED\|\|'+value+r'===\1\.CREDITS_FIXED\?this\._betMode='+mode+r'\.FIXED:'+value+r'===\1\.NO_COINS&&\(this\._betMode='+mode+r'\.NO_COINS\)'
    if not re.search(transition,parent_body) or not all(token in source for token in ('COINS_FIXED=2','CREDITS_FIXED=3','NO_COINS=4')):raise ValueError('inherited_credit_zero_to_none_not_verified')
    max_lines=effective_lines or int(defaults[2])
    if line_lock:
        if line_lock[1]!=dynamic[3] or 'this._lines=this._maxLines' not in body:raise ValueError('inherited_line_lock_not_verified')
        if configuration.get('lines') not in (0,max_lines):raise ValueError('inherited_public_lines_mismatch')
    elif configuration.get('lines')!=max_lines:raise ValueError('inherited_public_lines_mismatch')
    for prop,locked,maximum in [('lines','isLinesLocked','maxLines'),('coins','isCoinLocked','maxCoins')]:
        pattern=r'set '+prop+r'\((\w+)\)\{if\(this\.'+locked+r'\|\|\1>this\.'+maximum+r'\|\|\1<1\)return'
        if not re.search(pattern,body):raise ValueError('inherited_minimum_setter_not_verified:'+prop)
    return {'lines':max_lines if line_lock else 1,'coins':1,'source_excerpt':parent+'.objects.bet='+binding[1]+'; '+descriptor[1]+'.'+defaults.group(0)+'; effective lines '+str(max_lines)+'; '+(line_lock[0] if line_lock else 'unlocked minimum 1x1')}

def profile(source,initial,settings,configuration=None):
    denoms=latest(initial,54)
    if not denoms:raise ValueError('native_denominations_missing')
    count=int(denoms[0]);values=[int(v) for v in denoms[1:1+count]]
    xml=re.findall(r'<denom\s+Value="([\d.]+)"',settings)
    if not xml:
        xml=re.findall(r'<Denominations>([\d.,]+)</Denominations>',settings)
        xml=xml[0].split(',') if xml else []
    if len(xml)!=count or not values or min(values)<=0:raise ValueError('denomination_pairing_not_verified')
    scales={Decimal(v)/Decimal(d) for v,d in zip(values,xml)}
    if len(scales)!=1 or next(iter(scales))!=next(iter(scales)).to_integral_value():raise ValueError('currency_scale_not_verified')
    # These literals are emitted by the game-specific entry point, after SDK defaults.
    pairs=list(re.finditer(r'betMaxLines:(?P<lines>[\w$.]+),betMaxCoins:(?P<coins>[\w$.]+)|betMaxCoins:(?P<reverse_coins>[\w$.]+),betMaxLines:(?P<reverse_lines>[\w$.]+)',source))
    pairs=[m for m in pairs if 'super.defaultParams' not in source[max(0,m.start()-90):m.start()]]
    legacy=list(re.finditer(r'createBetSettings\(\w*\)\{[^{}]{0,150}?(?:return (?:[\w$]+=[\w$.|]+,)?|(?:var|let|const) [\w$]+=)new [\w$]+\((?P<legacy_lines>[\w$.]+),(?P<legacy_coins>[\w$.]+),[^)]*\)',source))
    legacy+=list(re.finditer(r'createBetSettings\(\w*\)\{return (?P<registry>[\w.$]+)\.register\((?P<bet_class>[\w$]+),\{useValue:new (?P=bet_class)\((?P<legacy_lines>[\w$.]+),(?P<legacy_coins>[\w$.]+),[^)]*\)\}\),(?P=registry)\.resolve\((?P=bet_class)\)\}',source))
    legacy+=list(re.finditer(r'createBetSettings\(\w*\)\{return new [\w$]+\((?P<legacy_lines>\d+),(?P<legacy_coins>this\._config\.creditDisplay===[\w$]+\.NO_COINS\?\d+:\d+),this\._config\.betMaxMode,\w+\)\}',source))
    legacy.sort(key=lambda match:match.start())
    legacy_match=legacy[-1] if legacy else None
    definitions=list(re.finditer(r'createBetSettings\([^)]*\)\{',source))
    if not pairs and definitions and (not legacy_match or legacy_match.start()!=definitions[-1].start()):raise ValueError('final_legacy_bet_override_not_resolved')
    if not pairs and not legacy_match:
        inherited=inherited_default_profile(source,configuration);denomination=min(values)
        return dict(inherited,denomination=denomination,cost_native=inherited['lines']*inherited['coins']*denomination,scale=int(next(iter(scales))),denominations_native=values,denominations_display=xml)
    match=pairs[-1] if pairs else legacy_match
    bound=bool(re.search(r'objects\.bet,\{components:\[\{component:[\w.$]+,params:\{$',source[max(0,match.start()-100):match.start()]))
    bound=bound or bool(re.search(r'bet:[\w.$]+\.merge\([\w$]+,\{components:\[\{component:[\w.$]+,params:\{$',source[max(0,match.start()-160):match.start()]))
    # Some games name their composed bet component and bind that alias in the final object map.
    if not bound and pairs:
        for binding in re.finditer(r'\bbet:([\w$]+)(?=[,}])',source):
            alias=binding[1]
            for assignment in re.finditer(r'(?<![\w.$])'+re.escape(alias)+r'=[\w.$]+\.merge\(',source[:binding.start()]):
                segment=source[assignment.start():match.start()]
                if 0<len(segment)<300 and 'components:[{component:' in segment and 'params:{' in segment:bound=True
    if not bound and not (not pairs and legacy_match):raise ValueError('bet_profile_not_bound_to_game')
    locks=re.findall(r'get lock\(\)\{return ([\w.|]+)\}',source)
    fixed=any({'LINE','COIN','FIXED_BET'}.issubset({v.rsplit('.',1)[-1] for v in lock.split('|')}) for lock in locks)
    fixed=fixed or bool(re.search(r'get betMode\(\)\{return [\w$.]+\.FIXED\}',source))
    if not pairs and legacy_match:fixed=all('.'+flag in legacy_match.group(0) for flag in ('LINE','COIN','FIXED_BET'))
    if configuration and configuration.get('creditDisplay') in (2,3):fixed=True
    def constant(value):
        if value.isdigit():return int(value)
        inline=re.fullmatch(r'this\._config\.creditDisplay===([\w$]+)\.NO_COINS\?(\d+):(\d+)',value)
        if inline:
            if not configuration or configuration.get('creditDisplay') not in (0,2,3,4) or not re.search(r'NO_COINS=4\]="NO_COINS"\}\('+re.escape(inline[1])+r'\|\|\('+re.escape(inline[1])+r'=\{\}\)\)',source):raise ValueError('inline_credit_enum_not_verified')
            return int(inline[2] if configuration['creditDisplay']==4 else inline[3])
        if not pairs and legacy_match and configuration and configuration.get('creditDisplay') in (0,2,3,4):
            local=object_text(source,legacy_match.start()+legacy_match[0].index('{'))
            conditional=re.fullmatch(r'\{(?:var|let|const) '+re.escape(value)+r'=this\._config\.creditDisplay!==([\w$]+)\.NO_COINS\?(\d+):(\d+);return new [\w$]+\(\d+,'+re.escape(value)+r',this\._config\.betMaxMode,\w+\)\}',local)
            if not conditional and re.search(r'(?:var|let|const) '+re.escape(value)+r'=',local):raise ValueError('local_bet_constant_not_proven')
            if conditional:
                enum=re.escape(conditional[1])
                if not re.search(r'NO_COINS=4\]="NO_COINS"\}\('+enum+r'\|\|\('+enum+r'=\{\}\)\)',source):raise ValueError('local_credit_enum_not_verified')
                return int(conditional[3] if configuration['creditDisplay']==4 else conditional[2])
        if '.' in value:
            owner,prop=value.rsplit('.',1)
            assignments=re.findall(r'(?<![\w.$])'+re.escape(value)+r'=(\d+)(?=[,;}])',source)
            if len(set(assignments))==1:return int(assignments[0])
            hits=re.findall(r'(?:static )?get '+re.escape(prop)+r'\(\)\{return (\d+)\}',source)
            if len(set(hits))==1:return int(hits[0])
            raise ValueError('bet_static_constant_ambiguous:'+value)
        hits=re.findall(r'(?<![\w.$])'+re.escape(value)+r'=(\d+)(?=[,;}])',source)
        if len(set(hits))!=1:raise ValueError('bet_constant_ambiguous:'+value)
        return int(hits[0])
    pair_values=(match['lines'] or match['reverse_lines'],match['coins'] or match['reverse_coins']) if pairs else (match['legacy_lines'],match['legacy_coins'])
    partial_proof=''
    if pairs:
        for partial in re.finditer(r'(?<![\w.$])([\w$]+)=[\w.$]+\.merge\(([\w$]+),\{components:\[\{component:[\w.$]+,params:\{betMaxCoins:([\w$.]+)\}\}\]',source[match.end():]):
            alias,base,coins_value=partial.groups()
            if not re.search(r'\bbet:'+re.escape(alias)+r'(?=[,}])',source[match.end()+partial.end():]):continue
            bases=list(re.finditer(r'(?<![\w.$])'+re.escape(base)+r'=[\w.$]+\.merge\(',source[:match.start()]))
            if not bases or match.start()-bases[-1].start()>300:continue
            pair_values=(pair_values[0],coins_value);partial_proof=partial.group(0)
    lines,coins=map(constant,pair_values);denomination=min(values)
    if not fixed:
        default_max=configuration and configuration.get('lines')==0 and 'this._lines=this._maxLines' in source
        if configuration and configuration.get('creditDisplay')==0 and (configuration.get('lines')==lines or default_max):
            coins=1 # SDK initializes unlocked coins to one; preserve published default lines.
        else:raise ValueError('fixed_bet_semantics_not_verified')
    if coins<=0 or lines<=0:raise ValueError('invalid_fixed_bet')
    return {'lines':lines,'coins':coins,'denomination':denomination,'cost_native':coins*lines*denomination,'scale':int(next(iter(scales))),'denominations_native':values,'denominations_display':xml,'source_excerpt':match.group(0)+('; '+partial_proof if partial_proof else '')}

def modes(source,initial):
    setup=latest(initial,60)
    bound=bool(re.search(r'betBooster:[A-Za-z_$][\w.$]*[,}]',source))
    factors=set(re.findall(r'[{,]betBoostFactor:(\d+(?:\.\d+)?)(?=[,}])',source))
    has_serialization=bool(re.search(r'\.lines\*this\._betBooster\.currentBetBoostFactor',source))
    enabled=bool(setup and len(setup)>3 and setup[3]=='0')
    return {'go_ultra':bound and has_serialization and enabled and len(factors)==1,
            'booster_bound':bound,'native_booster_enabled':enabled,'factors':sorted(factors),
            'inventory_status':'reviewed_booster_only','other_controls_status':'needs_review'}

def continuation(items,processed_free):
    errors=[args for code,args in items if code in (110,111)]
    if errors:raise ValueError('native_error:'+str(errors))
    wallet=latest(items,52)
    if wallet and len(wallet)>1 and wallet[1]=='0':return None
    # FEATURE_COLLECT is an explicit prompt; never guess FEATURE_SELECT arguments.
    if any(code==2 and args[:2]==['5','1'] for code,args in items):return '2 6'
    end=latest(items,3)
    if end and len(end)>=4:
        if int(end[3])>0 or processed_free:return '7 '+str(processed_free)
        if int(end[2])>0 or end[0]=='1':return '4 0'
    raise ValueError('unrecognized_native_continuation')
