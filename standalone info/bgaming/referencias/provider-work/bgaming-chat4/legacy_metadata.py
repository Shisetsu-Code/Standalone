"""Read the official loader/bundle to prove omitted legacy feature-price defaults."""
import re,hashlib,urllib.request
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save
def client_route(text):
 basic=re.search(r'"basic"\s*:\s*\{[^}]*\bres\s*:\s*"([A-Za-z0-9_./-]+)"',text)
 if basic:
  version=basic[1]
  if version.startswith('/') or any(part in ('.','..','') for part in version.split('/')):raise ValueError('Invalid static resource route')
  return version,version+'/bundle.js'
 m=re.search(r'res:[A-Za-z_$][\w$]*="([A-Za-z0-9_.-]+)"',text)
 if m:return m[1],m[1]+'/bundle.js'
 entries=set(re.findall(r'/assets/[A-Za-z0-9_-]+\.js',text))
 if len(entries)!=1:raise ValueError('Legacy resource version needs review')
 route=entries.pop().lstrip('/');return route.rsplit('/',1)[-1],route

def load_client(gid,opener):
 if not re.fullmatch('[A-Za-z0-9_-]+',gid):raise ValueError('Invalid client identifier')
 if getattr(opener,'classic_casino',False):
  url='https://cdn.bgaming-network.com/html/casino.min.js';cache=PRIVATE/'research'/'classic'/'casino.min.js'
  if cache.exists():raw=cache.read_bytes()
  else:
   with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as r:
    if r.url!=url:raise ValueError('Unexpected classic source redirect')
    raw=r.read()
   cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(raw)
  return dict(client_family='classic-casino',client_version=getattr(opener,'classic_version',None),source_url=url,source_sha256=hashlib.sha256(raw).hexdigest()),raw.decode('utf8')
 origin='https://cdn.bgaming-network.com/html/'+gid+'/'
 def get(route):
  cache=PRIVATE/'research'/'legacy'/gid/route
  if cache.exists():return cache.read_bytes()
  with opener.open(urllib.request.Request(origin+route,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as r:
   if urlsplit(r.url).hostname!='cdn.bgaming-network.com':raise ValueError('Unexpected static source origin')
   raw=r.read()
  cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(raw);return raw
 loader=get('loader.js');text=loader.decode('utf8');version,route=client_route(text)
 raw=get(route);return dict(client_version=version,source_url=origin+route,source_sha256=hashlib.sha256(raw).hexdigest(),loader_sha256=hashlib.sha256(loader).hexdigest()),raw.decode('utf8')

def prove_default(gid,opener):
 result,source=load_client(gid,opener)
 proof=re.search(r'([A-Za-z_$][\w$]*)=[A-Za-z_$][\w$]*\.options\.feature_options\.feature_multipliers,[A-Za-z_$][\w$]*=\1\.base_bet\|\|100',source)
 if not proof:raise ValueError('Default feature denominator not proved in this client')
 result.update(source_verified=True,feature_default_base_bet=100,evidence='initBuyFeatures assigns feature_multipliers.base_bet || 100 before calculating purchase/chance ratios')
 result['rows_parameter_verified']='this.additionalSpinOptions.rows=String(this.reelSize)' in source
 result['rows_feature_level_verified']='purchased_feature_level=""+this.reelSize' in source and 'this.FREESPIN_BUY,this.reelSize' in source
 variables=set(re.findall(r'setBetsVisibleMultiplier\(([A-Za-z_$][\w$]*)\[this\.reelSize\]',source));factors={}
 if len(variables)==1:
  name=variables.pop();maps=re.findall(r'(?<![\w$])'+re.escape(name)+r'=\{((?:\d+:\d+(?:\.\d+)?)(?:,\d+:\d+(?:\.\d+)?)*)\}',source)
  if len(set(maps))==1:factors={key:value for key,value in re.findall(r'(\d+):(\d+(?:\.\d+)?)',maps[0])}
 result['rows_normal_factors']=factors
 result['extra_bonus_command_verified']=bool(re.search(r'\{command:"buy_extra_bonus",options:\{bonus_type:[A-Za-z_$][\w$]*\}\}',source))
 result['extra_bonus_types']=[name for name in ['extra_spin','extra_board','extra_multiplier','regenerate_bonus'] if re.search(re.escape(name)+r':\{command:"'+re.escape(name)+'"',source)] if result['extra_bonus_command_verified'] else []
 from native_variants import balanced
 rounding={};rounding_proof=[]
 for kind,method in [('purchase','_recalculateBonusPrices'),('antebet','_recalculateChancePrices')]:
  marker=re.search(re.escape(method)+r'\(\)\{',source)
  if marker:
   body=balanced(source,marker.end()-1)
   if 'Math.ceil(' in body:rounding[kind]='ceil';rounding_proof.append(dict(kind=kind,method=method,method_sha256=hashlib.sha256(body.encode()).hexdigest(),operator='Math.ceil'))
 result['price_rounding']=rounding;result['rounding_evidence']=rounding_proof;result['rounding_validation']='Compiled client rule; each active price is accepted only if native wallet debit matches. Responses and request bet are not rewritten.'
 save(ROOT/'protocols'/(gid+'.legacy-prices.json'),result);return result

def prove_fixed_play(gid,opener):
 result,source=load_client(gid,opener)
 if '.playCommand="play"' not in source or not re.search(r'\.data\.totalBet=[A-Za-z_$][\w$]*\.options\.bet',source) or not re.search(r'options:\{bet:[A-Za-z_$][\w$]*\.A\.data\.totalBet,bonus:!!',source):raise ValueError('Fixed scratch play envelope not proved')
 result.update(source_verified=True,fixed_play_verified=True,evidence='Client initializes totalBet from options.bet and sends play with that native bet and bonus=false')
 save(ROOT/'protocols'/(gid+'.fixed-play.json'),result);return result

def prove_native_variants(gid,opener):
 from native_variants import parse
 result,source=load_client(gid,opener);variants=parse(source)
 result.update(source_verified=True,native_variants=variants,evidence='Explicit official allOptions variants and native request mode/bet conversion, parsed as data without executing source. Planned prices must still reconcile against native server balances.')
 save(ROOT/'protocols'/(gid+'.native-variants.json'),result);return result

def prove_continuations(gid,opener):
 result,source=load_client(gid,opener);commands=[]
 for name in ['preselection_game','play_preselection_game']:
  expression=r'\{command:"'+re.escape(name)+r'"\};[A-Za-z_$][\w$]*\.sendCommand\('
  if re.search(expression,source):commands.append(name)
 options={}
 if gid=='WildMoonThieves' and re.search(r'sendCommand\(([A-Za-z_$][\w$]*)\)\{var ([A-Za-z_$][\w$]*)=\{command:"play_preselection_game",options:\1\};[A-Za-z_$][\w$]*\.sendCommand\(\2\)',source) and re.search(r'autoOpenDoors\(\)\{this\.isWaitingResponse=!0,this\.sendCommand\(\{mode:"auto"\}\)',source):
  commands.append('play_preselection_game');options['play_preselection_game']={'mode':'auto'}
 proof=dict(legacy_continuations=commands,continuation_options=options,continuation_source=result,continuation_evidence='Exact client request and immediate sendCommand call; WildMoon auto branch uses literal mode=auto. Manual door indices are not inferred.')
 if gid=='WildMoonThieves' and options:proof['unresolved']=['Manual door selection branch known in source, not yet exercised; automatic branch only']
 save(ROOT/'protocols'/(gid+'.continuations.json'),proof);return proof

def prove_alice_choices(gid,opener):
 if gid!='AliceWonderLuck':raise ValueError('Alice contract cannot be applied to another game')
 from alice_choices import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.choices.json'),result);return result

def prove_old_slot(gid,opener):
 if getattr(opener,'classic_casino',False):
  from classic_slots import metadata as classic_metadata
  result,source=load_client(gid,opener);result.update(classic_metadata(source,gid));save(ROOT/'protocols'/(gid+'.old-slots.json'),result);return result
 from old_slots import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.old-slots.json'),result);return result

def prove_classic_plinko(gid,opener):
 if gid not in ['Plinko','EasterPlinko','PlinkoXY']:raise ValueError('Classic Plinko source contract has not been verified for another identifier')
 from classic_plinko import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.classic-plinko.json'),result);return result

def prove_gold_symbols(gid,opener):
 if gid not in ['Maneki88Fortunes','Maneki88Gold']:raise ValueError('Gold-symbol source contract not verified for this identifier')
 from gold_symbols import metadata
 result=prove_default(gid,opener);_,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.gold-symbols.json'),result);return result

def prove_freespin_types(gid,opener):
 if gid not in ['MonsterHunt','AlohaKingElvis','CatchTheGoldHoldAndWin']:raise ValueError('Free-spin type contract not verified for this identifier')
 from freespin_types import metadata
 result=prove_default(gid,opener);_,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.freespin-types.json'),result);return result

def prove_classic_heads(gid,opener):
 if not getattr(opener,'classic_casino',False):raise ValueError('Classic client script not observed in fresh launch')
 from classic_heads import metadata
 result,source=load_client(gid,opener);result.update(metadata(source,gid));save(ROOT/'protocols'/(gid+'.classic-heads.json'),result);return result

def prove_indexed_rows(gid,opener):
 if gid!='BigAtlantisFrenzy':raise ValueError('Indexed row minimum contract not verified for this game')
 from indexed_rows import metadata
 result=prove_default(gid,opener);_,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.indexed-rows.json'),result);return result

def prove_volatility(gid,opener):
 if gid not in ['DiamondOfJungle','DiscoParty']:raise ValueError('Paid volatility contract not verified for this identifier')
 from volatility_modes import metadata
 result=prove_default(gid,opener);_,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.volatility.json'),result);return result

def prove_line_counts(gid,opener):
 if gid not in ['BurningChilliX','RoyalFruitsMultiLines','WildTiger','FishingClub','WinterFishingClub']:raise ValueError('Line-count selector contract not verified for this identifier')
 from line_count_modes import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.line-counts.json'),result);return result

def prove_cats_choices(gid,opener):
 if gid!='CatsSoup':raise ValueError('Cats Soup contract is game-specific')
 from cats_choices import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.choices.json'),result);return result

def prove_limbo(gid,opener):
 if gid!='Limbo':raise ValueError('Unverified Limbo game identifier')
 from limbo import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.limbo.json'),result);return result

def prove_native_play(gid,opener):
 from native_play_modes import metadata
 result,source=load_client(gid,opener);result.update(metadata(gid,source));save(ROOT/'protocols'/(gid+'.native-play.json'),result);return result

def prove_classic_roulette(gid,opener):
 if not getattr(opener,'classic_casino',False):raise ValueError('Fresh launch did not confirm shared classic client')
 from classic_roulette import metadata
 result,source=load_client(gid,opener);result.update(metadata(gid,source));save(ROOT/'protocols'/(gid+'.classic-roulette.json'),result);return result

def prove_royal_roulette(gid,opener):
 if gid!='RoyalRoulette500X':raise ValueError('Royal Roulette schema is game-specific')
 from royal_roulette import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.royal-roulette.json'),result);return result

def prove_scratch_packs(gid,opener):
 if gid!='ThreeKingsScratch':raise ValueError('Scratch pack schema is game-specific')
 from scratch_packs import metadata
 result,source=load_client(gid,opener);result.update(metadata(source));save(ROOT/'protocols'/(gid+'.scratch-packs.json'),result);return result

def prove_native_tables(gid,opener):
 if gid in ['Minesweeper','MinesweeperXY'] and not getattr(opener,'classic_casino',False):raise ValueError('Classic mine script not confirmed in fresh launch')
 from native_tables_extra import metadata
 result,source=load_client(gid,opener);result.update(metadata(source,gid));save(ROOT/'protocols'/(gid+'.native-tables-live-source.json'),result);return result

def prove_native_modes_extra(gid,opener):
 from native_modes_extra import metadata
 result,source=load_client(gid,opener);result.update(metadata(source,gid));save(ROOT/'protocols'/(gid+'.native-modes-extra-live-source.json'),result);return result

def prove_blackjack(gid,opener):
 from blackjack_extra import metadata
 result,source=load_client(gid,opener);result.update(metadata(source,gid));save(ROOT/'protocols'/(gid+'.blackjack-live-source.json'),result);return result
