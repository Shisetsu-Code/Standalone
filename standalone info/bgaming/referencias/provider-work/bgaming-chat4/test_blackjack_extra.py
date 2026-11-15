"""Static official source gates and synthetic original-native blackjack ledgers."""
import copy
import importlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parents[1]/'bgaming-private-chat4/research'
GAMES=('BlackjackPro','MultihandBlackjack','ClassicMultihandBlackjack','MultihandBlackjackPro2','SurrenderMultihandBlackjack')

def source(gid):
 p=PRIVATE/'classic/casino.min.js' if gid in GAMES[:2] else next((PRIVATE/'legacy'/gid).glob('*/bundle.js'))
 return p.read_text(encoding='utf8')
def initial(gid):return json.loads((ROOT/'live'/(gid+'.json')).read_text())['events'][0]['response']
def area(name='area_1',bet=100,win=0,status='alive',**extra):return dict(name=name,main={'bet':bet,'win_amount':win},status=status,**extra)
def modern(balance,areas,current='area_1',commands=('stand','hit'),state='active'):
 return {'balance':balance,'areas':areas,'current_area':current,'game':{'state':state},'available_commands':list(commands)}
def classic(balance,bets,current='1',commands=('stand','hit'),win=None,state='hit'):
 r={'balance':balance,'bets':bets,'game':{'state':state,'current_hand':current,'hands':{}},'available_commands':list(commands)}
 if win is not None:r['result']={'total':win,'hands':{}}
 return r

