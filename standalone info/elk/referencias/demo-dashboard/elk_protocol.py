"""Validated public ELK stage-demo XML contracts."""
from decimal import Decimal
import hashlib
import re
import xml.etree.ElementTree as ET

D=lambda value:Decimal(str(value))

def validate_fresh_demo(init):
    if init.findtext('method')!='init' or init.findtext('errorcode')!='0':raise ValueError('invalid_native_init')
    if init.findtext('roundid')!='0' or D(init.findtext('gamesession/totbet'))!=0 or D(init.findtext('gamesession/totwon'))!=0:raise ValueError('not_a_fresh_demo')
    if init.findtext('player/currency')!='EUR' or D(init.findtext('player/balance'))<=0:raise ValueError('unexpected_demo_wallet')

def parse_xml(text):
    if isinstance(text,bytes):text=text.decode('utf8')
    if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):raise ValueError('unsupported_xml_declaration')
    root=ET.fromstring(text)
    error=root.findtext('errorcode')
    if error not in (None,'0'):raise ValueError('provider_error_code:'+error)
    return root

def round_id(value):
    if value in (None,'','0') or value.startswith('round-'):return value
    return 'round-'+hashlib.sha256(value.encode()).hexdigest()[:20]

def redact_xml(text):
    if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):return '[UNSUPPORTED XML]'
    root=ET.fromstring(text)
    def walk(node,parent=''):
        for key,value in list(node.attrib.items()):
            if re.sub('[^a-z]','',key.lower()) in {'session','sessionid','sessionkey','sessiontoken','extsession','gamesession','token','onetimetoken','clientseed','playerhash','authorization','authtoken','accesstoken'}:node.set(key,'[REDACTED]')
            elif key.lower()=='roundid':node.set(key,round_id(value))
        if node.tag.lower() in ('onetimetoken','playerhash') or (parent.lower()=='gamesession' and node.tag.lower()=='id'):node.text='[REDACTED]'
        elif node.tag.lower()=='roundid':node.text=round_id(node.text)
        elif node.text and node.text.lstrip().startswith('<'):node.text=redact_xml(node.text)
        for child in node:walk(child,node.tag)
    walk(root)
    return ET.tostring(root,encoding='unicode')

def mode_controls(init):
    levels=init.find('betlevels')
    if levels is None:raise ValueError('published_betlevels_missing')
    flag=init.find('gameprops/bmode')
    enabled=levels.get('bmode')=='true' and (flag is None or flag.get('enabled')=='true')
    found={}
    for level in levels.findall('betlevel'):
        level_id=level.get('id')
        if not re.fullmatch(r'[0-9]+',level_id or ''):raise ValueError('unrecognized_betlevel_id')
        modes=level.findall('bmodes/bmode')
        if not modes and level.get('amount'):modes=[ET.Element('bmode',id='DEF',amount=level.get('amount'))]
        for mode in modes:
            key=mode.get('id');amount=mode.get('amount')
            if key!='DEF' and not enabled:continue
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*',key or ''):raise ValueError('unrecognized_mode_id')
            if D(amount)<=0:continue
            candidate={'mode':key,'betlevel':level_id,'amount':amount}
            previous=found.get(key)
            if previous is None or (D(amount),int(level_id))<(D(previous['amount']),int(previous['betlevel'])):found[key]=candidate
    if 'DEF' not in found:raise ValueError('normal_minimum_missing')
    controls=[found['DEF']]+[found[k] for k in sorted(found) if k!='DEF']
    variants=init.findall('variants/variant')
    if not variants:return controls
    expanded=[]
    for variant in variants:
        key=variant.get('id')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',key or ''):raise ValueError('unrecognized_variant_id')
        table=parse_xml(variant.findtext('game/paytable'))
        prices={m.get('name'):D(m.get('price')) for m in table.findall('BMODES/BMODE')}
        for control in controls:
            if prices and control['mode'] not in prices:continue
            if prices and D(control['amount'])/D(found['DEF']['amount'])!=prices[control['mode']]/prices['DEF']:raise ValueError('variant_price_contract_mismatch')
            expanded.append(dict(control,variant=key))
    if not expanded:raise ValueError('variant_controls_missing')
    return expanded

