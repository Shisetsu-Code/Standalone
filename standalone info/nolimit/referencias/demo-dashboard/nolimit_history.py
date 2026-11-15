"""Native menus from archived attempts remain discovery evidence after a retry."""
import json
from nolimit_protocol import choice_point

def history_points(folder,bases):
    roots={r['case']:r for r in bases};result=[]
    for path in sorted((folder/'attempts').rglob('*.json')):
        document=json.loads(path.read_text(encoding='utf8'));summary=document.get('summary',{})
        root=summary.get('root_case',summary.get('case'));base=roots.get(root)
        if not base or summary.get('code')!=base['code'] or summary.get('control_id')!=base.get('control_id'):continue
        seen=set()
        for step in document.get('trace',[]):
            for reply in step.get('responses',[]):
                if reply.get('id')!=step['request']['id'] or not reply.get('game'):continue
                point=choice_point(reply['game'],base['code'])
                if not point:continue
                signature=(point['node'],tuple(point['options']))
                if signature in seen:continue
                seen.add(signature);result.append({'root':root,'source':str(path.relative_to(folder)),'point':point})
    return result
