"""Star Trek's source-defined bonus selection and continuation; native FUN requests only."""
import re,hashlib,copy
from native_variants import balanced
def metadata(source,integration):
 required=['.BONUS="fs_choice"','.PICK_RESPIN="pick_respin"','.CASH_PRIZE="cash_prize"','this.onPickMeObjectClicked(e+1)','[this.lowVolatility,this.mediumVolatility,this.highVolatility,this.gamble]']
 if any(term not in source for term in required) or not re.search(r'\.params\.choice=([A-Za-z_$][\w$]*)\.BGInput\.Object',source):raise ValueError('Star Trek one-based choice request not proved')
 methods=list(re.finditer(r'defineNextRound\([^)]*\)\{',integration))
 if not methods:raise ValueError('Star Trek state transition method absent')
 body=balanced(integration,methods[-1].end()-1)
 if any(term not in body for term in ['scatterPositions.length','numFreeSpins','numOfRespin','revealOrder','isCashPrizeAwarded']):raise ValueError('Star Trek transition schema not recognized')
 return dict(star_choices_verified=True,star_choice_values=[1,2,3,4],star_choice_labels=['low','medium','high','random'],star_choice_source_sha256=hashlib.sha256(source.encode()).hexdigest(),star_transition_method_sha256=hashlib.sha256(body.encode()).hexdigest(),star_choice_evidence='One-based pick callback feeds BGInput.Object and custom_req.choice; four source popups. fs_choice/respin/pick_respin/cash_prize names and defineNextRound predicates from this game client. Respin picks/cash prize request factories send no player-coordinate field.')
def expand(modes):
 result=[]
 for mode in modes:
  if mode.get('custom_params',{}).get('isFeatureBuyFreeSpin'):
   for choice in range(1,5):m=copy.deepcopy(mode);m.update(name=mode['name']+'/choice:'+str(choice),freespin_choice=choice);result.append(m)
  else:result.append(mode)
 return result
def next_request(result,mode,meta):
 if not meta.get('star_choices_verified') or result.get('final') is not False:raise RuntimeError('Unverified Star Trek open state')
 g=result.get('resp',{}).get('engine',{}).get('gamestate',{});current=g.get('action');fs=g.get('freespinState',{});rs=g.get('respinState',{});pick=g.get('pickState',{});cash=rs.get('cashPrize') or {};reveal=rs.get('revealOrder') or {};scatters=g.get('triggeringDetails',{}).get('scatterPositions',[]);action=None
 # Mirror the source's priority: respins, freespins, scatter selection, pick round, cash prize.
 if rs.get('numOfRespin',0)>0:action='respin'
 if fs.get('numFreeSpins',0)>0:action='freespin'
 eligible=current in ['spin','autospin','pick_respin','cash_prize'];pick_finished=current!='pick_respin' or (not rs.get('numOfRespin',0) and (not pick or reveal.get('total_pick')==pick.get('pick_index',-1)+1));cash_ok=current!='cash_prize' or cash.get('winnings')!=0
 if eligible and len(scatters)==3 and not rs.get('numOfRespin',0) and pick_finished and cash_ok:action='fs_choice'
 if current=='respin' and reveal.get('total_pick',0)>0:action='pick_respin'
 if current=='pick_respin' and reveal and pick.get('pick_index',-1)+1!=reveal.get('total_pick'):action='pick_respin'
 if current=='pick_respin' and reveal and pick.get('pick_index',-1)+1==reveal.get('total_pick') and rs.get('isCashPrizeAwarded'):action='cash_prize'
 if current=='cash_prize' and cash.get('level',0)>0 and cash.get('winnings')==0 and rs.get('isCashPrizeAwarded'):action='cash_prize'
 if action is None:raise RuntimeError('Unknown Star Trek continuation; received state retained')
 custom={'action':action,'exponent':2}
 if action=='fs_choice':
  choice=mode.get('freespin_choice',1)
  if type(choice) is not int or not 1<=choice<=4:raise RuntimeError('Star Trek choice outside verified source range')
  custom['choice']=choice
 return dict(bet=mode['bet_native'],bet_type='bet',custom_req=custom)