def purchase_tree(reply):
    text=reply.findtext('game/pubdata')
    if not text:raise ValueError('native_purchase_data_missing')
    root=parse_xml(text)
    purchases=root.findall('PURCHASE')
    if root.tag!='PURCHASES' or len(purchases)!=1:raise ValueError('unverified_purchase_sequence')
    return purchases[0]

def results(reply):
    return [{'step':i,'mode':node.get('mode'),'attributes':dict(node.attrib),'xml':ET.tostring(node,encoding='unicode')} for i,node in enumerate(purchase_tree(reply).findall('RESULT'))]

def validate_result_closure(init,purchase,control):
    native=purchase_tree(purchase);nodes=native.findall('RESULT')
    if not nodes or any(child.tag!='RESULT' for child in native):raise ValueError('unrecognized_purchase_continuation')
    table=init.findtext('game/paytable')
    if control.get('variant'):
        table=next(v for v in init.findall('variants/variant') if v.get('id')==control['variant']).findtext('game/paytable')
    allowed={mode.get('name') for mode in parse_xml(table).findall('MODE')} if table else {'BASE','BONUS'}
    if table and not parse_xml(table).findall('MODE') and init.find('betlevels').get('bmode')=='false':
        configs=parse_xml(table).findall('CONFIG')
        if not configs:raise ValueError('unrecognized_classic_layout')
        ids=[config.get('id') for config in configs]
        if all(value is not None for value in ids):allowed=set(ids)
        elif all(value is None for value in ids):allowed={str(index) for index in range(len(configs))}
        else:raise ValueError('mixed_classic_config_identifiers')
        if parse_xml(table).tag=='MODES':
            for node in nodes:
                if node.get('mode') is None and node.get('freespin',node.get('freespins')) not in ('0','1'):raise ValueError('unrecognized_classic_spin_flag')
            allowed.add(None)
    if table and parse_xml(table).get('gameid')=='10053' and 'FREESPINS-AVALANCHE' in allowed:
        allowed|={'FREESPINS-'+name for name in list(allowed) if re.fullmatch(r'AVALANCHE-[4-8]',name)}
    if not allowed or any(node.get('mode') not in allowed for node in nodes):raise ValueError('unpublished_result_mode')
    last=nodes[-1]
    for key in ('freespin','freespins','fsleft'):
        if last.get(key) is not None and D(last.get(key))!=0:raise ValueError('classic_bonus_steps_remaining')
    for action in last.findall('ACTIONS'):
        if action.get('fscount') is not None and D(action.get('fscount'))!=0:raise ValueError('classic_bonus_actions_remaining')
    if last.get('amounttotal') is not None and D(last.get('amounttotal'))!=D(native.get('winamount')):raise ValueError('final_result_total_mismatch')
    known={'bonus-counter','freedrops','redrops','free-drops','free-spins','respins','freespins','subrounds','dropz','respins-base','respins-bonus','extra-drops','kitty-free-drops','drops','coin-game-counter','lives','sub-rounds','coin-chase-counter','','bonus-symbols','super-bonus-symbols','both-ways','life-lines','bonus spins','casino spins','spins','extras','bonus-spins','progress','base-multiplier','levels','features-collected','bonus-respins'}
    meters={'win-multiplier','multiplier','collect-bonuses','body-counter','win multiplier','remembered-multiplier'}
    for counter in last.findall('COUNTERS/COUNTER'):
        name=counter.get('name')
        if name not in known|meters:raise ValueError('unrecognized_continuation_counter')
        if name not in meters and D(counter.get('left','0'))>0:
            summaries=[a for a in last.iter('ACTION') if a.get('name')=='bonus-summary' and a.get('bonus-counter-left')=='0']
            fish_and_bird=table and parse_xml(table).get('gameid')=='10246' and name=='bonus-counter'
            if not fish_and_bird or not summaries or counter.get('current') is not None or counter.get('decrease') is not None:raise ValueError('bonus_steps_remaining')

