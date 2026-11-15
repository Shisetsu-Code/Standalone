"""Requeue only init/rejection evidence after explicit per-game source corrections."""
import json,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
TARGETS={'Plinko':'classic-plinko','Maneki88Fortunes':'gold-symbols','Maneki88Gold':'gold-symbols','StarTrekNextGen':'jsonrpc','LuckAndMagicScratch':'fixed-play','HeadsTails':'classic-heads','HeadsTailsXY':'classic-heads','LokiLoot':'legacy-prices'}
TARGETS.update({gid:'native-variants' for gid in ['BalloonMania','ChickenShot','KickerMania','OpenIt','HotChilliBells','RoyalBeellionHoldAndWin','WildTiger2']})
TARGETS['BigAtlantisFrenzy']='indexed-rows'
TARGETS['MultiRush']='product-round'
TARGETS['WildClustersP']='product-round'
TARGETS['LuckyBirds']='lucky-birds'
TARGETS['SweetSamurai']='flat-rpc'
TARGETS.update({gid:'four-modern-slots-prepared' for gid in ['CatsLoveYummy','RedHotChilliChickens','MysticReels','ChickenFire']})
TARGETS.update({gid:'final-pair-prepared' for gid in ['YommiRush','JokerVsJoker']})
TARGETS.update({gid:'blackjack-prepared' for gid in ['BlackjackPro','MultihandBlackjack','ClassicMultihandBlackjack','MultihandBlackjackPro2','SurrenderMultihandBlackjack']})
TARGETS.update({gid:'rpc-extra-prepared' for gid in ['Robospin','KeepersOfTheSecret7rst','GrandPatron7rst','BigBucksSaloon','ClashofGodsAnubisvsHades','AztecsClawWildDice']})
TARGETS.update({gid:'native-modes-prepared' for gid in ['InfinityPull','ChickenRush2','PenaltyDuel','PenaltyDuelWithJulioCesar','FishingTime','ElementsOfPower','JogoDoBicho','TileMaster']})
TARGETS.update({gid:'native-tables-prepared' for gid in ['RocketDice','RocketDiceXY','MineGems','FortuneRedPackets','Minesweeper','MinesweeperXY']})
TARGETS.update({gid:'rpc-extra-prepared' for gid in ['JungleQueen','SugarMix','TreasureExplorer','ZeusGoesWild']})
TARGETS.update({gid:'rpc-extra-prepared' for gid in ['RecycleRiches','BlackbeardsBounty','BlazingFirepots']})
TARGETS['Limbo']='limbo'
TARGETS['ThreeKingsScratch']='scratch-packs'
TARGETS['RoyalRoulette500X']='royal-roulette'
TARGETS.update({gid:'classic-roulette' for gid in ['AmericanRoulette','EuropeanRoulette','FrenchRoulette']})
TARGETS.update({gid:'native-play' for gid in ['DiceClash','StreetPower','FortuneSpin']})
TARGETS.update({gid:'classic-plinko' for gid in ['EasterPlinko','PlinkoXY']})
TARGETS.update({gid:'volatility' for gid in ['DiamondOfJungle','DiscoParty']})
TARGETS.update({gid:'line-counts' for gid in ['BurningChilliX','RoyalFruitsMultiLines','WildTiger','FishingClub','WinterFishingClub']})
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 changed=[]
 selected=sys.argv[1:] or list(TARGETS)
 if not set(selected)<=set(TARGETS):raise ValueError('Unprepared identifier')
 for gid in selected:
  proof=TARGETS[gid]
  if gid not in state['results']:continue
  result=state['results'][gid];path=ROOT/result['report'];r=json.loads(path.read_text(encoding='utf8'))
  if r.get('modes'):raise ValueError('Do not discard received closed modes: '+gid)
  for event in r.get('events',[]):
   q=event.get('request',{});response=event.get('response',{})
   if q.get('command')=='init' or q.get('method')=='init':continue
   if event.get('status')==422 and response.get('errors')==[{'code':203,'desc':'invalid_options'}]:continue
   if q.get('method')=='play' and response.get('error') and 'result' not in response:continue
   raise ValueError('Unclassified previous gameplay: '+gid)
  if proof!='jsonrpc' and not (ROOT/'protocols'/(gid+'.'+proof+'.json')).exists():raise ValueError('Source proof missing '+gid)
  archive=ROOT/'live'/'attempts'/(gid+'.before-prepared-wire-v2.json')
  if archive.exists():raise ValueError('Already enqueued '+gid)
  save(archive,r)
  for source in [PRIVATE/(gid+'.session.json'),PRIVATE/'hyperhive'/(gid+'.session.json')]:
   if source.exists():
    target=PRIVATE/'attempts'/(gid+'.'+source.parent.name+'.before-prepared-wire-v2.session.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),source_proof='protocols/'+gid+('' if proof=='jsonrpc' else '.'+proof)+'.json',reason='Native request contract proved in this official client and regression-tested. Previous rejected/init evidence preserved. Fresh independent FUN launch; no POST replay.'))
  del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(ROOT/'run-state.json',state);save(ROOT/'prepared-wire-v2-requeue.json',dict(updated_at=now(),games=changed));print('Prepared cases queued',changed)
