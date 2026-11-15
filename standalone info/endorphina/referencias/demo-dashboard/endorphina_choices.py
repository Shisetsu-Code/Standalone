"""Choices declared by native states; action fields verified in captured clients."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

CONFIG={}
for _path in (Path(__file__).resolve().parent/'endorphina'/'batches').glob('*/features.json'):
    CONFIG.update({r['slug']:r.get('features',[]) for r in json.loads(_path.read_text(encoding='utf8'))})


def selection_feature(feature):
    name=feature['featureClassName']
    return feature['featureID']=='FREE_GAME' and ('SelectionFreegamesFeature' in name or name=='ChunjieFreegamesFeature')


def features_from_config(config):
    features=deepcopy(config['game']['features'])
    selections=set()
    for control in config.get('input',[]):
        for action in control.get('actions',{}).get('onClick',[]):
            event=action.get('event',{})
            value=event.get('arg')
            if event.get('className')=='FREEGAMES_SELECT' and type(value) is int and value>=0:
                selections.add(value)
    if selections:
        for feature in features:
            if selection_feature(feature):
                feature['selection_inputs']=sorted(selections)
    return features


def point(feature,slug=None):
    state=feature.get('current_state',{})
    fid=feature['feature_id']
    field='player_choice'
    if fid=='PICKME_EXTENDED':
        level=state['level']
        cells=state['items'][level]
        keys=[i for i,v in enumerate(cells) if v==-1]
        kind='hidden_pick'
        action='logic.api.gamelogic.pickmeExtended.PickMeExtendedAction'
    elif fid in ('PICKME','MATCH3'):
        level=state.get('level',0)
        cells=state['field']
        keys=[i for i,v in enumerate(cells) if isinstance(v,(int,float)) and v<0]
        kind='hidden_pick'
        action='logic.api.gamelogic.'+('pickme.PickMe_Action' if fid=='PICKME' else 'match3.Match3_Action')
    elif fid=='CHANCE_WIN':
        level=state.get('position',0)
        cells=state['field']
        keys=list(range(len(cells)))
        kind='chance_selection'
        action='logic.api.gamelogic.chance.Chance_Action'
    elif fid=='PYRAMID_WIN':
        stage=state['level']
        level=str(stage)+':'+str(state['row_in_pyramid'] if stage else 0)
        if stage==0:
            cells=[0,1]
            keys=[1,0] if state['tries']>0 else [1]
        elif stage==1:
            cells=state['pyramid_fields'][state['row_in_pyramid']]
            keys=list(range(len(cells)))
        else:
            raise ValueError('unknown_pyramid_stage')
        kind='pyramid_selection'
        action='logic.api.gamelogic.pyramid.Pyramid_Action'
    elif fid=='PENALTY':
        level='attack' if state['isAttackPhase'] else 'defend'
        cells=state['field']
        keys=list(range(len(cells)))
        kind='penalty_selection'
        action='logic.api.gamelogic.penalty.Penalty_Action'
        field='playerChoice'
    elif fid=='FREE_GAME':
        config=next((f for f in CONFIG.get(slug,[]) if selection_feature(f)),None)
        selecting=state.get('played_free_games')==0 or state.get('not_played_free_games')==0 and state.get('number_of_lucky_free_games_retriggers',0)>0
        if not config or not selecting:return None
        choices=next((s['choice'] for s in state.get('states') or [] if isinstance(s.get('choice'),list)),None)
        cells=choices or config.get('params',{}).get('multipliers') or config.get('selection_inputs')
        if not cells:raise ValueError('missing_freegames_selection_options')
        keys=config['selection_inputs'] if not choices and not config.get('params',{}).get('multipliers') else list(range(len(cells)))
        level='initial' if state.get('played_free_games')==0 else 'retrigger'
        kind='freegames_selection'
        action='logic.api.gamelogic.freegames.Free_Games_Choose_Type_Action'
    else:
        return None
    if not keys:return None
    family={'feature':fid,'name':feature.get('feature_name',''),'kind':kind,'level':level,'size':len(cells),'action_type':action}
    node=hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16]
    return {'node':node,'family':family,'options':keys,'action_type':action,'field':field}
