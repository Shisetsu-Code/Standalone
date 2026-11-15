"""Native gold_symbols_count selectors; expected prices only, never rewritten responses."""
import re,hashlib
def metadata(source):
 if not re.search(r'additionalSpinOptions\.gold_symbols_count=""\+[A-Za-z_$][\w$]*',source) or '*this.BET_BY_SPECIAL_LVL[' not in source or 'this.BET_BY_SPECIAL_LVL[this.goldSymbolsLevel]' not in source:raise ValueError('Gold-symbol native selector/price evidence missing')
 identifiers=set(re.findall(r'BET_BY_SPECIAL_LVL=([A-Za-z_$][\w$]*)',source));maps=[]
 for identifier in identifiers:
  matches=re.findall(r'(?<![\w$])'+re.escape(identifier)+r'=\{((?:\d+:\d+)(?:,\d+:\d+)*)\}',source)
  if len(set(matches))!=1:raise ValueError('Gold-symbol factor map not explicit')
  maps.append(dict((k,int(v)) for k,v in re.findall(r'(\d+):(\d+)',matches[0])))
 if not maps or any(m!=maps[0] for m in maps) or set(maps[0])!=set('12345'):raise ValueError('Gold-symbol client classes disagree on factor map')
 if not re.search(r'for\(var ([A-Za-z_$][\w$]*) in ([A-Za-z_$][\w$]*)\)\2\[\1\]=\2\[\1\]\*this\.BET_BY_SPECIAL_LVL\[\1\]',source):raise ValueError('Feature multiplier per gold level not proved')
 if not re.search(r'beforeGoFreespins\([^)]*\)\{super\.beforeGoFreespins\([^)]*\),delete this\.additionalSpinOptions\.gold_symbols_count',source):raise ValueError('Gold-symbol removal before freespins not proved')
 return dict(gold_symbols_factors=maps[0],gold_symbols_source_sha256=hashlib.sha256(source.encode()).hexdigest(),gold_symbols_removed_before_freespins=True,gold_symbols_evidence='Source uses native string gold_symbols_count for paid spins, removes it in beforeGoFreespins, restores it afterExitFreespins, and multiplies per-level feature prices by explicit BET_BY_SPECIAL_LVL factors; raw wire bet remains unchanged')
def plan(initial,meta):
 o=initial['options'];currency=o['currency'];bet=min(o['available_bets']);factors=meta['gold_symbols_factors'];fm=o['feature_options']['feature_multipliers'];disabled=o['feature_options'].get('disabled_features',[]);base=fm.get('base_bet',meta.get('feature_default_base_bet'))
 if currency.get('code')!='FUN' or currency.get('subunits')!=100 or type(bet) is not int or bet<=0 or type(base) is not int or base<=0:raise ValueError('Unverified gold-symbol amounts')
 modes=[]
 for level,factor in sorted(factors.items()):
  args={'bet':bet,'gold_symbols_count':level};cost=bet*factor
  modes.append(dict(name='gold_symbols:'+level+'/normal',command='spin',options=args,cost_native=cost))
  for feature,values in fm.items():
   if feature=='base_bet' or feature in disabled:continue
   if not isinstance(values,dict) or level not in values or type(values[level]) is not int:raise ValueError('Unrecognized gold-symbol feature level')
   numerator=cost*values[level];price,remainder=divmod(numerator,base);kind='antebet' if feature.endswith('_chance') else 'purchase'
   if remainder and meta.get('price_rounding',{}).get(kind)!='ceil':raise ValueError('Gold-symbol fractional price rule unproved')
   modes.append(dict(name='gold_symbols:'+level+'/'+feature,command='spin',options=dict(args,purchased_feature=feature,purchased_feature_level=level),cost_native=price+bool(remainder)))
 return modes
