"""Offline Wild Moon manual-door policy and native receipt audits; no live calls."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent


def old_report():
 archive=ROOT/'live/attempts/WildMoonThieves.before-manual-doors.json'
 return json.loads((archive if archive.exists() else ROOT/'live/WildMoonThieves.json').read_text())


def init():
 return {'api_version':'2','options':{'available_bets':[25,50],
  'currency':{'code':'FUN','subunits':100},'feature_options':{'feature_multipliers':{'base_bet':25,'freespin_buy':2500,'bonus_buy':2500},'disabled_features':[]}},
  'balance':{'wallet':100000,'game':0},'flow':{'state':'closed','available_actions':['init','spin'],'round_id':None,'last_action_id':None}}


def door_response(wallet,history,new,finished,action,round_id='round-1'):
 return {'api_version':'2','balance':{'wallet':wallet,'game':0},
  'features':{'preselection_game':{'doors_auto_open_flag':False,'doors':history,'new_doors':new,'finished':finished}},
  'flow':{'round_id':round_id,'last_action_id':action,'command':'play_preselection_game',
          'state':'freespins' if finished else 'preselection_game','available_actions':['init','freespin'] if finished else ['init','play_preselection_game']},
  'outcome':{'bet':25,'win':0}}


def trigger(wallet=97500,round_id='round-1'):
 return {'api_version':'2','balance':{'wallet':wallet,'game':0},'features':{},'outcome':{'bet':25,'win':0},
  'flow':{'state':'preselection_game','available_actions':['init','play_preselection_game'],
   'round_id':round_id,'last_action_id':round_id+'-start','command':'spin','purchased_feature':{'name':'freespin_buy'}}}


def child_context(indices):
 events=[{'request':{'command':'init'},'response':init(),'status':200}];modes=[];wallet=100000
 for ordinal,index in enumerate(indices):
  start=len(events);wallet-=2500;rid='round-'+str(ordinal+1);t=trigger(wallet,rid)
  events.append({'request':{'command':'spin','options':{'bet':25,'purchased_feature':'freespin_buy'}},'response':t,'status':200})
  opened=[{'index':index,'wilds':0}];doors=door_response(wallet,opened,opened,True,rid+'-door',rid)
  events.append({'request':{'command':'play_preselection_game','options':{'index':index}},'response':doors,'status':200})
  end={'balance':{'wallet':wallet,'game':0},'outcome':{'bet':25,'win':0},'features':{},
       'flow':{'state':'closed','command':'freespin','available_actions':['init','spin'],'round_id':rid,'last_action_id':rid+'-free'}}
  events.append({'request':{'command':'freespin'},'response':end,'status':200})
  modes.append({'mode':{'name':'manual_first_door:'+str(index),'command':'spin','options':{'bet':25,'purchased_feature':'freespin_buy'},'cost_native':2500,'manual_initial_door':index},
                'status':'closed','first_event':start,'last_event':len(events)-1,'final_state':'closed','final_balance':end['balance']})
 return {'game':{'game_id':'WildMoonThieves'},'status':'testing','events':events,'modes':modes,'declared_modes':[m['mode'] for m in modes],'checks':[]}


class WildMoonManualTests(unittest.TestCase):
 def setUp(self):
  self.m=importlib.import_module('run_wild_moon_manual');self.proof=self.m.cached_proof()
 def test_received_freespin_buy_is_only_matching_preselection_trigger(self):
  chosen=self.m.select_trigger(old_report(),init())
  self.assertEqual(chosen['options'],{'bet':25,'purchased_feature':'freespin_buy'})
  self.assertEqual(chosen['cost_native'],2500)
 def test_sixteen_targets_do_not_rebuy_old_three_modes(self):
  modes=self.m.manual_modes(old_report(),init(),self.proof)
  self.assertEqual([m['manual_initial_door'] for m in modes],list(range(16)))
  self.assertTrue(all(m['options']=={'bet':25,'purchased_feature':'freespin_buy'} for m in modes))
  self.assertEqual(sum(m['cost_native'] for m in modes),40000)
 def test_manual_first_target_then_lowest_unopened_and_exact_wallet(self):
  first=[{'index':7,'wilds':3}];both=first+[{'index':0,'wilds':0}]
  d=Fake([door_response(97500,first,first,False,'a1'),door_response(97500,both,both[1:],True,'a2')]);d.active_mode={'manual_initial_door':7}
  result=self.m.play_manual_doors(d,trigger(),self.proof,7)
  self.assertEqual([q['options'] for q in d.requests],[{'index':7},{'index':0}])
  self.assertEqual(result['flow']['state'],'freespins');self.assertEqual(len(d.money_checks),2)
  self.assertTrue(all(c['ok'] for c in d.money_checks))
 def test_opened_target_or_changed_money_stops_without_retry(self):
  before=trigger();before['features']={'preselection_game':{'doors':[{'index':7,'wilds':2}]}}
  d=Fake([])
  with self.assertRaises(ValueError):self.m.play_manual_doors(d,before,self.proof,7)
  self.assertEqual(d.requests,[])
  changed=door_response(97501,[{'index':7,'wilds':0}],[{'index':7,'wilds':0}],True,'a1')
  d=Fake([changed])
  with self.assertRaises(ValueError):self.m.play_manual_doors(d,trigger(),self.proof,7)
  self.assertEqual(len(d.requests),1);self.assertEqual(changed['balance']['wallet'],97501)
 def test_base_settle_cannot_dispatch_automatic_door_or_another_purchase(self):
  opened=[{'index':7,'wilds':0}];d=Fake([door_response(97500,opened,opened,True,'a1')]);d.manual_proof=self.proof;d.active_mode={'manual_initial_door':7}
  def bad_base(self,response):return self.call('play_preselection_game',{'mode':'auto'})
  with patch.object(self.m.Demo,'settle',bad_base):
   with self.assertRaises(RuntimeError):self.m.ManualWildMoonDemo.settle(d,trigger())
  self.assertEqual(len(d.requests),1);self.assertEqual(d.requests[0]['options'],{'index':7})
 def test_audit_all_sixteen_initial_choices_requires_actual_native_receipts(self):
  context=child_context(range(16));saved=copy.deepcopy(context)
  audit=self.m.audit_manual_context(context,self.proof)
  self.assertEqual(audit['failed'],0);self.assertTrue(audit['complete']);self.assertEqual(audit['first_indices_executed'],list(range(16)))
  self.assertEqual(audit['paid_attempts'],16);self.assertEqual(audit['cost_native'],40000);self.assertEqual(context,saved)
 def test_duplicate_first_choices_do_not_claim_all_initial_indices(self):
  context=child_context([7]*16);audit=self.m.audit_manual_context(context,self.proof)
  self.assertFalse(audit['complete']);self.assertEqual(audit['first_indices_executed'],[7]);self.assertEqual(len(audit['pending_initial_indices']),15)
 def test_tampered_price_or_door_history_is_not_accepted(self):
  context=child_context([7]);context['events'][1]['response']['balance']['wallet']+=1
  self.assertGreater(self.m.audit_manual_context(context,self.proof)['failed'],0)
  context=child_context([7]);context['events'][2]['response']['features']['preselection_game']['new_doors']=[]
  self.assertGreater(self.m.audit_manual_context(context,self.proof)['failed'],0)
 def test_derived_report_preserves_original_context_and_scopes_aliases(self):
  old=old_report();saved=copy.deepcopy(old);new=child_context(range(16));combined=self.m.derive_report(old,new,self.proof)
  self.assertEqual(old,saved);self.assertEqual(combined['contexts'][0]['report'],old)
  self.assertNotIn('events',combined);self.assertEqual(len(combined['modes']),19)
  self.assertEqual(len(combined['declared_modes']),19)
  self.assertEqual({m['context_id'] for m in combined['declared_modes']},{'original','manual-doors'})
  self.assertEqual({m['context_id'] for m in combined['modes']},{'original','manual-doors'})
  self.assertTrue(combined['manual_door_coverage']['complete'])
  self.assertEqual(combined['contexts'][0]['report'].get('provider_state_observations'),old.get('provider_state_observations'))
 def test_output_paths_keep_one_canonical_flat_live_report(self):
  context,canonical=self.m.output_paths(ROOT)
  self.assertEqual(context,ROOT/'live/bonus-contexts/WildMoonThieves.manual-doors.context.json')
  self.assertEqual(canonical,ROOT/'live/WildMoonThieves.json')
 def test_once_archive_never_overwrites_existing_bytes(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'old.json';self.m.write_once(p,b'original')
   with self.assertRaises(FileExistsError):self.m.write_once(p,b'replacement')
   self.assertEqual(p.read_bytes(),b'original')
 def test_source_pin_and_native_feature_price_are_required(self):
  proof=copy.deepcopy(self.proof);proof['source_sha256']='0'*64
  with self.assertRaises(ValueError):self.m.manual_modes(old_report(),init(),proof)
  first=init();first['options']['feature_options']['feature_multipliers']['base_bet']=24
  with self.assertRaises(ValueError):self.m.select_trigger(old_report(),first)


class Fake:
 def __init__(self,responses):
  self.responses=iter(responses);self.events=[];self.requests=[];self.money_checks=[];self.choice_actions=[];self.game={'game_id':'WildMoonThieves'}
 def call(self,command,options=None):
  q={'command':command}
  if options is not None:q['options']=options
  self.requests.append(q);r=next(self.responses);self.last_response=r
  self.events.append({'request':q,'response':r,'status':200});return r

if __name__=='__main__':unittest.main()