def settlement(init,purchase,check,control):
    def require(condition,message):
        if not condition:raise ValueError(message)
    require(init.findtext('method')=='init' and purchase.findtext('method')=='purchase' and check.findtext('method')=='checkwin','native_method_mismatch')
    validate_fresh_demo(init)
    require(init.findtext('roundid')=='0' and D(init.findtext('gamesession/totbet'))==0 and D(init.findtext('gamesession/totwon'))==0,'not_a_fresh_demo')
    for response in (init,purchase,check):require(response.findtext('player/currency')=='EUR','unexpected_currency')
    published=next((c for c in mode_controls(init) if c['mode']==control['mode'] and c.get('variant')==control.get('variant')),None)
    require(published==control,'control_not_native_minimum')
    info=purchase.find('roundinfo');require(info is not None,'native_roundinfo_missing')
    native_round=purchase.findtext('roundid');require(native_round not in (None,'0'),'native_round_id_missing')
    require(info.findtext('roundid')==native_round==check.findtext('roundid'),'round_id_mismatch')
    cost=D(info.findtext('betamount'));win=D(info.findtext('winamount'));before=D(init.findtext('player/balance'));after=D(check.findtext('player/balance'))
    require(info.findtext('currency')=='EUR' and info.findtext('bmode')==control['mode'] and info.findtext('betlevel')==control['betlevel'],'native_mode_or_level_mismatch')
    require(cost==D(control['amount']) and cost>0 and win>=0,'native_entry_cost_mismatch')
    require(before-cost+win==after==D(info.findtext('balanceafterwin')),'wallet_mismatch')
    require(D(check.findtext('gamesession/totbet'))==cost and D(check.findtext('gamesession/totwon'))==win,'native_session_totals_mismatch')
    if check.find('gamesession/netposition') is not None:require(D(check.findtext('gamesession/netposition'))==win-cost,'native_netposition_mismatch')
    native=purchase_tree(purchase)
    if control.get('variant'):require(native.get('variant')==control['variant'],'pubdata_variant_mismatch')
    require(native.get('bmode')==(control['mode'] if init.find('betlevels').get('bmode')=='true' else None),'pubdata_mode_mismatch')
    if native.get('betlevel') is not None:require(native.get('betlevel')==control['betlevel'],'pubdata_level_mismatch')
    else:
        table=parse_xml(init.findtext('game/paytable'))
        if native.get('revision') or table.get('revision'):require(bool(native.get('revision')) and native.get('revision')==table.get('revision'),'unverified_legacy_revision')
        else:require(init.find('betlevels').get('bmode')=='false' and (table.get('protocol-version')=='2' or table.tag in ('SETUP','MODES') and bool(table.findall('CONFIG'))),'unverified_classic_contract')
        mode=next(m for level in init.findall('betlevels/betlevel') if level.get('id')==control['betlevel'] for m in level.findall('bmodes/bmode') if m.get('id')==control['mode'])
        coin=D(mode.get('coinvalue'))
        if native.get('coinvalue') is not None:require(D(native.get('coinvalue'))==coin,'legacy_coin_value_mismatch')
        coins=native.get('betcoins',native.get('bet'))
        if coins is not None:require(D(coins)*coin==cost,'legacy_bet_coins_mismatch')
        else:require(native.get('betamount') is not None and D(native.get('betamount'))==cost,'legacy_bet_amount_missing')
        native_win=native.get('win',native.get('wintot'))
        if native_win is None:native_win=native.findall('RESULT')[-1].get('wintotal')
        require(native_win is not None and D(native_win)*coin==win,'legacy_win_coins_mismatch')
    if native.get('betamount') is not None:require(D(native.get('betamount'))==cost,'pubdata_cost_mismatch')
    else:require(init.find('betlevels').get('bmode')=='false' and native.get('betcoins') is not None,'pubdata_cost_missing')
    require(D(native.get('winamount'))==win and native.get('currency','EUR')=='EUR','pubdata_money_mismatch')
    steps=results(purchase);require(bool(steps),'native_results_missing')
    validate_result_closure(init,purchase,control)
    indices=[r['attributes'].get('resultIndex') for r in steps]
    if any(i is not None for i in indices):require(all(i is not None for i in indices) and [int(i) for i in indices]==list(range(len(steps))),'native_result_order_mismatch')
    return {'cost':str(cost),'win':str(win),'balance_before':str(before),'balance_after':str(after),'wallet_check':'match','closed':True,'round_id':native_round,'native_results':len(steps)}
