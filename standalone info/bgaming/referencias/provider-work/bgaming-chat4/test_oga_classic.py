import unittest
from oga_classic import parse,customize,continuation_contracts
class ClassicOGA(unittest.TestCase):
 def client(self,stake=False):
  return 'params.req.custom_req=t.formattedRequest.params;formattedRequest.params.action=t.type;'+('formattedRequest.params.stake=t.stake;' if stake else '')
 def test_nested_line_count_is_not_a_wire_field(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:Array.from({length:20},((t,e)=>e)),perLine:!0,isNormalBuy:!1,isSuperBuy:!1}}};x.params.isNormalBuy=!0;x.params.isSuperBuy=!0;'
  meta=parse({'engine':{'definition':{'normalBuyCost':100,'superBuyCost':200}}},source,'',self.client())
  self.assertNotIn('length',meta['normal_custom_params']);self.assertEqual(meta['normal_custom_params']['selectedWinLines'],list(range(20)));self.assertEqual([v['factor'] for v in meta['variants']],['100','200']);self.assertFalse(meta['variants'][0]['custom_params']['isSuperBuy']);self.assertTrue(meta['variants'][1]['custom_params']['isSuperBuy'])
 def test_custom_stake_only_when_client_adds_it(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:[0],perLine:!0}}};'
  for stake in [False,True]:
   meta=parse({'engine':{'definition':{}}},source,'',self.client(stake));req=customize(meta,{},10,'spin',True);self.assertEqual(req['selectedWinLines'],[0]);self.assertEqual(req['action'],'spin');self.assertEqual('stake' in req,stake)
 def test_unmapped_buy_cost_stays_pending(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:[],perLine:!0}}};'
  meta=parse({'engine':{'definition':{'mysteryBuy':300}}},source,'',self.client());self.assertIn('Unmapped price mysteryBuy',meta['unresolved'])
 def test_same_purchase_alias_has_separate_costs(self):
  from rpc_audit_hotrocket import audit_rpc
  variants=[{'feature':'buy_bonus','factor':'100','custom_params':{'isSuperBuy':False}},{'feature':'buy_bonus','factor':'200','custom_params':{'isSuperBuy':True}}]
  events=[]
  for flag,balance in [(False,99000),(True,97000)]:events.append({'request':{'params':{'req':{'bet':10,'purchased_feature':'buy_bonus','custom_req':{'isSuperBuy':flag}}}},'response':{'result':{'balance':balance,'final':True,'resp':{'win':0}}}})
  checks,rounds=audit_rpc({'result':{'balance':100000}},events,{None:'1'},variants);self.assertTrue(all(c['ok'] for c in checks));self.assertEqual([r['cost_native'] for r in rounds],[1000,2000])
 def test_game_specific_map_may_omit_shared_line_fields(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{isNormalBuy:!1,isSuperBuy:!1}}};x.params.isNormalBuy=!0;x.params.isSuperBuy=!0;'
  meta=parse({'engine':{'definition':{'normalBuyCost':100,'superBuyCost':200}}},source,'',self.client())
  self.assertEqual(meta['normal_custom_params'],{'isNormalBuy':False,'isSuperBuy':False});self.assertNotIn('perLine',customize(meta,{},100,'spin',True))
 def test_explicit_null_line_selection_is_preserved(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:null,perLine:!0,isFeatureBuyFreeSpin:!1,isFeatureBuyRespin:!1}}};'
  meta=parse({'engine':{'definition':{}}},source,'',self.client());self.assertIn('selectedWinLines',meta['normal_custom_params']);self.assertIsNone(meta['normal_custom_params']['selectedWinLines'])
 def test_unknown_dynamic_field_not_silently_omitted(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:helper.dynamic(),perLine:!0}}};'
  with self.assertRaises(ValueError):parse({'engine':{'definition':{}}},source,'',self.client())
 def test_explicit_bonus_flags_and_rtp_are_distinct_from_money(self):
  source='x.Regular]={ActionType:A.SPIN,AdditionalData:{request:A.SPIN,params:{selectedWinLines:null,perLine:!0,isFeatureBuyFreeSpin:!1,isFeatureBuyRespin:!1}}};x.params.isFeatureBuyFreeSpin="FreeSpin"===e.Mode;x.params.isFeatureBuyRespin="Respin"===e.Mode;'
  meta=parse({'engine':{'definition':{'featureBuyMulFreespin':100,'featureBuyMulRespin':50,'buyFeatureRespinRtp':96.3}}},source,'',self.client());self.assertEqual([v['factor'] for v in meta['variants']],['100','50']);self.assertEqual(meta['unresolved'],[]);self.assertEqual(meta['non_monetary_rtp_fields'],{'buyFeatureRespinRtp':96.3})
 def test_combined_action_requires_explicit_client_assignment(self):
  source='(A=N||(N={})).SPIN="spin",A.JACKPOT_RESPIN="jackpot_respin";i.AdditionalData.request=N.JACKPOT_RESPIN,i.AdditionalData.params.action=N.JACKPOT_RESPIN;'
  actions=continuation_contracts(source);self.assertEqual(actions,{'jackpot_respin':{'action':'jackpot_respin'}})
  self.assertEqual(customize({'classic_continuations':actions},{},100,'jackpot_respin',False),{'action':'jackpot_respin','exponent':2})
  with self.assertRaises(RuntimeError):customize({'classic_continuations':{}},{},100,'jackpot_respin',False)
if __name__=='__main__':unittest.main()
