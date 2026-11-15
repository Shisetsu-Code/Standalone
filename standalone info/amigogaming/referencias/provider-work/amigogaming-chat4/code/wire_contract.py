"""Bind local variable renaming to the actual native action object."""
import re
def action_fields(source):
 match=re.search(r'_actionRequest\((\w+),(\w+),(\w+)=null\)\{var (\w+)=\{"@type":(\w+)\.Requests\.Action,id:this\.messageID,action:\{"@type":\1\}\};(?:switch|if)\(\2&&\(\4\.action\.betParams=\5\.BetsController\.getBetParams\(\)\)',source)
 if not match:return None
 action,paid,choice,obj,namespace=match.groups()
 buy_supported=f'this.buyInId&&({obj}.action.buyInId=this.buyInId,this.buyInId=null)' in source
 sequential=f'case {namespace}.RequestAction.PickMe:case {namespace}.RequestAction.Sequential:{obj}.action.choice={choice}' in source
 pickme_only=f'{action}==={namespace}.RequestAction.PickMe){obj}.action.choice={choice}' in source
 if not sequential and not pickme_only:return None
 return {'action_object':obj,'namespace':namespace,'choice_variable':choice,'sequential_supported':sequential,'buy_supported':buy_supported}
