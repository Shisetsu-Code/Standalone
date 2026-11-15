"""Native public-FUN demo rules; unknown decisions stop for review."""
import re,json,hashlib
from pathlib import Path
from decimal import Decimal
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

SECRET={'token','session_id','session','huid','user_id','player_id','authorization','cookie','cookies','auth','client_command_timestamp'}
CONTINUATIONS={'respin','bonus_init','bonus_spins_stop','freespin_init','freespin','freespin_stop'}

def sanitize(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower() in SECRET else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str) and value.startswith(('https://','http://','//')):
        u=urlsplit(value);q=[(k,'[REDACTED]' if k.lower() in SECRET else v) for k,v in parse_qsl(u.query,keep_blank_values=True)]
        return urlunsplit((u.scheme,u.netloc,re.sub(r'/[0-9a-f]{24,}/','/[REDACTED]/',u.path),urlencode(q),''))
    return value

def native_int(value):
    n=Decimal(str(value))
    if isinstance(value,bool) or not n.is_finite() or n!=int(n):raise ValueError('non_integer_native_money')
    return int(n)

def catalog_from_pages(pages):
    count={p['data']['total_pages'] for p in pages}
    if len(count)!=1 or {p['page'] for p in pages}!=set(range(1,next(iter(count))+1)) or len(pages)!=next(iter(count)):raise ValueError('incomplete_catalog_pages')
    games=[];seen=set()
    for p in sorted(pages,key=lambda x:x['page']):
        for g in p['data']['items']:
            gid=g['name']
            if g['provider']!='3oaks' or not re.fullmatch('[a-z0-9_]+',gid) or gid in seen:raise ValueError('ambiguous_catalog_identity')
            seen.add(gid);games.append({'ordinal':len(games)+1,'id':gid,'slug':gid,'name':g['title_text'],'release_date':g['release_date'],'provider':'threeoaks','has_page':g['has_page'],'details_url':'https://3oaks.com/api/v1/games/'+gid})
    return games

def bet_profile(start):
    settings=start['settings'];context=start['context']
    if start['status']['code']!='OK' or start['user']['currency']!='FUN' or context.get('round_finished') is not True:raise ValueError('fresh_fun_demo_not_idle')
    bets=[native_int(v) for v in settings['bets']];lines=[native_int(v) for v in settings['lines']];factors=[native_int(v) for v in settings['bet_factor']]
    if not bets or not lines or min(bets)<=0 or min(lines)<=0 or min(factors)<=0:raise ValueError('invalid_public_bet_ranges')
    selected=context['spins']['lines']
    if selected not in lines:raise ValueError('default_lines_not_published')
    if len(factors)==1:factor=factors[0]
    elif len(factors)==len(lines):factor=factors[lines.index(selected)]
    else:raise ValueError('bet_factor_mapping_unproven')
    scale=native_int(settings['currency_format']['denominator'])
    if scale<=0:raise ValueError('invalid_currency_scale')
    return {'bet_per_line':min(bets),'lines':selected,'bet_factor':factor,'base_cost_native':min(bets)*factor,'scale':scale}

def next_action(context,source=None):
    if context.get('round_finished') is True:return None
    actions=context.get('actions',[])
    if len(actions)!=1:raise ValueError('unrecognized_native_decision:'+str(actions))
    name=actions[0]
    if name not in CONTINUATIONS:
        path=Path(__file__).parent/'threeoaks/reference/continuation-bindings.json'
        bindings=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
        proof=bindings.get(hashlib.sha256(source.encode('utf8')).hexdigest(),{}) if source else {}
        if name not in proof.get('empty_actions',[]):raise ValueError('unrecognized_native_decision:'+str(actions))
    return {'name':actions[0],'params':{}}

