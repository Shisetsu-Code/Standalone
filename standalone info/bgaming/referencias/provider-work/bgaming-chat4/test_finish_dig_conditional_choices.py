"""Offline native Dig finite choices; no provider transport or persistent state."""
import copy
import importlib
import unittest

from bonus_choices_extra import CARDS,PINS


def response(wallet=10000,game=0,state='closed',round_id='r0',action='a0',command='spin'):
 return dict(balance=dict(wallet=wallet,game=game),flow=dict(state=state,round_id=round_id,last_action_id=action,command=command,available_actions=['init','spin'] if state=='closed' else ['init','gamble','close']))


def fixture():
 initial=response(command='init');initial['options']=dict(currency=dict(code='FUN',subunits=100),available_bets=[10,20])
 modes=[dict(mode=dict(name='normal'),status='closed_financial_anomaly',financial_status='failed')]
 modes += [dict(mode=dict(name='freespin_buy:'+str(i)),status='closed',original_purchase=i) for i in range(1,10)]
 declared=[]
 for c in CARDS:
  m=dict(name='conditional_card/'+c,command='spin',options=dict(bet=10),cost_native=10,conditional_card=True,gamble_choice=c,maximum_paid_attempts=1)
  declared.append(m);modes.append(dict(mode=copy.deepcopy(m),status='needs_trigger',first_event=0,last_event=0,paid_attempts=1,attempted_once=True,reason='Original one attempt did not offer target'))
 report=dict(game=dict(game_id='DigDigDigger'),status='needs_review',declared_modes=declared,modes=modes,
             protocol_metadata=dict(source_verified=True,source_sha256=PINS['DigDigDigger']),
             events=[dict(request=dict(command='init'),response=initial,status=200)],checks=[dict(kind='historic_failure',ok=False,event=0)],
             bonus_mode_coverage=dict(tested=['s'],executed_not_financially_verified=['s'],pending=list(CARDS[1:]),collect_tested=True))
 return report


class Fake:
 def __init__(self,report,outcome='lose',stake=20,fail_command=None):
  self.events=report['events'];self.money_checks=report['checks'];self.last_response=copy.deepcopy(self.events[-1]['response']);self.prev=self.last_response
  self.requests=[];self.outcome=outcome;self.stake=stake;self.fail_command=fail_command;self.n=0
 def call(self,command,options=None):
  self.requests.append((command,options));self.n+=1
  if command==self.fail_command:raise OSError('uncertain test transport')
  old=self.last_response;b=old['balance'];r=old['flow']['round_id']
  if command=='spin':
   offered=self.outcome!='none';after=response(b['wallet']+b['game']-10,self.stake if offered else 0,'gamble' if offered else 'closed','r'+str(self.n),'a'+str(self.n),command)
   after['outcome']=dict(bet=10,win=self.stake if offered else 0)
  elif command=='gamble':
   choice=options['bet'];win=self.outcome=='win';payout=b['game']*(2 if choice in ('black','red') else 4) if win else 0
   after=response(b['wallet'],payout,'gamble' if win else 'closed',r,'a'+str(self.n),command)
   after['gamble']=dict(win=win,bet=b['game'])
  elif command=='close':after=response(b['wallet'],b['game'],'closed',r,old['flow']['last_action_id'],command)
  else:raise AssertionError('Unproved command')
  self.last_response=after;self.events.append(dict(request=dict(command=command,**({'options':copy.deepcopy(options)} if options is not None else {})),response=copy.deepcopy(after),status=200));return after