class BlackjackTests(unittest.TestCase):
 def setUp(self):self.m=importlib.import_module('blackjack_extra')
 def modes(self,gid):return self.m.plan(initial(gid),self.m.metadata(source(gid),gid))
 def test_five_source_families_have_distinct_native_wires(self):
  for gid in GAMES:
   modes=self.modes(gid);self.assertTrue(modes)
   self.assertTrue(all(m['command']==('deal' if gid in GAMES[:2] else 'start') for m in modes))
  with self.assertRaises(ValueError):self.m.metadata('command:"start"','ClassicMultihandBlackjack')
 def test_only_native_max_side_bet_clients_get_side_modes(self):
  self.assertFalse(any('perfect_pair' in m['name'] for m in self.modes('ClassicMultihandBlackjack')))
  for gid in ('MultihandBlackjackPro2','SurrenderMultihandBlackjack'):
   self.assertTrue(any('perfect_pair' in m['name'] for m in self.modes(gid)))
   self.assertTrue(any('twenty_one' in m['name'] for m in self.modes(gid)))
 def test_classic_pro_deal_uses_chip_bonus_and_exact_native_sum(self):
  mode=next(m for m in self.modes('BlackjackPro') if 'bonus' in m['name'])
  bet=next(iter(mode['options'].values()));self.assertEqual(bet,{'chip':100,'bonus':100});self.assertEqual(mode['cost_native'],200)
 def test_modern_hand_ids_come_from_registered_prefabs(self):
  for gid,count in [('ClassicMultihandBlackjack',3),('MultihandBlackjackPro2',5),('SurrenderMultihandBlackjack',3)]:
   meta=self.m.metadata(source(gid),gid);self.assertEqual(meta['hand_ids'],['area_'+str(i) for i in range(1,count+1)])
 def test_each_native_hand_count_has_normal_selector_coverage(self):
  for gid in GAMES:
   meta=self.m.metadata(source(gid),gid);modes=self.modes(gid)
   counts={len(m['options']['areas']) if gid not in GAMES[:2] else len(m['options']) for m in modes if m['target']=='normal'}
   self.assertEqual(counts,set(range(1,len(meta['hand_ids'])+1)))
 def test_split_receipts_do_not_double_parent_or_side_bet(self):
  pp={'bet':100,'win_amount':300}
  parent=area(bet=100,status='splited',perfect_pair=pp)
  children=[area('splited_1_area_1',win=200,perfect_pair=pp),area('splited_2_area_1',win=0,perfect_pair=pp)]
  totals=self.m.area_totals([parent]+children)
  self.assertEqual(totals,{'stake_native':300,'win_native':500})
 def test_insurance_price_is_half_original_hand_and_skip_is_free(self):
  before=modern(99900,[area()],commands=('insurance',))
  self.assertEqual(self.m.request_cost('MultihandBlackjackPro2',{'command':'insurance','options':{'areas':['area_1']}},initial('MultihandBlackjackPro2'),before),50)
  self.assertEqual(self.m.request_cost('MultihandBlackjackPro2',{'command':'insurance','options':{'areas':[]}},initial('MultihandBlackjackPro2'),before),0)
 def test_area_action_cannot_target_dealer_or_inactive_hand(self):
  before=modern(99900,[area()],commands=('double',))
  with self.assertRaises(ValueError):self.m.request_cost('MultihandBlackjackPro2',{'command':'double','options':{'area_name':'dealer'}},initial('MultihandBlackjackPro2'),before)
 def test_modern_side_award_is_not_credited_again_at_stand_or_finish(self):
  gid='MultihandBlackjackPro2';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/perfect_pair')
  pp={'bet':100,'win_amount':300}
  d=Demo(i,[modern(100100,[area(perfect_pair=pp)],commands=('stand',)),
            modern(100100,[area(perfect_pair=pp,status='closed')],current='none',commands=('finish',),state='finished'),
            {'balance':100100,'game':{'state':'closed'},'available_commands':['init','start']}])
  result=self.m.run(d,mode,i)
  self.assertEqual(result['status'],'closed');self.assertEqual([c['win_native'] for c in d.money_checks],[300,0,0])
  self.assertEqual(d.requests[1],('stand',{'area_name':'area_1'}))
 def test_modern_double_additional_native_stake_is_not_hidden(self):
  gid='ClassicMultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/double')
  d=Demo(i,[modern(99900,[area()],commands=('double','stand')),
            modern(100200,[area(bet=200,win=400,status='closed')],current='none',commands=('finish',),state='finished'),
            {'balance':100200,'game':{'state':'closed'},'available_commands':['start']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'closed');self.assertEqual([c['cost_native'] for c in d.money_checks],[100,100,0])
 def test_classic_pro_side_credit_then_fresh_terminal_result(self):
  gid='BlackjackPro';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='1/bonus')
  bets={'1':{'chip':100,'bonus':100},'total':200}
  d=Demo(i,[classic(100100,bets,win=300,commands=('stand',)),classic(100300,bets,current='',win=200,commands=('finish',),state='finished'),
            {'balance':100300,'game':{'state':'closed'},'available_commands':['deal']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'closed');self.assertEqual(d.requests[1],('stand',None))
 def test_unavailable_split_target_closes_without_fake_coverage(self):
  gid='MultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='1/split');bets={'1':{'chip':100},'total':100}
  d=Demo(i,[classic(99900,bets,commands=('stand',)),classic(99900,bets,current='',win=0,commands=('finish',),state='finished'),
            {'balance':99900,'game':{'state':'closed'},'available_commands':['deal']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'needs_trigger');self.assertFalse(any(q[0]=='split' for q in d.requests))
 def test_native_wallet_mismatch_is_retained_and_never_patched(self):
  gid='ClassicMultihandBlackjack';i=initial(gid);mode=self.modes(gid)[0];bad=modern(99999,[area()],commands=('stand',));d=Demo(i,[bad])
  with self.assertRaises(ValueError):self.m.run(d,mode,i)
  self.assertIs(d.prev,bad);self.assertEqual(bad['balance'],99999)
 def test_audit_derives_split_cost_from_current_raw_receipt(self):
  gid='MultihandBlackjack';i=initial(gid)
  start={'command':'deal','options':{'1':100}};one={'1':{'chip':100},'total':100};two={'1':{'chip':100},'2':{'chip':100},'total':200}
  steps=[(start,classic(99900,one,commands=('split','stand'))),
   ({'command':'split','options':{'hand_id':'2'}},classic(99800,two,current='1',commands=('stand',))),
   ({'command':'stand'},classic(99800,two,current='2',commands=('stand',))),
   ({'command':'stand'},classic(100000,two,current='',win=200,commands=('finish',),state='finished')),
   ({'command':'finish'},{'balance':100000,'game':{'state':'closed'},'available_commands':['deal']})]
  r=report(gid,i,steps);result=self.m.audit(r)
  self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],200);self.assertEqual(result['paid_attempts'],1)
 def test_original_init_only_reports_are_not_gameplay(self):
  for gid in GAMES:
   result=self.m.audit(report(gid,initial(gid),[]))
   self.assertEqual(result['failed'],0);self.assertEqual(result['paid_attempts'],0);self.assertEqual(result['rounds'],0)
 def test_modern_insurance_debit_and_known_main_receipt_are_checked(self):
  gid='ClassicMultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/insurance_accept')
  a=modern(99900,[area()],commands=('insurance',));b=modern(99850,[area(insured=True)],commands=('stand',))
  c=modern(100050,[area(win=200,status='closed',insured=True)],current='none',commands=('finish',),state='finished')
  end={'balance':100050,'game':{'state':'closed'},'available_commands':['start']}
  d=Demo(i,[a,b,c,end]);self.assertEqual(self.m.run(d,mode,i)['status'],'closed')
  self.assertEqual(d.requests[1],('insurance',{'areas':['area_1']}));self.assertEqual([x['cost_native'] for x in d.money_checks],[100,50,0,0])
  audited=self.m.audit(report(gid,i,[({'command':'start','options':mode['options']},a),({'command':'insurance','options':{'areas':['area_1']}},b),({'command':'stand','options':{'area_name':'area_1'}},c),({'command':'finish'},end)]))
  self.assertEqual(audited['failed'],0);self.assertEqual(audited['cost_native'],150)
 def test_unknown_insurance_payout_never_becomes_a_fabricated_balance(self):
  gid='ClassicMultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/insurance_accept')
  first=modern(99900,[area()],commands=('insurance',));unknown=modern(100000,[area(win=0,insured=True,status='closed')],current='none',commands=('finish',),state='finished')
  d=Demo(i,[first,unknown])
  with self.assertRaises(ValueError):self.m.run(d,mode,i)
  self.assertIs(d.prev,unknown);self.assertEqual(unknown['balance'],100000)
 def test_surrender_native_refund_is_original_main_receipt(self):
  gid='SurrenderMultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/surrender')
  d=Demo(i,[modern(99900,[area()],commands=('surrender','stand')),
            modern(99950,[area(win=50,status='closed',surrended=True)],current='none',commands=('finish',),state='finished'),
            {'balance':99950,'game':{'state':'closed'},'available_commands':['start']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'closed');self.assertEqual(d.money_checks[1]['win_native'],50)
 def test_audit_rejects_false_conditional_claim_and_forged_action_price(self):
  gid='MultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='1/split');bets={'1':{'chip':100},'total':100}
  steps=[({'command':'deal','options':{'1':100}},classic(99900,bets,commands=('stand',))),
         ({'command':'stand'},classic(99900,bets,current='',commands=('finish',),win=0,state='finished')),
         ({'command':'finish'},{'balance':99900,'game':{'state':'closed'},'available_commands':['deal']})]
  r=report(gid,i,steps);r['modes']=[{'mode':mode,'status':'closed','first_event':1,'last_event':3}]
  self.assertGreater(self.m.audit(r)['failed'],0)
  r['modes']=[];r['events'][1]['response']['balance']=99999
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_split_side_receipts_follow_first_native_root_as_official_source(self):
  parent=area(status='splited',perfect_pair={'bet':100,'win_amount':300})
  children=[area('splited_1_area_1',win=0,perfect_pair={'bet':100,'win_amount':0}),area('splited_2_area_1',win=0,perfect_pair={'bet':100,'win_amount':0})]
  self.assertEqual(self.m.area_totals([parent]+children),{'stake_native':300,'win_native':300})
 def test_actual_surrender_engine_win_is_hypothetical_not_native_payout(self):
  gid='SurrenderMultihandBlackjack';i=initial(gid)
  before=modern(99500,[area()],commands=('surrender','stand'));before['game']['state']='alive'
  raw_area=area(win=200,status='surrended',surrended=True);raw_area['main']['multiplier']=2
  response=modern(99550,[raw_area],current='none',commands=('init','finish'),state='finished');response['game']['action']='surrender'
  saved=copy.deepcopy(response);ledger=self.m.new_ledger();ledger.update(stake_native=100)
  checked=self.m.reconcile(gid,before,response,{'command':'surrender','options':{'area_name':'area_1'}},i,ledger)
  self.assertEqual(checked['expected'],99550);self.assertEqual(checked['win_native'],50)
  self.assertEqual(checked['raw_engine_win_native'],200);self.assertEqual(checked['native_surrender_refund'],50)
  self.assertEqual(response,saved)
 def test_received_surrender_normalizes_offline_and_sends_finish_only(self):
  gid='SurrenderMultihandBlackjack';i=initial(gid);mode=next(m for m in self.modes(gid) if m['name']=='area_1/surrender')
  first=modern(99900,[area()],commands=('surrender','stand'))
  raw_area=area(win=200,status='surrended',surrended=True);cash=modern(99950,[raw_area],current='none',commands=('init','finish'),state='finished');cash['game']['action']='surrender'
  done={'balance':99950,'game':{'state':'closed'},'available_commands':['init','start']}
  r=report(gid,i,[({'command':'start','options':mode['options']},first),({'command':'surrender','options':{'area_name':'area_1'}},cash)])
  d=Demo(cash,[done]);d.last_response=cash;d.events=r['events'];result=self.m.resume_received(d,mode,i)
  self.assertEqual(d.requests,[('finish',None)]);self.assertEqual(result['status'],'closed');self.assertEqual(result['first_event'],1)
  checked=next(c for c in d.money_checks if c.get('normalized_received_surrender'))
  self.assertEqual(checked['win_native'],50);self.assertEqual(checked['raw_engine_win_native'],200)

def report(gid,i,steps):
 return {'game':{'game_id':gid},'status':'test','protocol':'blackjack-extra','modes':[],
         'checks':[{'cost_native':1,'ok':True}],
         'events':[{'request':{'command':'init'},'response':i,'status':200}]+[
          {'request':q,'response':r,'status':200} for q,r in steps]}

class Demo:
 def __init__(self,i,responses):self.prev=i;self.responses=iter(responses);self.events=[];self.requests=[];self.money_checks=[]
 def call(self,command,options=None):
  self.requests.append((command,options));r=next(self.responses);self.events.append({'response':r});return r

if __name__=='__main__':unittest.main()