def mode_inventory(start,source):
    p=bet_profile(start);s=start['settings'];c=start['context'];base=p['base_cost_native'];params={'bet_per_line':p['bet_per_line'],'lines':p['lines']}
    result=[{'key':'normal','kind':'normal','action':{'name':'spin','params':params},'cost_native':base,'supported':True}]
    bindings_path=Path(__file__).parent/'threeoaks/reference/serializer-bindings.json'
    source_sha=hashlib.sha256(source.encode('utf8')).hexdigest()
    bindings=json.loads(bindings_path.read_text(encoding='utf8')) if bindings_path.exists() else {}
    binding=bindings.get(source_sha,{});schema=binding.get('buy_schema');booster_schema=binding.get('booster_schema')
    branch_ok=True
    for guard in binding.get('guards',[]):
        value=s
        for key in guard['path'].split('.'):value=value.get(key) if isinstance(value,dict) else None
        if guard['test']=='falsy':branch_ok=branch_ok and not value
        elif guard['test']=='positive':branch_ok=branch_ok and value is not None and Decimal(str(value))>0
        else:branch_ok=False
    for mode in c.get('available_buy_bonus',[]):
        price=s.get('buy_bonus_prices',s.get('freespins_buying_price',{})).get(str(mode));key='buy-'+str(mode)
        row={'key':key,'kind':'buy','mode_id':mode,'supported':False,'price_multiplier':price}
        try:
            if 'buy_spin' not in c.get('actions',[]) or price is None or Decimal(str(price))<=0:raise ValueError('buy_price_or_action_unpublished')
            if not branch_ok:raise ValueError('source_settings_branch_not_proven')
            buy=dict(params)
            if schema=='flow_numeric_zero_based_no_factor':
                if int(mode)<1:raise ValueError('zero_based_buy_mode_not_published')
                buy['selected_mode']=int(mode)-1
            elif schema in ('direct_numeric','direct_string','flow_numeric','flow_string','flow_numeric_no_factor'):
                buy['selected_mode']=str(mode) if schema.endswith('string') else int(mode)
                if schema in ('flow_numeric','flow_string'):buy['bet_factor']=p['bet_factor']
            elif schema=='flow_scatter_count':
                if p['lines']!=p['bet_factor']:raise ValueError('scatter_buy_lines_factor_mismatch')
                buy.update(bet_factor=p['bet_factor'],ante_bet=0,buy_spin_scatters_count=int(mode)+3)
            elif schema in ('direct_plain','flow_plain','flow_plain_no_factor'):
                if [str(x) for x in c.get('available_buy_bonus',[])]!=['1']:raise ValueError('plain_buy_requires_one_native_option')
                if schema=='flow_plain':buy['bet_factor']=p['bet_factor']
            elif schema=='direct_paid_feature':
                feature=binding.get('paid_feature_map',{}).get(str(mode))
                if not feature:raise ValueError('paid_feature_id_not_proven')
                buy['paid_feature']=feature
            else:raise ValueError('buy_wire_schema_needs_review')
            row.update(action={'name':'buy_spin','params':buy},cost_native=native_int(Decimal(base)*Decimal(str(price))),supported=True)
        except ValueError as exc:row['error']=str(exc)
        result.append(row)
    seen=set()
    for mode in c.get('available_booster',[]):
        price=s.get('booster_prices',{}).get(str(mode));row={'key':'booster-'+str(mode),'kind':'booster','mode_id':mode,'supported':False,'price_multiplier':price}
        try:
            if price is None or Decimal(str(price))<=0:raise ValueError('booster_price_unpublished')
            boost=dict(params)
            if not branch_ok:raise ValueError('source_settings_branch_not_proven')
            if booster_schema=='gr_option' and 'booster_spin' in c.get('actions',[]):boost['selected_mode']=mode;action='booster_spin'
            elif booster_schema=='gr_option':boost.update(ante_bet=price,selected_mode=mode);action='spin'
            elif booster_schema=='ante_only':boost['ante_bet']=price;action='spin'
            else:raise ValueError('booster_wire_schema_needs_review')
            row.update(action={'name':action,'params':boost},cost_native=native_int(Decimal(base)*Decimal(str(price))),supported=True);seen.add(str(price))
        except ValueError as exc:row['error']=str(exc)
        result.append(row)
    for price in s.get('ante_bet',[]):
        if Decimal(str(price))<=1 or str(price) in seen:continue
        boost=dict(params,ante_bet=price);row={'key':'ante-'+str(price).replace('.','_'),'kind':'booster','price_multiplier':price,'supported':False}
        if booster_schema=='ante_only' and branch_ok:
            try:row.update(action={'name':'spin','params':boost},cost_native=native_int(Decimal(base)*Decimal(str(price))),supported=True)
            except ValueError:row['error']='ante_cost_not_integral'
        else:row['error']='ante_wire_schema_needs_review'
        result.append(row)
    return result

def reconcile(before,cost,steps,source=None):
    if not steps:raise ValueError('no_round_steps')
    before=native_int(before);cost=native_int(cost)
    for i,step in enumerate(steps):
        r=step['response'];action=step['request']['action']
        if step.get('status','received')!='received' or step['http_status']!=200 or r.get('status',{}).get('code')!='OK' or r['user']['currency']!='FUN':raise ValueError('uncertain_or_failed_fun_request')
        if r['context'].get('last_action')!=action['name']:raise ValueError('native_action_echo_mismatch')
        if i and action!=next_action(steps[i-1]['response']['context'],source):raise ValueError('unexpected_or_additional_paid_action')
    final=steps[-1]['response'];c=final['context']
    if c.get('round_finished') is not True or c.get('current')!='spins' or 'spin' not in c.get('actions',[]):raise ValueError('native_round_not_closed')
    win=native_int(c['spins']['total_win']);after=native_int(final['user']['balance'])
    if cost<=0 or win<0 or before-cost+win!=after:raise ValueError('native_wallet_mismatch')
    return {'balance_before_native':before,'cost_native':cost,'win_native':win,'balance_after_native':after,'wallet_check':'match','internal_steps':len(steps)}
