"""Actions certified against each current native client and visible state."""
from native import resolved
from wire_contract import action_fields
def continuation(state,init,source,bet):
 cur=resolved(state);feature=init['features'].get(cur,{})
 if feature.get('@type')=='features.slot.SlotFeature':return {'@type':'features.slot.action.SpinAction','betParams':bet}
 if feature.get('@type')=='features.pickme.PickMeFeature':
  if 'pickMe(t,i){this.customEvent=i,this._actionRequest(e.RequestAction.PickMe,null,t)}' not in source or not any(t in source for t in ['e.BackendController.pickMe(t,e.EventGame.PickMeData)','e.BackendController.pickMe(t,e.EventGame.SurpriseResult)']):raise ValueError('pickme_native_contract_not_certified')
  s=state['states'][cur];choices=s.get('choices')
  if not isinstance(choices,list) or s.get('steps',0)<=0:raise ValueError('pickme_choices_unavailable')
  for n,v in enumerate(choices):
   if v==-1:return {'@type':'features.pickme.action.PickMeAction','choice':n}
  raise ValueError('pickme_no_hidden_choices')
 if feature.get('@type')=='features.match3.Match3Feature':
  required=['e.BackendController.pickMe(t,e.EventGame.Match3Data)','pickMe(t,i){this.customEvent=i,this._actionRequest(e.RequestAction.PickMe,null,t)}']
  if not all(t in source for t in required) or not action_fields(source):raise ValueError('match3_native_contract_not_certified')
  choices=state['states'][cur].get('choices')
  if not isinstance(choices,list) or not choices or not all(isinstance(v,int) for v in choices):raise ValueError('match3_visible_choices_unknown')
  for n,v in enumerate(choices):
   if v==-1:return {'@type':'features.pickme.action.PickMeAction','choice':n}
  raise ValueError('match3_no_hidden_choices')
 raise ValueError('unknown_interactive_'+cur+'_'+str(feature.get('@type')))