class FiniteDigTests(unittest.TestCase):
 def setUp(self):
  self.m=importlib.import_module('finish_dig_conditional_choices');self.proof=self.m.cached_proof()
 def test_six_losses_close_only_matching_modes_preserving_purchase_and_failure(self):
  report=fixture();saved=copy.deepcopy(report);d=Fake(report);self.m.execute(d,report,self.proof)
  self.assertEqual([q[1]['bet'] for q in d.requests if q[0]=='gamble'],list(CARDS))
  self.assertEqual(report['modes'][:10],saved['modes'][:10]);self.assertEqual(report['checks'][0],saved['checks'][0]);self.assertEqual(report['status'],'needs_review')
  self.assertTrue(all(m['status']=='closed' and len(m['attempts'])==2 for m in report['modes'][10:]))
  self.assertEqual(report['dig_finite_conditional']['gross_native_debit'],180)
  self.assertEqual(self.m.audit_extension(report,self.proof)['failed'],0)
 def test_wins_collect_once_and_pending_credit_funds_next_spin(self):
  report=fixture();d=Fake(report,'win');self.m.execute(d,report,self.proof,max_attempts=2)
  self.assertEqual([q[0] for q in d.requests],['spin','gamble','close','spin','gamble','close'])
  self.assertEqual(report['events'][4]['response']['balance']['wallet'],10060)
  self.assertEqual(self.m.audit_extension(report,self.proof)['failed'],0)
 def test_no_offer_caps_one_hundred_and_does_not_claim_target(self):
  report=fixture();d=Fake(report,'none');self.m.execute(d,report,self.proof)
  self.assertEqual(len(d.requests),100);self.assertTrue(all(m['status']=='needs_trigger' for m in report['modes'][10:]));self.assertEqual(report['dig_finite_conditional']['pending_choices'],list(CARDS))
  self.assertEqual(len(report['modes'][10]['attempts']),101)
 def test_native_gross_budget_includes_gamble_stake_and_collects_if_too_large(self):
  report=fixture();d=Fake(report,stake=100);self.m.execute(d,report,self.proof,max_attempts=1,gross_native_budget=50)
  self.assertEqual([q[0] for q in d.requests],['spin','close']);self.assertEqual(report['dig_finite_conditional']['gross_native_debit'],10)
  self.assertEqual(report['modes'][10]['status'],'needs_trigger')
 def test_uncertain_gamble_stops_no_retry_and_claim_blocks_second_execute(self):
  report=fixture();d=Fake(report,fail_command='gamble');self.m.execute(d,report,self.proof)
  self.assertEqual([q[0] for q in d.requests],['spin','gamble']);self.assertEqual(report['dig_finite_conditional']['status'],'needs_review')
  with self.assertRaises(ValueError):self.m.execute(d,report,self.proof)
 def test_source_caps_open_context_and_wrong_wire_rejected_before_call(self):
  for change in ('source','cap','open','wire'):
   report=fixture();d=Fake(report);p=copy.deepcopy(self.proof);kwargs={}
   if change=='source':p['source_sha256']='wrong'
   if change=='cap':kwargs['max_attempts']=101
   if change=='open':d.last_response['flow']['state']='gamble'
   if change=='wire':report['modes'][-1]['mode']['options']['bet']=20
   with self.assertRaises(ValueError):self.m.execute(d,report,p,**kwargs)
   self.assertEqual(d.requests,[])
 def test_already_verified_conditional_is_never_replayed(self):
  report=fixture();report['modes'][10].update(status='closed',gamble_choices_financially_verified=['s']);saved=copy.deepcopy(report['modes'][10]);d=Fake(report)
  self.m.execute(d,report,self.proof)
  self.assertEqual(report['modes'][10],saved);self.assertNotIn('s',[q[1]['bet'] for q in d.requests if q[0]=='gamble'])
 def test_independent_audit_rejects_native_tamper_or_second_gamble_level(self):
  report=fixture();d=Fake(report);self.m.execute(d,report,self.proof,max_attempts=1)
  tampered=copy.deepcopy(report);tampered['events'][-1]['response']['balance']['wallet']+=1
  self.assertGreater(self.m.audit_extension(tampered,self.proof)['failed'],0)
  tampered=copy.deepcopy(report);tampered['events'].append(copy.deepcopy(tampered['events'][-1]))
  self.assertGreater(self.m.audit_extension(tampered,self.proof)['failed'],0)
 def test_paid_native_mismatch_stops_before_any_gamble_and_preserves_received_response(self):
  report=fixture()
  class WrongDebit(Fake):
   def call(self,command,options=None):
    after=super().call(command,options);after['balance']['wallet']+=1;self.events[-1]['response']=copy.deepcopy(after);return after
  d=WrongDebit(report);self.m.execute(d,report,self.proof)
  self.assertEqual([q[0] for q in d.requests],['spin']);self.assertEqual(report['events'][-1]['response']['balance']['wallet'],9991)
  self.assertEqual(report['dig_finite_conditional']['status'],'needs_review');self.assertGreater(report['dig_finite_conditional']['audit']['failed'],0)
  self.assertEqual(report['modes'][10]['status'],'needs_trigger');self.assertFalse(report['checks'][0]['ok'])

if __name__=='__main__':unittest.main()
